import math
from asyncio import Lock
from datetime import datetime, timezone

from app.clients.common.mailbox import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MessagePayload,
)
from app.utils.charts import generate_asset_price_chart, generate_private_main_chart
from app.utils.log_context import get_update_context
from app.utils.platform import normalize_platform
from app.utils.trading import (
    TradeError,
    build_portfolio_snapshot,
    get_active_player_context,
)

_PRIVATE_SCREEN_LOCKS: dict[str, Lock] = {}
_TRADES_PER_PAGE = 5
_PORTFOLIO_PER_PAGE = 8
_MAX_CAPTION_LENGTH = 1024
_PENDING_STUCK_SECONDS = 20


def _get_private_screen_lock(tg_user_id: int, platform: str) -> Lock:
    key = f"{normalize_platform(platform)}:{tg_user_id}"
    lock = _PRIVATE_SCREEN_LOCKS.get(key)
    if lock is None:
        lock = Lock()
        _PRIVATE_SCREEN_LOCKS[key] = lock
    return lock


def _chunk_buttons(
    buttons: list[InlineKeyboardButton], columns: int
) -> list[list[InlineKeyboardButton]]:
    return [
        buttons[index : index + columns] for index in range(0, len(buttons), columns)
    ]


def _shorten_label(text: str, max_length: int = 18) -> str:
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 1].rstrip()}..."


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


def _safe_caption(text: str) -> str:
    if len(text) <= _MAX_CAPTION_LENGTH:
        return text
    return text[: _MAX_CAPTION_LENGTH - 1].rstrip() + "..."


def _is_pending_stale(timestamp_raw: str | None) -> bool:
    if not timestamp_raw:
        return True
    try:
        timestamp = datetime.fromisoformat(timestamp_raw)
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - timestamp).total_seconds() >= _PENDING_STUCK_SECONDS


def _screen_platform(data: dict | None = None) -> str:
    if data and data.get("_client_platform"):
        return normalize_platform(str(data["_client_platform"]))
    context = get_update_context() or {}
    return normalize_platform(context.get("platform"))


def _is_vk_client(app, data: dict | None = None) -> bool:
    if data and data.get("_client_platform"):
        return str(data["_client_platform"]).upper() == "VK"
    context = get_update_context() or {}
    return normalize_platform(context.get("platform")) == "VK"


def _companies_per_page(app, data: dict | None = None) -> int:
    return 4 if _is_vk_client(app, data) else 6


def _main_chart_assets(
    app, assets: list[dict], page: int, data: dict | None = None
) -> list[dict]:
    page_size = _companies_per_page(app, data)
    start = page * page_size
    end = start + page_size
    return assets[start:end]


def _current_page(
    total_items: int, requested_page: int, page_size: int
) -> tuple[int, int]:
    total_pages = max(1, math.ceil(max(1, total_items) / page_size))
    page = min(max(0, requested_page), total_pages - 1)
    return page, total_pages


def _build_dm_feed_lines(state: dict) -> list[str]:
    tick = int(state.get("tick", 0))
    feed = state.get("dm_feed") or {}
    lines: list[str] = []

    lines.extend(
        f"Новости: {news_item.get('text', '')}"
        for news_item in feed.get("news", [])
        if tick <= int(news_item.get("display_until", -1))
    )

    for event_item in feed.get("events", []):
        active_until = int(event_item.get("active_until", -1))
        if tick < active_until:
            remaining = max(0, active_until - tick)
            event_text = event_item.get("text")
            if event_text:
                if int(event_item.get("event_ticks", 0)) > 0 and event_item.get(
                    "include_remaining", True
                ):
                    lines.append(f"Ивент: {event_text} (осталось тиков: {remaining})")
                else:
                    lines.append(f"Ивент: {event_text}")
            elif (
                event_item.get("asset_name") is not None
                and event_item.get("delta") is not None
            ):
                lines.append(
                    f"Ивент: {event_item.get('asset_name')} "
                    f"{float(event_item.get('delta', 0.0)):+.2f} (осталось тиков: {remaining})"
                )
            elif event_item.get("asset_name") is not None:
                lines.append(
                    f"Ивент: {event_item.get('asset_name')} (осталось тиков: {remaining})"
                )
        elif tick == active_until + 1:
            ended_text = event_item.get("ended_text")
            if ended_text:
                lines.append(f"Ивент завершён: {ended_text}")
            elif event_item.get("asset_name") is not None:
                lines.append(f"Ивент завершён: {event_item.get('asset_name')}")

    for insider_item in feed.get("insiders", []):
        source_tick = int(insider_item.get("source_tick", tick))
        if tick == source_tick:
            insider_text = insider_item.get("text")
            if insider_text:
                lines.append(f"Инсайд: {insider_text}")
            else:
                lines.append(
                    f"Инсайд: {insider_item.get('asset_name')} "
                    f"{float(insider_item.get('forecast_percent', 0.0)):+.1f}%"
                )
        elif tick == source_tick + 1:
            lines.append(f"Инсайд отыгран: {insider_item.get('asset_name')}")

    return lines


