import json
from datetime import UTC, datetime
from typing import Any

RUNTIME_KEY_TEMPLATE = "game_runtime:{game_id}"

RuntimeState = dict[str, Any]


def get_runtime_key(game_id: int) -> str:
    return RUNTIME_KEY_TEMPLATE.format(game_id=game_id)


def build_initial_runtime_state(
    game_id: int, chat_id: int, platform: str = "TG"
) -> RuntimeState:
    return {
        "game_id": game_id,
        "chat_id": chat_id,
        "platform": str(platform).upper(),
        "chat_title": None,
        "tick": 0,
        "status": "running",
        "market_view": "main",
        "market_message_id": None,
        "market_message_pending": False,
        "market_message_pending_since": None,
        "last_news": [],
        "last_event": None,
        "last_insider_info": None,
        "global_event": None,
        "assets": {},
        "updated_at": None,
    }


async def init_runtime_state(
    app, game_id: int, chat_id: int, platform: str = "TG"
) -> RuntimeState:
    state = await load_runtime_state(app, game_id)
    if state is not None:
        changed = False
        normalized_platform = str(platform).upper()
        if not state.get("platform"):
            state["platform"] = normalized_platform
            changed = True
        if "market_view" not in state:
            state["market_view"] = "main"
            changed = True
        if "market_message_pending_since" not in state:
            state["market_message_pending_since"] = None
            changed = True
        if "global_event" not in state:
            state["global_event"] = None
            changed = True
        if changed:
            await save_runtime_state(app, state)
        return state

    state = build_initial_runtime_state(
        game_id=game_id, chat_id=chat_id, platform=platform
    )
    await save_runtime_state(app, state)
    return state


async def load_runtime_state(app, game_id: int) -> RuntimeState | None:
    raw_state = await app.redis.get(get_runtime_key(game_id))
    if not raw_state:
        return None
    return json.loads(raw_state)


async def save_runtime_state(app, state: RuntimeState) -> RuntimeState:
    state["updated_at"] = datetime.now(UTC).isoformat()
    await app.redis.set(get_runtime_key(state["game_id"]), json.dumps(state))
    return state
