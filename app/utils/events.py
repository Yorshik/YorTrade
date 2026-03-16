import random

from app.utils.runtime import RuntimeState

EVENT_DURATION_TICKS = 6
DIVIDEND_PAYOUT_RATE = 0.02
BUYBACK_MULTIPLIER = 1.5
EVENT_TYPES = (
    "trend_reversal",
    "innovation",
    "dividends",
    "buyback",
    "market_crash",
)


def _event_payload(
    *,
    tick: int,
    event_type: str,
    text: str,
    ticks_left: int,
    include_remaining: bool = True,
    ended_text: str | None = None,
    asset_state: dict | None = None,
    delta: float | None = None,
) -> dict:
    payload = {
        "tick": tick,
        "type": event_type,
        "text": text,
        "ticks_left": ticks_left,
        "include_remaining": include_remaining,
    }
    if ended_text:
        payload["ended_text"] = ended_text
    if asset_state is not None:
        payload["asset_id"] = asset_state.get("asset_id")
        payload["asset_name"] = asset_state.get("name")
    if delta is not None:
        payload["delta"] = delta
    return payload


def _build_trend_reversal_event(state: RuntimeState, asset_state: dict) -> dict:
    current_sign = int(asset_state.get("trend_sign", 1))
    new_sign = -current_sign if random.random() < 0.7 else current_sign
    volatility = float(asset_state["volatility"])
    delta = round(random.uniform(1.5 * volatility, 2.5 * volatility) * new_sign, 2)
    asset_state["active_event"] = {
        "type": "trend_reversal",
        "ticks_left": EVENT_DURATION_TICKS,
        "delta": delta,
        "source_tick": state["tick"],
    }
    return _event_payload(
        tick=state["tick"],
        event_type="trend_reversal",
        text=f"{asset_state['name']} {delta:+.2f}",
        ticks_left=EVENT_DURATION_TICKS,
        asset_state=asset_state,
        delta=delta,
    )


def _build_innovation_event(state: RuntimeState, asset_state: dict) -> dict:
    asset_state["active_event"] = {
        "type": "innovation",
        "ticks_left": EVENT_DURATION_TICKS,
        "source_tick": state["tick"],
        "investors": [],
    }
    return _event_payload(
        tick=state["tick"],
        event_type="innovation",
        text=f"{asset_state['name']}: готовит инновацию, ждём итог.",
        ticks_left=EVENT_DURATION_TICKS,
        asset_state=asset_state,
    )


def _build_dividends_event(state: RuntimeState, asset_state: dict) -> dict:
    asset_state["active_event"] = {
        "type": "dividends",
        "ticks_left": 1,
        "source_tick": state["tick"],
        "payout_rate": DIVIDEND_PAYOUT_RATE,
    }
    return _event_payload(
        tick=state["tick"],
        event_type="dividends",
        text=f"{asset_state['name']}: объявлены дивиденды, выплата на следующем тике.",
        ticks_left=1,
        include_remaining=False,
        asset_state=asset_state,
    )


def _build_buyback_event(state: RuntimeState, asset_state: dict) -> dict:
    asset_state["active_event"] = {
        "type": "buyback",
        "ticks_left": EVENT_DURATION_TICKS,
        "source_tick": state["tick"],
        "sell_multiplier": BUYBACK_MULTIPLIER,
    }
    return _event_payload(
        tick=state["tick"],
        event_type="buyback",
        text=f"{asset_state['name']}: выкуп акций x{BUYBACK_MULTIPLIER:.1f}, покупка временно закрыта.",
        ticks_left=EVENT_DURATION_TICKS,
        ended_text=f"{asset_state['name']}: выкуп завершён.",
        asset_state=asset_state,
    )


def _build_market_crash_event(state: RuntimeState) -> dict:
    state["global_event"] = {
        "type": "market_crash",
        "ticks_left": EVENT_DURATION_TICKS,
        "source_tick": state["tick"],
    }
    return _event_payload(
        tick=state["tick"],
        event_type="market_crash",
        text="Обвал рынка: все компании падают в течение 6 тиков.",
        ticks_left=EVENT_DURATION_TICKS,
        ended_text="Обвал рынка завершён.",
    )


async def generate_events(
    app, game_id: int, state: RuntimeState
) -> tuple[RuntimeState, dict | None]:
    game = await app.market.game.get_by_id(game_id)
    settings = (game.settings or {}) if game else {}
    event_chance = float(settings.get("event_chance", 0.5))
    state.setdefault("global_event", None)
    assets = [
        asset
        for asset in state.get("assets", {}).values()
        if not asset.get("active_event")
    ]

    if random.random() > event_chance:
        state["last_event"] = None
        return state, None

    selected = random.choice(EVENT_TYPES)
    if selected == "market_crash":
        event = _build_market_crash_event(state)
    else:
        if not assets:
            state["last_event"] = None
            return state, None
        asset_state = random.choice(assets)
        if selected == "trend_reversal":
            event = _build_trend_reversal_event(state, asset_state)
        elif selected == "innovation":
            event = _build_innovation_event(state, asset_state)
        elif selected == "dividends":
            event = _build_dividends_event(state, asset_state)
        else:
            event = _build_buyback_event(state, asset_state)

    state["last_event"] = event
    return state, event
