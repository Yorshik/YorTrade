from contextvars import ContextVar, Token
from typing import Any

_UPDATE_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "update_context", default=None
)


def set_update_context(
    *,
    update_id: int | None,
    user_id: int | None,
    chat_id: int | None,
    update_type: str | None,
    platform: str | None,
    actor_key: str | None,
) -> Token:
    return _UPDATE_CONTEXT.set(
        {
            "update_id": update_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "update_type": update_type,
            "platform": platform,
            "actor_key": actor_key,
        }
    )


def reset_update_context(token: Token) -> None:
    _UPDATE_CONTEXT.reset(token)


def get_update_context() -> dict[str, Any] | None:
    return _UPDATE_CONTEXT.get()
