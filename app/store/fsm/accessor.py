from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.store.fsm.states import FSM
from app.utils.log_context import get_update_context
from app.utils.platform import build_actor_key, parse_actor_key

if TYPE_CHECKING:
    from app.web.application import App


class FSMAccessor:
    def __init__(self, app: App):
        self.app = app
        self.FSM = FSM

    def _resolve_actor_key(self, user_id: int, platform: str | None = None) -> str:
        context = get_update_context() or {}
        if (
            platform is None
            and context.get("user_id") == user_id
            and context.get("actor_key")
        ):
            return str(context["actor_key"])
        actor_key = build_actor_key(platform or context.get("platform"), user_id)
        return actor_key or f"TG:{user_id}"

    async def get_state(
        self, user_id: int, platform: str | None = None
    ) -> tuple[str, dict[str, Any]] | None:
        actor_key = self._resolve_actor_key(user_id, platform)
        parsed_actor = parse_actor_key(actor_key)
        if parsed_actor:
            raw_data = await self.app.users.user.get_fsm_state(
                parsed_actor[0], parsed_actor[1]
            )
        else:
            raw_data = None
        if raw_data:
            data = dict(raw_data)
            return data.get("state"), data.get("data", {})
        return None

    async def set_state(
        self,
        user_id: int,
        state: str,
        data: dict[str, Any] | None = None,
        platform: str | None = None,
    ):
        if data is None:
            data = {}
        payload = {"state": state, "data": data}
        actor_key = self._resolve_actor_key(user_id, platform)
        parsed_actor = parse_actor_key(actor_key)
        if parsed_actor:
            await self.app.users.user.set_fsm_state(
                parsed_actor[0], parsed_actor[1], payload
            )

    async def clear_state(self, user_id: int, platform: str | None = None):
        actor_key = self._resolve_actor_key(user_id, platform)
        parsed_actor = parse_actor_key(actor_key)
        if parsed_actor:
            await self.app.users.user.set_fsm_state(
                parsed_actor[0], parsed_actor[1], None
            )