async def _portfolio_amounts_by_asset(app, player_id: int) -> dict[int, int]:
    portfolio_rows = await app.market.portfolio.list_by_player(player_id)
    return {row.asset_id: row.amount for row in portfolio_rows}


async def _tick_seconds(app, game_id: int) -> int:
    game = await app.market.game.get_by_id(game_id)
    if not game:
        return 10
    return int((game.settings or {}).get("tick_seconds", 10))


async def _build_main_screen(
    app, tg_user_id: int, data: dict
) -> tuple[str, InlineKeyboardMarkup, str, dict, str]:
    platform = _screen_platform(data)
    user, player, game, state = await get_active_player_context(
        app, tg_user_id, platform=platform
    )
    _ = user
    assets = sorted(state.get("assets", {}).values(), key=lambda item: item["name"])
    if not assets:
        empty_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Выйти", callback_data="private:leave_confirm"
                    )
                ]
            ]
        )
        return (
            "Рынок пуст.",
            empty_keyboard,
            generate_private_main_chart([], 10),
            data,
            app.fsm.FSM.PLAYING_MAIN,
        )

    page_size = _companies_per_page(app, data)
    page, total_pages = _current_page(
        len(assets), int(data.get("companies_page", 0)), page_size
    )
    page_assets = _main_chart_assets(app, assets, page, data)
    holdings = await _portfolio_amounts_by_asset(app, player.id)
    snapshot = await build_portfolio_snapshot(app, tg_user_id, platform=platform)

    lines = [
        f'Чат: "{state.get("chat_title") or "Неизвестный чат"}" ("{state["chat_id"]}")',
        f"Тик: {state['tick']} | Осталось времени: {_format_seconds_left(state.get('ends_at'))}",
        "",
        f"Страница компаний: {page + 1}/{total_pages}",
    ]

    for asset in page_assets:
        owned = int(holdings.get(int(asset["asset_id"]), 0))
        lines.append(
            f"{asset['name']} -- {float(asset['current_price']):.2f} "
            f"({_asset_change_percent(asset):+.1f}%) (в портфеле: {owned})"
        )

    feed_lines = _build_dm_feed_lines(state)
    if feed_lines:
        lines.append("")
        lines.extend(feed_lines)

    lines.extend(
        [
            "",
            f"Общий капитал: {float(snapshot['total_capital']):.2f}",
            f"Баланс: {float(snapshot['balance']):.2f}",
        ]
    )

    company_buttons = [
        InlineKeyboardButton(
            text=_shorten_label(asset["name"], 20),
            callback_data=f"private:company:{asset['asset_id']}",
        )
        for asset in page_assets
    ]

    rows = _chunk_buttons(company_buttons, 2)
    if total_pages > 1:
        rows.append(
            [
                InlineKeyboardButton(
                    text="<-", callback_data="private:companies_page:-1"
                ),
                InlineKeyboardButton(
                    text=f"{page + 1}/{total_pages}", callback_data="noop"
                ),
                InlineKeyboardButton(
                    text="->", callback_data="private:companies_page:1"
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="Портфель", callback_data="private:portfolio"),
            InlineKeyboardButton(
                text="История сделок", callback_data="private:history"
            ),
        ]
    )
    rows.append(
        [InlineKeyboardButton(text="Выйти", callback_data="private:leave_confirm")]
    )

    chart = generate_private_main_chart(page_assets, await _tick_seconds(app, game.id))
    new_data = dict(data)
    new_data["companies_page"] = page
    return (
        _safe_caption("\n".join(lines)),
        InlineKeyboardMarkup(inline_keyboard=rows),
        chart,
        new_data,
        app.fsm.FSM.PLAYING_MAIN,
    )


