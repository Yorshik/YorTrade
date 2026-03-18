from asyncio import Lock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.clients.common.mailbox import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MessagePayload,
)
from app.utils.charts import generate_market_overview_chart
from app.utils.runtime import RuntimeState, save_runtime_state
from app.utils.trading import build_leaderboard

MAX_GROUP_INLINE_PLAYERS = 6
MAX_GROUP_INLINE_ASSETS = 6
MAX_CAPTION_LENGTH = 1024
PENDING_STUCK_SECONDS = 20

GROUP_VIEW_MAIN = "main"
GROUP_VIEW_LEADERBOARD = "leaderboard"
GROUP_VIEW_MARKET = "market"
GROUP_VIEW_KEY = "market_view"
_MARKET_REFRESH_LOCKS: dict[int, Lock] = {}
PICTURES_DIR = Path(__file__).resolve().parents[2] / "data" / "pictures"
_SUPPORTED_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")


def _normalize_view(view: str | None) -> str:
    raw = (view or GROUP_VIEW_MAIN).strip().lower()
    if raw in {GROUP_VIEW_MAIN, GROUP_VIEW_LEADERBOARD, GROUP_VIEW_MARKET}:
        return raw
    return GROUP_VIEW_MAIN


def _market_refresh_lock(game_id: int) -> Lock:
    lock = _MARKET_REFRESH_LOCKS.get(game_id)
    if lock is None:
        lock = Lock()
        _MARKET_REFRESH_LOCKS[game_id] = lock
    return lock


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


