from __future__ import annotations

from collections.abc import Iterable

from app.clients.common.mailbox import MessagePayload

LEVELS = ("I", "II", "III", "Absolute")

ACHIEVEMENT_DEFINITIONS = {
    "capital_growth_peak_ratio": {
        "title": "Рост капитала",
        "thresholds": (1.25, 1.5, 1.75, 2.5),
    },
    "deals_total": {
        "title": "Количество сделок",
        "thresholds": (10, 50, 100, 300),
    },
    "trades_per_tick_peak": {
        "title": "Сделки за 1 тик",
        "thresholds": (3, 7, 13, 20),
    },
    "deal_profit_peak": {
        "title": "Прибыль за 1 сделку",
        "thresholds": (100, 250, 500, 1500),
    },
    "dividends_total": {
        "title": "Получено дивидендов",
        "thresholds": (100, 250, 500, 1500),
    },
    "impact_peak_percent": {
        "title": "Импакт",
        "thresholds": (1, 3, 7, 10),
    },
    "portfolio_unique_peak": {
        "title": "Активы в портфеле (уникальные)",
        "thresholds": (10, 50, 100, 400),
    },
    "portfolio_total_amount_peak": {
        "title": "Активы в портфеле (суммарно)",
        "thresholds": (10, 100, 500, 1000),
    },
    "wins_total": {
        "title": "Победы",
        "thresholds": (1, 5, 10, 25),
    },
    "company_share_peak_percent": {
        "title": "Доля компании",
        "thresholds": (10, 25, 60, 100),
    },
}

ACHIEVEMENT_ORDER = (
    "capital_growth_peak_ratio",
    "deals_total",
    "trades_per_tick_peak",
    "deal_profit_peak",
    "dividends_total",
    "impact_peak_percent",
    "portfolio_unique_peak",
    "portfolio_total_amount_peak",
    "wins_total",
    "company_share_peak_percent",
)

DEFAULT_STATS = {
    "capital_growth_peak_ratio": 1.0,
    "deals_total": 0,
    "trades_per_tick_peak": 0,
    "deal_profit_peak": 0.0,
    "dividends_total": 0.0,
    "impact_peak_percent": 0.0,
    "portfolio_unique_peak": 0,
    "portfolio_total_amount_peak": 0,
    "wins_total": 0,
    "company_share_peak_percent": 0.0,
}

INT_FIELDS = {
    "deals_total",
    "trades_per_tick_peak",
    "portfolio_unique_peak",
    "portfolio_total_amount_peak",
    "wins_total",
}

MONEY_FIELDS = {"deal_profit_peak", "dividends_total"}
PERCENT_FIELDS = {"impact_peak_percent", "company_share_peak_percent"}


def achievement_tracking_enabled(app) -> bool:
    users = getattr(app, "users", None)
    return bool(
        users is not None
        and getattr(users, "achievement", None) is not None
        and getattr(users, "player", None) is not None
    )


def game_start_balance(game) -> float:
    start_balance = float(
        (game.settings or {}).get("default_balance", 1000.0) or 1000.0
    )
    return max(1.0, start_balance)


def _normalize_value(field: str, value: float | int) -> float | int:
    if field in INT_FIELDS:
        return int(value)
    if (
        field in MONEY_FIELDS
        or field in PERCENT_FIELDS
        or field == "capital_growth_peak_ratio"
    ):
        return round(float(value), 4)
    return float(value)


def stats_to_dict(stats_row) -> dict[str, float | int]:
    return {
        field: _normalize_value(field, getattr(stats_row, field, default_value))
        for field, default_value in DEFAULT_STATS.items()
    }


def _tier_index(field: str, value: float | int) -> int:
    thresholds = ACHIEVEMENT_DEFINITIONS[field]["thresholds"]
    index = 0
    for threshold_index, threshold in enumerate(thresholds, start=1):
        if float(value) >= float(threshold):
            index = threshold_index
        else:
            break
    return index


def _tier_label(field: str, value: float | int) -> str:
    index = _tier_index(field, value)
    if index <= 0:
        return "-"
    return LEVELS[index - 1]


def _format_value(field: str, value: float | int) -> str:
    if field == "capital_growth_peak_ratio":
        return f"{float(value):.2f}x"
    if field in MONEY_FIELDS:
        return f"{float(value):.2f}$"
    if field in PERCENT_FIELDS:
        return f"{float(value):.2f}%"
    return str(int(value))


def _new_levels_for_range(
    field: str, old_value: float | int, new_value: float | int
) -> list[tuple[str, float]]:
    if float(new_value) <= float(old_value):
        return []
    levels: list[tuple[str, float]] = []
    for level_name, threshold in zip(
        LEVELS, ACHIEVEMENT_DEFINITIONS[field]["thresholds"], strict=True
    ):
        if float(old_value) < float(threshold) <= float(new_value):
            levels.append((level_name, float(threshold)))
    return levels