async def _build_company_screen(
    app, tg_user_id: int, data: dict
) -> tuple[str, InlineKeyboardMarkup, str, dict, str]:
    _, player, game, state = await get_active_player_context(
        app, tg_user_id, platform=_screen_platform(data)
    )
    asset_id = int(data.get("asset_id", 0))
    asset_state = state.get("assets", {}).get(str(asset_id))
    if asset_state is None:
        return await _build_main_screen(app, tg_user_id, data)

    game_asset = await app.market.game_asset.get(game.id, asset_id)
    portfolio = await app.market.portfolio.get_or_create(player.id, asset_id)

    text = _safe_caption(
        "\n".join(
            [
                f"Компания: {asset_state['name']}",
                f"Цена за акцию: {float(asset_state['current_price']):.2f}",
                f"Доступно акций: {game_asset.shares_available if game_asset else 0}",
                f"В портфеле: {portfolio.amount}",
            ]
        )
    )
    active_event = asset_state.get("active_event") or {}
    buyback_active = (
        str(active_event.get("type") or "") == "buyback"
        and int(active_event.get("ticks_left", 0) or 0) > 0
    )
    buy_button = InlineKeyboardButton(
        text="❌ Купить" if buyback_active else "Купить",
        callback_data="noop"
        if buyback_active
        else f"private:trade_menu:buy:{asset_id}",
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                buy_button,
                InlineKeyboardButton(
                    text="Продать", callback_data=f"private:trade_menu:sell:{asset_id}"
                ),
            ],
            [InlineKeyboardButton(text="Назад", callback_data="private:main")],
        ]
    )
    chart = generate_asset_price_chart(asset_state, await _tick_seconds(app, game.id))
    new_data = dict(data)
    new_data["asset_id"] = asset_id
    return text, keyboard, chart, new_data, app.fsm.FSM.PLAYING_ASSET


