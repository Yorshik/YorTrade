import asyncio
import contextlib
import logging
from datetime import datetime, timedelta, timezone
from time import monotonic

from app.clients.common.mailbox import MessagePayload
from app.market.event_engine import schedule_market_drivers
from app.market.models import GameStatus
from app.market.tick_processor import process_tick
from app.utils.achievements import apply_achievement_progress
from app.utils.live_updates import refresh_private_views
from app.utils.render import refresh_market_message
from app.utils.runtime import init_runtime_state, load_runtime_state, save_runtime_state
from app.utils.trading import build_leaderboard

logger = logging.getLogger(__name__)


def _event_dedupe_key(event_item: dict) -> tuple[object, ...]:
    event_id = str(event_item.get("event_id") or "").strip()
    if event_id:
        return ("event_id", event_id)
    return (
        "fallback",
        str(event_item.get("type") or ""),
        str(event_item.get("template_id") or ""),
        str(event_item.get("text") or ""),
        int(event_item.get("ticks_left", 0) or 0),
    )


def _dedupe_events(event_items: list[dict]) -> list[dict]:
    seen: set[tuple[object, ...]] = set()
    unique_items: list[dict] = []
    for event_item in event_items:
        key = _event_dedupe_key(event_item)
        if key in seen:
            continue
        seen.add(key)
        unique_items.append(event_item)
    return unique_items


