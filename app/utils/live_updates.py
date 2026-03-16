import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.utils.private_ui import show_private_screen
from app.utils.runtime import save_runtime_state

logger = logging.getLogger(__name__)
PENDING_STUCK_SECONDS = 20


def _ensure_dm_feed(state: dict) -> dict:
    feed = state.setdefault("dm_feed", {})
    feed.setdefault("news", [])
    feed.setdefault("events", [])
    feed.setdefault("insiders", [])
    return feed


def _prune_by_tick(items: list[dict], tick: int) -> bool:
    before = len(items)
    items[:] = [item for item in items if int(item.get("display_until", -1)) >= tick]
    return len(items) != before


def _update_dm_feed(state: dict, generated: dict[str, Any] | None) -> bool:
    tick = int(state.get("tick", 0))
    feed = _ensure_dm_feed(state)
    changed = False

    changed |= _prune_by_tick(feed["news"], tick)
    changed |= _prune_by_tick(feed["events"], tick)
    changed |= _prune_by_tick(feed["insiders"], tick)

    if not generated:
        return changed

    news_item = generated.get("news")
    if news_item:
        feed["news"].append(
            {
                "text": str(news_item),
                "source_tick": tick,
                "display_until": tick + 2,
            }
        )
        changed = True

    event_item = generated.get("event")
    if event_item:
        event_ticks = max(0, int(event_item.get("ticks_left", 0)))
        active_until = tick + event_ticks
        feed["events"].append(
            {
                "asset_name": event_item.get("asset_name"),
                "delta": float(event_item.get("delta", 0.0)),
                "source_tick": tick,
                "event_ticks": event_ticks,
                "active_until": active_until,
                "display_until": active_until + 1,
            }
        )
        changed = True

    insider_item = generated.get("insider")
    if insider_item:
        feed["insiders"].append(
            {
                "asset_name": insider_item.get("asset_name"),
                "forecast_percent": float(insider_item.get("forecast_percent", 0.0)),
                "true_change_percent": float(insider_item.get("true_change_percent", 0.0)),
                "source_tick": tick,
                "display_until": tick + 1,
            }
        )
        changed = True

    return changed


def _is_stale_pending(timestamp_raw: str | None) -> bool:
    if not timestamp_raw:
        return True
    try:
        timestamp = datetime.fromisoformat(timestamp_raw)
    except ValueError:
        return True
    return datetime.now(UTC) - timestamp >= timedelta(seconds=PENDING_STUCK_SECONDS)


async def refresh_private_views(
    app,
    game_id: int,
    state: dict,
    generated: dict[str, Any] | None = None,
) -> None:
    if _update_dm_feed(state, generated):
        await save_runtime_state(app, state)

    players = await app.users.player.list_by_game(game_id)
    for player in players:
        if not player.is_active:
            continue
        user = await app.users.user.get_by_id(player.user_id)
        if user is None:
            continue
        if not user.dm_chat_id:
            continue
        external_user_id = user.tg_user_id
        platform = user.platform
        fsm_state = await app.fsm.get_state(external_user_id, platform=platform)
        if not fsm_state:
            try:
                await show_private_screen(
                    app,
                    external_user_id,
                    user.dm_chat_id,
                    "main",
                    {"game_id": game_id},
                    target_platform=platform,
                )
            except Exception:
                logger.exception(
                    "Private view bootstrap failed game_id=%s player_id=%s user_id=%s platform=%s external_user_id=%s chat_id=%s",
                    game_id,
                    player.id,
                    user.id,
                    platform,
                    external_user_id,
                    user.dm_chat_id,
                )
            continue
        state_name, data = fsm_state
        if data.get("private_message_pending"):
            if not _is_stale_pending(data.get("private_message_pending_since")):
                continue
            data = dict(data)
            data["private_message_pending"] = False
            data["private_message_pending_since"] = None
            data["private_message_id"] = None
            await app.fsm.set_state(
                external_user_id,
                state_name,
                data,
                platform=platform,
            )
        screen = data.get("screen", "main")
        message_id = data.get("private_message_id")
        try:
            await show_private_screen(
                app,
                external_user_id,
                user.dm_chat_id,
                screen,
                data,
                message_id,
                target_platform=platform,
            )
        except Exception:
            logger.exception(
                "Private view refresh failed game_id=%s player_id=%s user_id=%s platform=%s external_user_id=%s chat_id=%s",
                game_id,
                player.id,
                user.id,
                platform,
                external_user_id,
                user.dm_chat_id,
            )