async def _build_trade_screen(
    app, tg_user_id: int, data: dict
) -> tuple[str, InlineKeyboardMarkup, str, dict, str]:
    _, player, game, state = await get_active_player_context(
        app, tg_user_id, platform=_screen_platform(data)
    )
    asset_id = int(data.get("asset_id", 0))
    side = data.get("trade_side", "buy")
    if side not in {"buy", "sell"}:
        side = "buy"

    asset_state = state.get("assets", {}).get(str(asset_id))
    if asset_state is None:
        return await _build_main_screen(app, tg_user_id, data)

    game_asset = await app.market.game_asset.get(game.id, asset_id)
    portfolio = await app.market.portfolio.get_or_create(player.id, asset_id)

    title = "Покупка" if side == "buy" else "Продажа"
    text = _safe_caption(
        "\n".join(
            [
                f"{title}: {asset_state['name']}",
                f"Цена за акцию: {float(asset_state['current_price']):.2f}",
                f"Доступно акций: {game_asset.shares_available if game_asset else 0}",
                f"В портфеле: {portfolio.amount}",
                f"Баланс: {float(player.balance):.2f}",
            ]
        )
    )

    fixed_buttons = [
        InlineKeyboardButton(
            text="1", callback_data=f"private:trade_exec:{side}:{asset_id}:fixed:1"
        ),
        InlineKeyboardButton(
            text="2", callback_data=f"private:trade_exec:{side}:{asset_id}:fixed:2"
        ),
        InlineKeyboardButton(
            text="5", callback_data=f"private:trade_exec:{side}:{asset_id}:fixed:5"
        ),
        InlineKeyboardButton(
            text="10", callback_data=f"private:trade_exec:{side}:{asset_id}:fixed:10"
        ),
        InlineKeyboardButton(
            text="МАКС", callback_data=f"private:trade_exec:{side}:{asset_id}:fixed:max"
        ),
    ]

    if side == "buy":
        fraction_buttons = [
            InlineKeyboardButton(
                text="1/4 баланса",
                callback_data=f"private:trade_exec:{side}:{asset_id}:fraction:25",
            ),
            InlineKeyboardButton(
                text="1/2 баланса",
                callback_data=f"private:trade_exec:{side}:{asset_id}:fraction:50",
            ),
            InlineKeyboardButton(
                text="Всё",
                callback_data=f"private:trade_exec:{side}:{asset_id}:fraction:100",
            ),
        ]
        fsm_state = app.fsm.FSM.PLAYING_BUY
    else:
        fraction_buttons = [
            InlineKeyboardButton(
                text="1/4 позиции",
                callback_data=f"private:trade_exec:{side}:{asset_id}:fraction:25",
            ),
            InlineKeyboardButton(
                text="1/2 позиции",
                callback_data=f"private:trade_exec:{side}:{asset_id}:fraction:50",
            ),
            InlineKeyboardButton(
                text="Всё",
                callback_data=f"private:trade_exec:{side}:{asset_id}:fraction:100",
            ),
        ]
        fsm_state = app.fsm.FSM.PLAYING_SELL

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            fixed_buttons,
            fraction_buttons,
            [
                InlineKeyboardButton(
                    text="Назад", callback_data=f"private:company:{asset_id}"
                )
            ],
        ]
    )
    chart = generate_asset_price_chart(asset_state, await _tick_seconds(app, game.id))
    new_data = dict(data)
    new_data["asset_id"] = asset_id
    new_data["trade_side"] = side
    return text, keyboard, chart, new_data, fsm_state


async def _build_portfolio_screen(
    app, tg_user_id: int, data: dict
) -> tuple[str, InlineKeyboardMarkup, str, dict, str]:
    platform = _screen_platform(data)
    _, _, game, state = await get_active_player_context(
        app, tg_user_id, platform=platform
    )
    snapshot = await build_portfolio_snapshot(app, tg_user_id, platform=platform)
    lines = sorted(snapshot["lines"], key=lambda line: line["asset_name"])

    page, total_pages = _current_page(
        len(lines), int(data.get("portfolio_page", 0)), _PORTFOLIO_PER_PAGE
    )
    page_lines = lines[page * _PORTFOLIO_PER_PAGE : (page + 1) * _PORTFOLIO_PER_PAGE]

    text_lines = [
        f"Общий капитал: {float(snapshot['total_capital']):.2f}",
        f"Баланс: {float(snapshot['balance']):.2f}",
        "",
    ]
    if not page_lines:
        text_lines.append("Портфель пуст.")
    else:
        text_lines.extend(
            f"{line['asset_name']} -- {line['amount']} ({float(line['capital']):.2f})"
            for line in page_lines
        )

    rows: list[list[InlineKeyboardButton]] = []
    if total_pages > 1:
        rows.append(
            [
                InlineKeyboardButton(
                    text="<-", callback_data="private:portfolio_page:-1"
                ),
                InlineKeyboardButton(
                    text=f"{page + 1}/{total_pages}", callback_data="noop"
                ),
                InlineKeyboardButton(
                    text="->", callback_data="private:portfolio_page:1"
                ),
            ]
        )
    rows.append([InlineKeyboardButton(text="Назад", callback_data="private:main")])

    assets = sorted(state.get("assets", {}).values(), key=lambda item: item["name"])
    companies_page = int(data.get("companies_page", 0))
    chart_assets = _main_chart_assets(app, assets, companies_page)
    chart = generate_private_main_chart(chart_assets, await _tick_seconds(app, game.id))
    new_data = dict(data)
    new_data["portfolio_page"] = page
    return (
        _safe_caption("\n".join(text_lines)),
        InlineKeyboardMarkup(inline_keyboard=rows),
        chart,
        new_data,
        app.fsm.FSM.PLAYING_PORTFOLIO,
    )


