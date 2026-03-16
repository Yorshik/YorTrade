import random

from app.data.models import PhraseType
from app.utils.runtime import RuntimeState


def _select_phrase_type(change_percent: float) -> PhraseType:
    if change_percent > 0.5:
        return PhraseType.GROWTH
    if change_percent < -0.5:
        return PhraseType.FALL
    return PhraseType.STABLE


async def _pick_asset_phrase(app, asset_id: int, phrase_type: PhraseType) -> str:
    phrases = await app.data.phrase.list_for_asset(asset_id, phrase_type)
    if not phrases:
        return "Компания получила обновление."
    return random.choice(phrases).phrase


async def generate_news(
    app, game_id: int, state: RuntimeState
) -> tuple[RuntimeState, str | None]:
    last_news = state.setdefault("last_news", [])
    game = await app.market.game.get_by_id(game_id)
    settings = (game.settings or {}) if game else {}
    news_chance = float(settings.get("news_chance", 0.5))
    assets = list(state.get("assets", {}).values())
    if not assets or random.random() > news_chance:
        return state, None

    asset_state = random.choice(assets)
    volatility = float(asset_state["volatility"])
    change_percent = round(random.uniform(-3 * volatility, 3 * volatility), 1)
    phrase_type = _select_phrase_type(change_percent)
    phrase = await _pick_asset_phrase(app, int(asset_state["asset_id"]), phrase_type)
    asset_state.setdefault("pending_news", []).append(
        {"change_percent": change_percent, "source": "company", "tick": state["tick"]}
    )
    news_item = (
        f"Тик {state['tick']}: {phrase} {change_percent:+.1f}% "
        f"стоимости {asset_state['name']}."
    )

    last_news.append(news_item)
    del last_news[:-5]
    return state, news_item