class GameEngine:
    UI_REFRESH_TIMEOUT_SECONDS = 60.0

    def __init__(self, app, tick_interval: float = 10.0):
        self.app = app
        self.tick_interval = tick_interval
        self._tasks: dict[int, asyncio.Task] = {}
        self._tick_intervals: dict[int, float] = {}

    async def start_game(
        self, game_id: int, tick_interval: float | None = None
    ) -> None:
        task = self._tasks.get(game_id)
        if task and not task.done():
            logger.info("Game loop already running for game_id=%s", game_id)
            return

        game = await self.app.market.game.get_by_id(game_id)
        if not game:
            logger.warning("Cannot start game loop: game_id=%s not found", game_id)
            return

        self._tick_intervals[game_id] = (
            tick_interval if tick_interval is not None else self.tick_interval
        )

        state = await init_runtime_state(
            self.app,
            game_id=game.id,
            chat_id=game.chat_id,
            platform=game.platform,
        )
        # Render initial large messages immediately at game start (before first tick).
        await self._refresh_outputs(game_id, state, generated=None)
        task = asyncio.create_task(
            self.run_game_loop(game_id),
            name=f"game-loop-{game_id}",
        )
        self._tasks[game_id] = task
        logger.info("Game loop task created for game_id=%s", game_id)

    async def stop_game(self, game_id: int) -> None:
        task = self._tasks.pop(game_id, None)
        self._tick_intervals.pop(game_id, None)
        if not task:
            logger.info("Game loop stop requested for unknown game_id=%s", game_id)
            return

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def stop_all_games(self) -> None:
        game_ids = list(self._tasks.keys())
        for game_id in game_ids:
            await self.stop_game(game_id)

    async def finish_game(self, game_id: int) -> None:
        state = await load_runtime_state(self.app, game_id)
        if state is None:
            game = await self.app.market.game.get_by_id(game_id)
            if not game:
                return
            state = await init_runtime_state(
                self.app,
                game_id=game.id,
                chat_id=game.chat_id,
                platform=game.platform,
            )
        elif not state.get("platform"):
            game = await self.app.market.game.get_by_id(game_id)
            if game:
                state["platform"] = game.platform
        await self._finish_game(game_id, state)
        await self.stop_game(game_id)

    async def run_game_loop(self, game_id: int) -> None:
        logger.info("Game loop started for game_id=%s", game_id)
        try:
            while True:
                if not await self._is_game_active(game_id):
                    logger.info(
                        "Game loop stopping because game is no longer active: game_id=%s",
                        game_id,
                    )
                    return

                tick_started = monotonic()
                state = await load_runtime_state(self.app, game_id)
                if state is None:
                    game = await self.app.market.game.get_by_id(game_id)
                    if not game:
                        logger.warning(
                            "Game loop cannot restore runtime state: game_id=%s missing",
                            game_id,
                        )
                        return
                    state = await init_runtime_state(
                        self.app,
                        game_id=game_id,
                        chat_id=game.chat_id,
                        platform=game.platform,
                    )
                elif not state.get("platform"):
                    game = await self.app.market.game.get_by_id(game_id)
                    if game:
                        state["platform"] = game.platform

                if self._is_game_time_over(state):
                    await self._finish_game(game_id, state)
                    return

                tick_interval = self._tick_intervals.get(game_id, self.tick_interval)
                state["next_tick_at"] = (
                    datetime.now(timezone.utc) + timedelta(seconds=tick_interval)
                ).isoformat()
                state["tick"] += 1
                logger.info(
                    "Game tick started for game_id=%s tick=%s", game_id, state["tick"]
                )

                state, scheduled = await self._run_stage(
                    "schedule_market_drivers",
                    schedule_market_drivers(self.app, game_id, state),
                    game_id,
                    state["tick"],
                )
                state, runtime_events = await self._run_stage(
                    "process_tick",
                    process_tick(self.app, game_id, state),
                    game_id,
                    state["tick"],
                )
                event_items = list((scheduled or {}).get("events") or [])
                event_items.extend(list(runtime_events or []))
                event_items = _dedupe_events(event_items)
                generated = {
                    "event": event_items[0] if event_items else (scheduled or {}).get("event"),
                    "events": event_items,
                    "news": (scheduled or {}).get("news"),
                    "news_image_id": (scheduled or {}).get("news_image_id"),
                    "insider": (scheduled or {}).get("insider"),
                }

                await self._run_stage(
                    "save_runtime_state",
                    save_runtime_state(self.app, state),
                    game_id,
                    state["tick"],
                )
                await self._refresh_outputs(game_id, state, generated)

                elapsed = monotonic() - tick_started
                logger.info(
                    "Game tick finished for game_id=%s tick=%s duration=%.3fs",
                    game_id,
                    state["tick"],
                    elapsed,
                )
                await asyncio.sleep(max(0.0, tick_interval - elapsed))
        except asyncio.CancelledError:
            logger.info("Game loop stopped for game_id=%s", game_id)
            raise
        except Exception:
            logger.exception(
                "Unhandled exception inside game loop for game_id=%s", game_id
            )
        finally:
            current_task = self._tasks.get(game_id)
            if current_task is asyncio.current_task():
                await self._tasks.pop(game_id, None)
                self._tick_intervals.pop(game_id, None)
            logger.info("Game loop cleanup completed for game_id=%s", game_id)

    async def _run_stage(self, stage_name: str, awaitable, game_id: int, tick: int):
        started_at = monotonic()
        result = await awaitable
        elapsed = monotonic() - started_at
        logger.info(
            "Game stage finished for game_id=%s tick=%s stage=%s duration=%.3fs",
            game_id,
            tick,
            stage_name,
            elapsed,
        )
        return result

    async def _refresh_outputs(
        self, game_id: int, state: dict, generated: dict | None = None
    ) -> None:
        tick = state["tick"]
        await self._run_best_effort_stage(
            "refresh_market_message",
            refresh_market_message(self.app, game_id, state, generated=generated),
            game_id,
            tick,
        )
        await self._run_best_effort_stage(
            "refresh_private_views",
            refresh_private_views(self.app, game_id, state, generated=generated),
            game_id,
            tick,
        )

    async def _run_best_effort_stage(
        self,
        stage_name: str,
        awaitable,
        game_id: int,
        tick: int,
        timeout_seconds: float | None = None,
    ) -> None:
        started_at = monotonic()
        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else self.UI_REFRESH_TIMEOUT_SECONDS
        )
        try:
            await asyncio.wait_for(awaitable, timeout=timeout)
            elapsed = monotonic() - started_at
            logger.info(
                "Game UI stage finished for game_id=%s tick=%s stage=%s duration=%.3fs",
                game_id,
                tick,
                stage_name,
                elapsed,
            )
        except TimeoutError:
            logger.warning(
                "Game UI stage timed out for game_id=%s tick=%s stage=%s timeout=%.1fs",
                game_id,
                tick,
                stage_name,
                timeout,
            )
        except Exception:
            logger.exception(
                "Game UI stage failed for game_id=%s tick=%s stage=%s",
                game_id,
                tick,
                stage_name,
            )

    async def _is_game_active(self, game_id: int) -> bool:
        game = await self.app.market.game.get_by_id(game_id)
        return bool(game and game.status == GameStatus.ACTIVE)

    def _is_game_time_over(self, state: dict) -> bool:
        ends_at = state.get("ends_at")
        if not ends_at:
            return False
        return datetime.now(timezone.utc) >= datetime.fromisoformat(ends_at)

    async def _finish_game(self, game_id: int, state: dict) -> None:
        game = await self.app.market.game.get_by_id(game_id)
        if not game:
            return

        players = await self.app.users.player.list_by_game(game_id)
        assets_state = state.get("assets", {})
        player_results: list[dict] = []
        for player in players:
            user = await self.app.users.user.get_by_id(player.user_id)
            if user is not None:
                portfolio_rows = await self.app.market.portfolio.list_by_player(
                    player.id
                )
                assets_capital = 0.0
                for row in portfolio_rows:
                    if row.amount <= 0:
                        continue
                    asset_state = assets_state.get(str(row.asset_id))
                    if asset_state is None:
                        continue
                    assets_capital += row.amount * float(asset_state["current_price"])
                total_capital = round(float(player.balance) + assets_capital, 2)
                await self.app.users.player.leave(player, final_capital=total_capital)
                player_results.append(
                    {
                        "player_id": player.id,
                        "user_id": user.id,
                        "display_name": user.username
                        or f"пользователь_{user.platform.lower()}_{user.tg_user_id}",
                        "total_capital": total_capital,
                        "balance": round(float(player.balance), 2),
                        "assets_capital": round(assets_capital, 2),
                    }
                )
                await self.app.fsm.set_state(
                    user.tg_user_id,
                    self.app.fsm.FSM.IDLE,
                    platform=user.platform,
                )

        if player_results:
            winner = min(
                player_results,
                key=lambda item: (
                    -float(item["total_capital"]),
                    int(item["player_id"]),
                ),
            )
            await apply_achievement_progress(
                self.app,
                user_id=int(winner["user_id"]),
                add={"wins_total": 1},
            )
        game.status = GameStatus.FINISHED
        game.ended_at = datetime.now(timezone.utc)
        await self.app.market.game.save(game)
        state["status"] = "finished"
        await save_runtime_state(self.app, state)
        await refresh_market_message(self.app, game_id, state)
        await self._notify_game_finished(game, player_results)

    async def _notify_game_finished(self, game, player_results: list[dict]) -> None:
        leaderboard = await build_leaderboard(self.app, game.id)
        leaderboard_lines = []
        for index, row in enumerate(leaderboard[:20], start=1):
            leaderboard_lines.append(
                f"{index}. {row['display_name']} - {row['capital']}"
            )
        leaderboard_text = "\n".join(leaderboard_lines) or "Лидерборд пуст."

        await self.app.sender.send_message(
            MessagePayload(
                chat_id=game.chat_id,
                target_platform=game.platform,
                text=(f"Игра завершена.\n\nИтоговый лидерборд:\n{leaderboard_text}"),
            )
        )

        rank_by_player_id = {
            row["player_id"]: index for index, row in enumerate(leaderboard, start=1)
        }
        for result in player_results:
            user = await self.app.users.user.get_by_id(result["user_id"])
            if user is None or not user.dm_chat_id:
                continue
            await self.app.sender.send_message(
                MessagePayload(
                    chat_id=user.dm_chat_id,
                    target_platform=user.platform,
                    text=(
                        "Игра завершена.\n"
                        f"Место: {rank_by_player_id.get(result['player_id'], '-')}\n"
                        f"Баланс: {result['balance']}\n"
                        f"Капитал активов: {result['assets_capital']}\n"
                        f"Итоговый капитал: {result['total_capital']}"
                    ),
                )
            )