async def _build_history_screen(
    app, tg_user_id: int, data: dict
) -> tuple[str, InlineKeyboardMarkup, str, dict, str]:
    _, player, game, state = await get_active_player_context(
        app, tg_user_id, platform=_screen_platform(data)
    )
    deals = await app.market.deal.list_by_player(player.id, limit=200)

    page, total_pages = _current_page(
        len(deals), int(data.get("history_page", 0)), _TRADES_PER_PAGE
    )
    page_deals = deals[page * _TRADES_PER_PAGE : (page + 1) * _TRADES_PER_PAGE]

    lines = []
    if not page_deals:
        lines.append("Сделок пока нет.")
    else:
        for deal in page_deals:
            asset = await app.data.asset.get_by_id(deal.asset_id)
            asset_name = asset.name if asset else f"актив:{deal.asset_id}"
            money = round(float(deal.amount) * float(deal.price), 2)
            deal_label = "покупка" if deal.type.value == "buy" else "продажа"
            money_label = (
                f"потрачено {money:.2f}"
                if deal.type.value == "buy"
                else f"получено {money:.2f}"
            )
            lines.append(
                f"{deal_label} -- {asset_name} -- {deal.amount} -- {money_label}"
            )

    rows: list[list[InlineKeyboardButton]] = []
    if total_pages > 1:
        rows.append(
            [
                InlineKeyboardButton(
                    text="<-", callback_data="private:history_page:-1"
                ),
                InlineKeyboardButton(
                    text=f"{page + 1}/{total_pages}", callback_data="noop"
                ),
                InlineKeyboardButton(text="->", callback_data="private:history_page:1"),
            ]
        )
    rows.append([InlineKeyboardButton(text="Назад", callback_data="private:main")])

    assets = sorted(state.get("assets", {}).values(), key=lambda item: item["name"])
    companies_page = int(data.get("companies_page", 0))
    chart_assets = _main_chart_assets(app, assets, companies_page)
    chart = generate_private_main_chart(chart_assets, await _tick_seconds(app, game.id))
    new_data = dict(data)
    new_data["history_page"] = page
    return (
        _safe_caption("\n".join(lines)),
        InlineKeyboardMarkup(inline_keyboard=rows),
        chart,
        new_data,
        app.fsm.FSM.PLAYING_DEALS,
    )


async def _build_leave_confirm_screen(
    app, tg_user_id: int, data: dict
) -> tuple[str, InlineKeyboardMarkup, str, dict, str]:
    _, _, game, state = await get_active_player_context(
        app, tg_user_id, platform=_screen_platform(data)
    )
    assets = sorted(state.get("assets", {}).values(), key=lambda item: item["name"])
    companies_page = int(data.get("companies_page", 0))
    chart_assets = _main_chart_assets(app, assets, companies_page)
    chart = generate_private_main_chart(chart_assets, await _tick_seconds(app, game.id))

    text = (
        "Ты точно хочешь покинуть игру?\n"
        "Аккаунт будет заморожен, а капитал останется в лидерборде."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подтвердить выход", callback_data="private:leave_yes"
                ),
                InlineKeyboardButton(text="Отмена", callback_data="private:main"),
            ]
        ]
    )
    return text, keyboard, chart, dict(data), app.fsm.FSM.PLAYING_MAIN


async def build_private_screen(
    app,
    tg_user_id: int,
    screen: str,
    data: dict,
) -> tuple[str, InlineKeyboardMarkup, str, dict, str]:
    if screen == "company":
        return await _build_company_screen(app, tg_user_id, data)
    if screen == "trade":
        return await _build_trade_screen(app, tg_user_id, data)
    if screen == "portfolio":
        return await _build_portfolio_screen(app, tg_user_id, data)
    if screen == "history":
        return await _build_history_screen(app, tg_user_id, data)
    if screen == "leave_confirm":
        return await _build_leave_confirm_screen(app, tg_user_id, data)
    return await _build_main_screen(app, tg_user_id, data)