def _collect_unlocks(
    changed_fields: Iterable[str],
    before_stats: dict[str, float | int],
    after_stats: dict[str, float | int],
) -> list[dict[str, str]]:
    unlocks: list[dict[str, str]] = []
    for field in changed_fields:
        old_value = before_stats[field]
        new_value = after_stats[field]
        for level_name, threshold in _new_levels_for_range(field, old_value, new_value):
            unlocks.append(
                {
                    "title": ACHIEVEMENT_DEFINITIONS[field]["title"],
                    "level": level_name,
                    "threshold": _format_value(field, threshold),
                }
            )
    return unlocks


def build_unlock_message(unlocks: list[dict[str, str]]) -> str:
    if not unlocks:
        return ""
    lines = ["Новое достижение!"]
    lines.extend(
        f"- {unlocked['title']}: {unlocked['level']} ({unlocked['threshold']})"
        for unlocked in unlocks
    )
    return "\n".join(lines)


def build_achievements_report(stats_row) -> str:
    stats = stats_to_dict(stats_row)
    lines = ["Твои достижения (общий прогресс):"]
    for index, field in enumerate(ACHIEVEMENT_ORDER, start=1):
        title = ACHIEVEMENT_DEFINITIONS[field]["title"]
        current_value = stats[field]
        max_value = ACHIEVEMENT_DEFINITIONS[field]["thresholds"][-1]
        lines.append(
            f"{index}. {title}: {_tier_label(field, current_value)} "
            f"({_format_value(field, current_value)} / {_format_value(field, max_value)})"
        )
    return "\n".join(lines)


async def build_player_capital_snapshot(
    app,
    *,
    player_id: int,
    balance: float,
    assets_state: dict[str, dict],
    asset_price_overrides: dict[int, float] | None = None,
) -> dict[str, float | int]:
    overrides = asset_price_overrides or {}
    portfolio_rows = await app.market.portfolio.list_by_player(player_id)
    assets_capital = 0.0
    unique_assets = 0
    total_amount = 0

    for row in portfolio_rows:
        amount = int(getattr(row, "amount", 0) or 0)
        if amount <= 0:
            continue
        unique_assets += 1
        total_amount += amount
        override_price = overrides.get(int(row.asset_id))
        if override_price is not None:
            price = float(override_price)
        else:
            asset_state = assets_state.get(str(row.asset_id))
            if asset_state is None:
                continue
            price = float(asset_state["current_price"])
        assets_capital += amount * price

    total_capital = round(float(balance) + assets_capital, 2)
    return {
        "assets_capital": round(assets_capital, 2),
        "total_capital": total_capital,
        "unique_assets": unique_assets,
        "total_amount": total_amount,
    }


async def _notify_unlocked_levels(
    app, user_id: int, unlocks: list[dict[str, str]]
) -> None:
    if not unlocks:
        return
    users_accessor = getattr(getattr(app, "users", None), "user", None)
    sender = getattr(app, "sender", None)
    if users_accessor is None or sender is None or not hasattr(sender, "send_message"):
        return
    user = await users_accessor.get_by_id(user_id)
    if user is None or not user.dm_chat_id:
        return
    text = build_unlock_message(unlocks)
    if not text:
        return
    await sender.send_message(
        MessagePayload(
            chat_id=user.dm_chat_id,
            target_platform=user.platform,
            text=text,
        )
    )


async def apply_achievement_progress(
    app,
    *,
    user_id: int,
    add: dict[str, float | int] | None = None,
    peak: dict[str, float | int] | None = None,
) -> list[dict[str, str]]:
    add = add or {}
    peak = peak or {}
    if not add and not peak:
        return []
    if not achievement_tracking_enabled(app):
        return []

    stats_row = await app.users.achievement.get_or_create(user_id)
    before_stats = stats_to_dict(stats_row)
    changed_fields: set[str] = set()

    for field, delta in add.items():
        if field not in DEFAULT_STATS:
            continue
        current_value = _normalize_value(
            field, getattr(stats_row, field, DEFAULT_STATS[field])
        )
        target_value = _normalize_value(field, float(current_value) + float(delta))
        if target_value != current_value:
            setattr(stats_row, field, target_value)
            changed_fields.add(field)

    for field, candidate_value in peak.items():
        if field not in DEFAULT_STATS:
            continue
        current_value = _normalize_value(
            field, getattr(stats_row, field, DEFAULT_STATS[field])
        )
        normalized_candidate = _normalize_value(field, candidate_value)
        if float(normalized_candidate) > float(current_value):
            setattr(stats_row, field, normalized_candidate)
            changed_fields.add(field)

    if not changed_fields:
        return []

    await app.users.achievement.save(stats_row)
    after_stats = stats_to_dict(stats_row)
    unlocks = _collect_unlocks(changed_fields, before_stats, after_stats)
    await _notify_unlocked_levels(app, user_id, unlocks)
    return unlocks