def _dedupe_generated_events(event_items: list[dict]) -> list[dict]:
    seen: set[tuple[object, ...]] = set()
    unique: list[dict] = []
    for event_item in event_items:
        key = _event_dedupe_key(event_item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(event_item)
    return unique


def _format_event_text(event_item: dict) -> str | None:
    raw_text = event_item.get("text")
    if not raw_text:
        return None
    text = str(raw_text)
    if not bool(event_item.get("include_remaining", True)):
        return text
    ticks_left = max(0, int(event_item.get("ticks_left", 0) or 0))
    return f"{text} ({ticks_left} тиков осталось)"


def build_generated_message(generated: dict[str, Any] | None) -> str | None:
    if not generated:
        return None
    lines: list[str] = []
    event_items = generated.get("events") or []
    if not event_items and generated.get("event"):
        event_items = [generated["event"]]
    event_items = _dedupe_generated_events(list(event_items))
    news = generated.get("news")
    insider = generated.get("insider")

    if event_items:
        lines.append("Ивент:")
        for event in event_items:
            text = _format_event_text(event)
            if text:
                lines.append(text)
            elif event.get("asset_name") is not None and event.get("delta") is not None:
                lines.append(
                    f"{event['asset_name']} {float(event['delta']):+.2f} "
                    f"(осталось тиков: {int(event.get('ticks_left', 0))})"
                )
            elif event.get("asset_name") is not None:
                lines.append(str(event["asset_name"]))
    if news:
        if lines:
            lines.append("")
        lines.extend(
            [
                "Новости:",
                str(news),
            ]
        )
    if insider:
        if lines:
            lines.append("")
        insider_text = insider.get("text")
        if insider_text:
            lines.extend(
                [
                    "Инсайд:",
                    str(insider_text),
                ]
            )
        else:
            lines.extend(
                [
                    "Инсайд:",
                    f"{insider['asset_name']} прогноз {float(insider['forecast_percent']):+.1f}%",
                ]
            )
    if not lines:
        return None
    return "\n".join(lines)


def _resolve_generated_image_path(generated: dict[str, Any] | None) -> str | None:
    if not generated:
        return None
    image_id = None
    event_items = generated.get("events") or []
    if not event_items and generated.get("event"):
        event_items = [generated["event"]]
    event_items = _dedupe_generated_events(list(event_items))
    for item in event_items:
        current = (item or {}).get("image_id")
        if current:
            image_id = str(current)
            break
    if not image_id:
        news_image_id = generated.get("news_image_id")
        if news_image_id:
            image_id = str(news_image_id)
    if not image_id:
        insider_item = generated.get("insider") or {}
        if insider_item.get("image_id"):
            image_id = str(insider_item.get("image_id"))
    if not image_id:
        return None

    for extension in _SUPPORTED_IMAGE_EXTENSIONS:
        candidate = PICTURES_DIR / f"{image_id}{extension}"
        if candidate.exists():
            return str(candidate)

    legacy_candidate = PICTURES_DIR / image_id
    if legacy_candidate.exists():
        return str(legacy_candidate)
    return None


def _format_seconds_left(ends_at: str | None) -> str:
    if not ends_at:
        return "--:--"
    seconds_left = max(
        0, int((datetime.fromisoformat(ends_at) - datetime.now(timezone.utc)).total_seconds())
    )
    minutes, seconds = divmod(seconds_left, 60)
    return f"{minutes:02d}:{seconds:02d}"


def _asset_change_percent(asset_state: dict) -> float:
    history = asset_state.get("history") or []
    if len(history) < 2:
        return 0.0
    previous = float(history[-2])
    current = float(history[-1])
    if previous == 0:
        return 0.0
    return ((current - previous) / previous) * 100.0


def _build_open_private_buttons(app, platform: str) -> list[InlineKeyboardButton]:
    buttons: list[InlineKeyboardButton] = []
    normalized = str(platform or "TG").upper()
    if normalized == "VK":
        group_id = int(getattr(app.config, "VK_GROUP_ID", 0) or 0)
        if group_id > 0:
            buttons.append(
                InlineKeyboardButton(
                    text="Открыть личку VK",
                    url=f"https://vk.com/im?sel=-{group_id}",
                )
            )
    else:
        username = (app.config.TG_BOT_USERNAME or "").strip().lstrip("@")
        if username:
            buttons.append(
                InlineKeyboardButton(
                    text="Открыть личку TG",
                    url=f"https://t.me/{username}",
                )
            )
    if not buttons:
        buttons.append(
            InlineKeyboardButton(
                text="Откройте личный чат с ботом", callback_data="noop"
            )
        )
    return buttons


def _build_group_status(player, state: RuntimeState) -> str:
    if state.get("status") == "finished":
        return "завершил"
    if not player.is_active:
        return "вышел"
    last_action_tick = (state.get("last_action_tick") or {}).get(str(player.id))
    if last_action_tick == int(state.get("tick", 0)) - 1:
        return "активен"
    return "пассивен"


def _truncate_caption(text: str) -> str:
    if len(text) <= MAX_CAPTION_LENGTH:
        return text
    return text[: MAX_CAPTION_LENGTH - 1].rstrip() + "..."


def _is_stale_pending(timestamp_raw: str | None) -> bool:
    if not timestamp_raw:
        return True
    try:
        timestamp = datetime.fromisoformat(timestamp_raw)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - timestamp >= timedelta(seconds=PENDING_STUCK_SECONDS)


def _build_player_line(row: dict, player, user, state: RuntimeState) -> str:
    status = _build_group_status(player, state) if player is not None else "пассивен"
    if user is None or not user.dm_chat_id:
        terminal_label = "не подключен"
    else:
        terminal_label = user.platform
    return f"{row['display_name']} ({float(row['capital']):.2f}$) - {terminal_label} - {status}"


def _asset_bought_total(
    asset_runtime: dict, game_assets_map: dict[int, object]
) -> tuple[int, int]:
    asset_row = game_assets_map.get(int(asset_runtime["asset_id"]))
    if asset_row is None:
        return 0, 0
    total = int(getattr(asset_row, "shares_total", 0) or 0)
    available = int(getattr(asset_row, "shares_available", 0) or 0)
    bought = max(0, total - available)
    return bought, total


def _build_asset_line(asset_runtime: dict, game_assets_map: dict[int, object]) -> str:
    bought, total = _asset_bought_total(asset_runtime, game_assets_map)
    return (
        f"{asset_runtime['name']} - {float(asset_runtime['current_price']):.2f} "
        f"({_asset_change_percent(asset_runtime):+.1f}%) ({bought}/{total})"
    )


def _build_group_keyboard(
    app,
    platform: str,
    *,
    view: str,
    players_count: int,
    assets_count: int,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if view == GROUP_VIEW_MAIN:
        top_row: list[InlineKeyboardButton] = []
        if players_count > MAX_GROUP_INLINE_PLAYERS:
            top_row.append(
                InlineKeyboardButton(
                    text="Лидерборд",
                    callback_data="group:view_leaderboard",
                )
            )
        if assets_count > MAX_GROUP_INLINE_ASSETS:
            top_row.append(
                InlineKeyboardButton(
                    text="Маркет",
                    callback_data="group:view_market",
                )
            )
        if top_row:
            rows.append(top_row)
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Назад к рынку", callback_data="group:view_main"
                )
            ]
        )

    rows.append(_build_open_private_buttons(app, platform))
    rows.append([InlineKeyboardButton(text="Закончить игру", callback_data="end_game")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _build_group_caption_and_keyboard(
    app,
    game_id: int,
    state: RuntimeState,
) -> tuple[str, InlineKeyboardMarkup, str]:
    view = _normalize_view(state.get(GROUP_VIEW_KEY))
    game = await app.market.game.get_by_id(game_id)
    tick_seconds = int((game.settings or {}).get("tick_seconds", 10)) if game else 10
    chart_content_b64 = generate_market_overview_chart(state, tick_seconds)
    chat_title = state.get("chat_title") or "Неизвестный чат"
    assets = sorted(state.get("assets", {}).values(), key=lambda asset: asset["name"])
    players = await app.users.player.list_by_game(game_id)
    players_map = {player.id: player for player in players}
    leaderboard = await build_leaderboard(app, game_id)

    game_assets = await app.market.game_asset.list_by_game(game_id)
    game_assets_map = {int(row.asset_id): row for row in game_assets}

    lines = [
        f"{chat_title} ({state['chat_id']})",
        f"Тик {state['tick']} | Осталось времени: {_format_seconds_left(state.get('ends_at'))}",
    ]

    if view in {GROUP_VIEW_MAIN, GROUP_VIEW_LEADERBOARD}:
        show_inline_players = (
            view == GROUP_VIEW_MAIN and len(players) <= MAX_GROUP_INLINE_PLAYERS
        )
        show_all_players = view == GROUP_VIEW_LEADERBOARD
        if show_inline_players or show_all_players:
            lines.append("")
            lines.append("Игроки:")
            for row in leaderboard:
                player = players_map.get(row["player_id"])
                user = (
                    await app.users.user.get_by_id(player.user_id)
                    if player is not None
                    else None
                )
                lines.append(_build_player_line(row, player, user, state))

    if view in {GROUP_VIEW_MAIN, GROUP_VIEW_MARKET}:
        show_inline_assets = (
            view == GROUP_VIEW_MAIN and len(assets) <= MAX_GROUP_INLINE_ASSETS
        )
        show_all_assets = view == GROUP_VIEW_MARKET
        if show_inline_assets or show_all_assets:
            lines.append("")
            lines.append("Компании:")
            lines.extend(_build_asset_line(asset, game_assets_map) for asset in assets)

    keyboard = _build_group_keyboard(
        app,
        str(state.get("platform") or "TG"),
        view=view,
        players_count=len(players),
        assets_count=len(assets),
    )
    caption = _truncate_caption("\n".join(lines))
    return caption, keyboard, chart_content_b64


async def refresh_market_message(
    app,
    game_id: int,
    state: RuntimeState,
    generated: dict[str, Any] | None = None,
) -> RuntimeState:
    async with _market_refresh_lock(game_id):
        state[GROUP_VIEW_KEY] = _normalize_view(state.get(GROUP_VIEW_KEY))
        if state.get("market_message_pending"):
            if not _is_stale_pending(state.get("market_message_pending_since")):
                return state
            state["market_message_pending"] = False
            state["market_message_pending_since"] = None
            await save_runtime_state(app, state)
        target_platform = str(state.get("platform") or "TG").upper()

        caption, keyboard, chart_content_b64 = await _build_group_caption_and_keyboard(
            app, game_id, state
        )
        generated_message = build_generated_message(generated)
        generated_image_path = _resolve_generated_image_path(generated)
        current_message_id = state.get("market_message_id")

        if generated_message:
            payload_kwargs: dict[str, Any] = {
                "chat_id": state["chat_id"],
                "target_platform": target_platform,
                "text": generated_message,
            }
            if generated_image_path:
                payload_kwargs["photo_path"] = generated_image_path
            await app.sender.send_message(
                MessagePayload(**payload_kwargs)
            )
            if current_message_id:
                await app.sender.delete_message(
                    state["chat_id"],
                    current_message_id,
                    target_platform=target_platform,
                )
                state["market_message_id"] = None
                current_message_id = None
                await save_runtime_state(app, state)

        if current_message_id and not generated_message:
            await app.sender.edit_message(
                MessagePayload(
                    chat_id=state["chat_id"],
                    target_platform=target_platform,
                    message_id=current_message_id,
                    photo_content_b64=chart_content_b64,
                    text=caption,
                    keyboard=keyboard,
                    runtime_update={
                        "game_id": game_id,
                        "message_field": "market_message_id",
                    },
                )
            )
            return state

        state["market_message_pending"] = True
        state["market_message_pending_since"] = datetime.now(timezone.utc).isoformat()
        await save_runtime_state(app, state)
        await app.sender.send_message(
            MessagePayload(
                chat_id=state["chat_id"],
                target_platform=target_platform,
                photo_content_b64=chart_content_b64,
                text=caption,
                keyboard=keyboard,
                runtime_update={
                    "game_id": game_id,
                    "message_field": "market_message_id",
                    "pending_field": "market_message_pending",
                },
            )
        )
        return state