async def show_private_screen(
    app,
    tg_user_id: int,
    chat_id: int,
    screen: str,
    data: dict | None = None,
    message_id: int | None = None,
    *,
    force_new: bool = False,
    delete_after_send_message_id: int | None = None,
    target_platform: str | None = None,
) -> int | None:
    context = get_update_context() or {}
    resolved_platform = normalize_platform(target_platform or context.get("platform"))
    lock = _get_private_screen_lock(tg_user_id, resolved_platform)
    async with lock:
        data = dict(data or {})
        data["_client_platform"] = resolved_platform
        (
            caption,
            keyboard,
            chart_content_b64,
            new_data,
            fsm_state,
        ) = await build_private_screen(
            app,
            tg_user_id,
            screen,
            data,
        )

        payload = MessagePayload(
            chat_id=chat_id,
            text=caption,
            keyboard=keyboard,
            photo_content_b64=chart_content_b64,
            message_id=message_id,
            target_platform=resolved_platform,
        )

        if message_id and not force_new:
            stored_message_id = message_id
            edit_data = {
                **new_data,
                "screen": screen,
                "private_message_id": stored_message_id,
                "private_message_pending_since": None,
            }
            payload.fsm_update = {
                "user_id": tg_user_id,
                "platform": resolved_platform,
                "state": fsm_state,
                "data": edit_data,
                "message_field": "private_message_id",
            }
            await app.sender.edit_message(payload)
            await app.fsm.set_state(
                tg_user_id,
                fsm_state,
                edit_data,
                platform=resolved_platform,
            )
            return stored_message_id

        if data.get("private_message_pending"):
            if not _is_pending_stale(data.get("private_message_pending_since")):
                return None
            data["private_message_pending"] = False
            data["private_message_pending_since"] = None
            data["private_message_id"] = None

        previous_message_id = data.get("private_message_id")
        pending_data = {
            **new_data,
            "screen": screen,
            "private_message_id": previous_message_id,
            "private_message_pending": True,
            "private_message_pending_since": datetime.now(timezone.utc).isoformat(),
        }
        payload.fsm_update = {
            "user_id": tg_user_id,
            "platform": resolved_platform,
            "state": fsm_state,
            "data": pending_data,
            "message_field": "private_message_id",
            "pending_field": "private_message_pending",
        }
        await app.sender.send_message(payload)
        old_message_to_delete = delete_after_send_message_id or previous_message_id
        if old_message_to_delete:
            await app.sender.delete_message(
                chat_id,
                old_message_to_delete,
                target_platform=resolved_platform,
            )

        await app.fsm.set_state(
            tg_user_id, fsm_state, pending_data, platform=resolved_platform
        )
        return None


async def compute_trade_amount(
    app,
    tg_user_id: int,
    side: str,
    asset_id: int,
    mode: str,
    value: str,
    platform: str | None = None,
) -> int:
    if side not in {"buy", "sell"}:
        raise TradeError("Некорректная сторона сделки.")

    _, player, game, state = await get_active_player_context(
        app, tg_user_id, platform=platform
    )
    asset_state = state.get("assets", {}).get(str(asset_id))
    if asset_state is None:
        raise TradeError("Этот актив недоступен в текущей игре.")

    price = float(asset_state["current_price"])
    game_asset = await app.market.game_asset.get(game.id, asset_id)
    portfolio = await app.market.portfolio.get_or_create(player.id, asset_id)

    if mode == "fixed":
        if value == "max":
            if side == "buy":
                by_balance = int(player.balance // price)
                return max(
                    0, min(by_balance, game_asset.shares_available if game_asset else 0)
                )
            return max(0, int(portfolio.amount))
        amount = int(value)
        return max(0, amount)

    if mode != "fraction":
        raise TradeError("Некорректный режим сделки.")

    fraction = max(0.0, min(1.0, int(value) / 100.0))
    if side == "buy":
        budget = float(player.balance) * fraction
        by_balance = int(budget // price)
        return max(0, min(by_balance, game_asset.shares_available if game_asset else 0))

    amount = int(portfolio.amount * fraction)
    if int(value) == 100:
        amount = int(portfolio.amount)
    return max(0, amount)
