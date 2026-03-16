import json
from typing import Optional, Tuple, Dict, Any, TYPE_CHECKING

from app.store.fsm.states import FSM
from app.utils.log_context import get_update_context
from app.utils.platform import build_actor_key, parse_actor_key

if TYPE_CHECKING:
    from app.web.application import App


class FSMAccessor:
    def __init__(self, app: App):
        self.app = app
        self.FSM = FSM

    @staticmethod
    def _redis_key(actor_key: str) -> str:
        return f"fsm:{actor_key}"

    def _resolve_actor_key(self, user_id: int, platform: str | None = None) -> str:
        context = get_update_context() or {}
        if platform is None and context.get("user_id") == user_id and context.get("actor_key"):
            return str(context["actor_key"])
        actor_key = build_actor_key(platform or context.get("platform"), user_id)
        return actor_key or f"TG:{user_id}"

    async def get_state(self, user_id: int, platform: str | None = None) -> Optional[Tuple[str, Dict[str, Any]]]:
        actor_key = self._resolve_actor_key(user_id, platform)
        raw = await self.app.redis.get(self._redis_key(actor_key))
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if parsed:
                return parsed.get("state"), parsed.get("data", {})

        parsed_actor = parse_actor_key(actor_key)
        if parsed_actor:
            raw_data = await self.app.users.user.get_fsm_state(parsed_actor[0], parsed_actor[1])
        else:
            raw_data = None
        if raw_data:
            data = dict(raw_data)
            return data.get("state"), data.get("data", {})
        return None

    async def set_state(self, user_id: int, state: str, data: Optional[Dict[str, Any]] = None, platform: str | None = None):
        if data is None:
            data = {}
        payload = {"state": state, "data": data}
        actor_key = self._resolve_actor_key(user_id, platform)
        await self.app.redis.set(self._redis_key(actor_key), json.dumps(payload))

        parsed_actor = parse_actor_key(actor_key)
        if parsed_actor:
            await self.app.users.user.set_fsm_state(parsed_actor[0], parsed_actor[1], payload)

    async def clear_state(self, user_id: int, platform: str | None = None):
        actor_key = self._resolve_actor_key(user_id, platform)
        await self.app.redis.delete(self._redis_key(actor_key))
        parsed_actor = parse_actor_key(actor_key)
        if parsed_actor:
            await self.app.users.user.set_fsm_state(parsed_actor[0], parsed_actor[1], None)
