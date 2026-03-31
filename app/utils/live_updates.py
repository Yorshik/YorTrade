import logging
from datetime import datetime, timedelta, timezone
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


def _event_fallback_key(item: dict, *, active_until: int | None = None) -> tuple[object, ...]:
    return (
        "fallback",
        str(item.get("type") or ""),
        str(item.get("template_id") or ""),
        str(item.get("text") or ""),
        int(item.get("active_until", -1) if active_until is None else active_until),
    )


def _events_match(left: dict, right: dict, *, right_active_until: int | None = None) -> bool:
    left_event_id = str(left.get("event_id") or "").strip()
    right_event_id = str(right.get("event_id") or "").strip()
    if left_event_id and right_event_id and left_event_id == right_event_id:
        return True
    return _event_fallback_key(left) == _event_fallback_key(
        right, active_until=right_active_until
    )


def _remove_matching_events(feed_events: list[dict], event_item: dict) -> bool:
    before = len(feed_events)
    event_id = str(event_item.get("event_id") or "").strip()
    if event_id:
        feed_events[:] = [
            item
            for item in feed_events
            if str(item.get("event_id") or "").strip() != event_id
        ]
        return len(feed_events) != before

    event_type = str(event_item.get("type") or "")
    template_id = str(event_item.get("template_id") or "")
    text = str(event_item.get("text") or "")
    feed_events[:] = [
        item
        for item in feed_events
        if not (
            not str(item.get("event_id") or "").strip()
            and str(item.get("type") or "") == event_type
            and str(item.get("template_id") or "") == template_id
            and str(item.get("text") or "") == text
        )
    ]
    return len(feed_events) != before


def _upsert_event(feed_events: list[dict], event_entry: dict, *, active_until: int) -> bool:
    for index, current in enumerate(feed_events):
        if not _events_match(current, event_entry, right_active_until=active_until):
            continue
        if current != event_entry:
            feed_events[index] = event_entry
            return True
        return False
    feed_events.append(event_entry)
    return True


def _dedupe_events(feed_events: list[dict]) -> bool:
    deduped: list[dict] = []
    changed = False
    for item in feed_events:
        existing_index = None
        for index, current in enumerate(deduped):
            if _events_match(current, item):
                existing_index = index
                break
        if existing_index is None:
            deduped.append(item)
            continue
        changed = True
        existing = deduped[existing_index]
        if int(item.get("source_tick", -1)) >= int(existing.get("source_tick", -1)):
            deduped[existing_index] = item
    if changed:
        feed_events[:] = deduped
    return changed


def _drop_finished_events(feed_events: list[dict], tick: int) -> bool:
    before = len(feed_events)
    feed_events[:] = [
        item
        for item in feed_events
        if int(item.get("active_until", -1)) > tick or bool(item.get("ended_text"))
    ]
    return len(feed_events) != before


def _update_dm_feed(state: dict, generated: dict[str, Any] | None) -> bool:
    tick = int(state.get("tick", 0))
    feed = _ensure_dm_feed(state)
    changed = False

    changed |= _prune_by_tick(feed["news"], tick)
    changed |= _prune_by_tick(feed["events"], tick)
    changed |= _prune_by_tick(feed["insiders"], tick)
    changed |= _drop_finished_events(feed["events"], tick)

    if not generated:
        changed |= _dedupe_events(feed["events"])
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

    event_items = generated.get("events") or []
    if not event_items and generated.get("event"):
        event_items = [generated["event"]]
    for event_item in event_items:
        event_ticks = max(0, int(event_item.get("ticks_left", 0)))
        if event_ticks <= 0:
            changed |= _remove_matching_events(feed["events"], event_item)
            continue
        active_until = tick + event_ticks
        delta_raw = event_item.get("delta")
        event_entry = {
            "type": event_item.get("type"),
            "event_id": event_item.get("event_id"),
            "template_id": event_item.get("template_id"),
            "asset_name": event_item.get("asset_name"),
            "source_tick": tick,
            "event_ticks": event_ticks,
            "active_until": active_until,
            "display_until": active_until + 1,
            "text": event_item.get("text"),
            "ended_text": event_item.get("ended_text"),
            "include_remaining": bool(event_item.get("include_remaining", True)),
        }
        if delta_raw is not None:
            event_entry["delta"] = float(delta_raw)
        changed |= _upsert_event(feed["events"], event_entry, active_until=active_until)

    insider_item = generated.get("insider")
    if insider_item:
        feed["insiders"].append(
            {
                "asset_name": insider_item.get("asset_name"),
                "text": insider_item.get("text"),
                "forecast_percent": float(insider_item.get("forecast_percent", 0.0)),
                "true_change_percent": float(
                    insider_item.get("true_change_percent", 0.0)
                ),
                "source_tick": tick,
                "display_until": tick + 1,
            }
        )
        changed = True

    changed |= _dedupe_events(feed["events"])

    return changed


def _is_stale_pending(timestamp_raw: str | None) -> bool:
    if not timestamp_raw:
        return True
    try:
        timestamp = datetime.fromisoformat(timestamp_raw)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - timestamp >= timedelta(seconds=PENDING_STUCK_SECONDS)


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
