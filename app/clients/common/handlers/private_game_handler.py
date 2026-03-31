from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import MessagePayload, MessageType, Update
from app.market.models import DealType
from app.utils.private_ui import compute_trade_amount, show_private_screen
from app.utils.trading import (
    TradeError,
    execute_trade,
    get_active_player_context,
    leave_active_game,
)


class PrivateGameHandler(BaseHandler):
    async def check(self, update: Update) -> bool:
        if not update.from_user:
            return False
        if (
            update.type == MessageType.TEXT
            and update.message
            and update.message.chat.type == "private"
        ):
            command = self.cut_prefix(update.text)
            return command in {"game", "market"}
        if (
            update.type == MessageType.CALLBACK_QUERY
            and update.callback_query.message
            and update.callback_query.message.chat.type == "private"
        ):
            return (update.callback_query.data or "").startswith("private:")
        return False

    async def handle(self, update: Update) -> MessagePayload | None:
        source_platform = (update.source_platform or "TG").upper()
        if update.type == MessageType.TEXT:
            try:
                await get_active_player_context(
                    self.app, update.from_user.id, platform=source_platform
                )
            except TradeError as exc:
                return MessagePayload(chat_id=update.chat_id, text=str(exc))
            await show_private_screen(
                self.app,
                update.from_user.id,
                update.chat_id,
                "main",
                target_platform=source_platform,
            )
            return None

        data = update.callback_query.data or ""
        state = await self.app.fsm.get_state(
            update.from_user.id, platform=source_platform
        )
        fsm_data = state[1] if state else {}
        message_id = (
            fsm_data.get("private_message_id")
            or update.callback_query.message.message_id
        )

        if fsm_data.get("private_message_pending"):
            await self.app.sender.answer_callback_query(
                callback_query_id=update.callback_query.id,
                text="Интерфейс обновляется, попробуй через секунду.",
                show_alert=False,
            )
            return None

        if data != "private:leave_yes":
            await self.app.sender.answer_callback_query(
                callback_query_id=update.callback_query.id,
                text="",
            )

        try:
            if data == "private:main":
                await show_private_screen(
                    self.app,
                    update.from_user.id,
                    update.chat_id,
                    "main",
                    fsm_data,
                    message_id,
                    target_platform=source_platform,
                )
            elif data.startswith("private:companies_page:"):
                shift = int(data.split(":")[-1])
                new_data = dict(fsm_data)
                new_data["companies_page"] = (
                    int(new_data.get("companies_page", 0)) + shift
                )
                await show_private_screen(
                    self.app,
                    update.from_user.id,
                    update.chat_id,
                    "main",
                    new_data,
                    message_id,
                    target_platform=source_platform,
                )
            elif data.startswith("private:company:"):
                asset_id = int(data.split(":")[-1])
                await show_private_screen(
                    self.app,
                    update.from_user.id,
                    update.chat_id,
                    "company",
                    {**fsm_data, "asset_id": asset_id},
                    message_id,
                    target_platform=source_platform,
                )
            elif data.startswith("private:trade_menu:"):
                _, _, side, asset_id_raw = data.split(":")
                await show_private_screen(
                    self.app,
                    update.from_user.id,
                    update.chat_id,
                    "trade",
                    {**fsm_data, "asset_id": int(asset_id_raw), "trade_side": side},
                    message_id,
                    target_platform=source_platform,
                )
            elif data.startswith("private:trade_exec:"):
                _, _, side, asset_id_raw, mode, value = data.split(":")
                asset_id = int(asset_id_raw)
                amount = await compute_trade_amount(
                    self.app,
                    update.from_user.id,
                    side,
                    asset_id,
                    mode,
                    value,
                    platform=source_platform,
                )
                if amount <= 0:
                    await self.app.sender.answer_callback_query(
                        callback_query_id=update.callback_query.id,
                        text="Нет объёма для сделки.",
                        show_alert=True,
                    )
                    return None

                deal_type = DealType.BUY if side == "buy" else DealType.SELL
                result = await execute_trade(
                    self.app,
                    update.from_user.id,
                    asset_id,
                    amount,
                    deal_type,
                    platform=source_platform,
                )
                await self.app.sender.answer_callback_query(
                    callback_query_id=update.callback_query.id,
                    text=(
                        f"{'Куплено' if deal_type == DealType.BUY else 'Продано'} "
                        f"{result['amount']} акций"
                    ),
                    show_alert=False,
                )
                await show_private_screen(
                    self.app,
                    update.from_user.id,
                    update.chat_id,
                    "trade",
                    {**fsm_data, "asset_id": asset_id, "trade_side": side},
                    message_id,
                    target_platform=source_platform,
                )
            elif data == "private:portfolio":
                await show_private_screen(
                    self.app,
                    update.from_user.id,
                    update.chat_id,
                    "portfolio",
                    {**fsm_data, "portfolio_page": 0},
                    message_id,
                    target_platform=source_platform,
                )
            elif data.startswith("private:portfolio_page:"):
                shift = int(data.split(":")[-1])
                new_data = dict(fsm_data)
                new_data["portfolio_page"] = (
                    int(new_data.get("portfolio_page", 0)) + shift
                )
                await show_private_screen(
                    self.app,
                    update.from_user.id,
                    update.chat_id,
                    "portfolio",
                    new_data,
                    message_id,
                    target_platform=source_platform,
                )
            elif data == "private:history":
                await show_private_screen(
                    self.app,
                    update.from_user.id,
                    update.chat_id,
                    "history",
                    {**fsm_data, "history_page": 0},
                    message_id,
                    target_platform=source_platform,
                )
            elif data.startswith("private:history_page:"):
                shift = int(data.split(":")[-1])
                new_data = dict(fsm_data)
                new_data["history_page"] = int(new_data.get("history_page", 0)) + shift
                await show_private_screen(
                    self.app,
                    update.from_user.id,
                    update.chat_id,
                    "history",
                    new_data,
                    message_id,
                    target_platform=source_platform,
                )
            elif data == "private:leave_confirm":
                await show_private_screen(
                    self.app,
                    update.from_user.id,
                    update.chat_id,
                    "leave_confirm",
                    fsm_data,
                    message_id,
                    target_platform=source_platform,
                )
            elif data == "private:leave_yes":
                result = await leave_active_game(
                    self.app, update.from_user.id, platform=source_platform
                )
                await self.app.sender.answer_callback_query(
                    callback_query_id=update.callback_query.id,
                    text="Ты покинул игру.",
                    show_alert=False,
                )
                await self.app.sender.send_message(
                    MessagePayload(
                        chat_id=update.chat_id,
                        target_platform=source_platform,
                        text="\n".join(
                            [
                                line
                                for line in [
                                    "Ты покинул игру.",
                                    f"Баланс: {result['balance']:.2f}",
                                    f"Капитал активов: {result['assets_capital']:.2f}",
                                    f"Зафиксированный итоговый капитал: {result['total_capital']:.2f}",
                                    (
                                        "Игра завершилась автоматически: "
                                        f"активных игроков осталось {result['active_players_left']}, "
                                        f"минимум {result['min_players']}."
                                    )
                                    if result.get("game_finished")
                                    else None,
                                ]
                                if line
                            ]
                        ),
                    )
                )
                await self.app.sender.delete_message(
                    update.chat_id, message_id, target_platform=source_platform
                )
            else:
                return None
        except TradeError as exc:
            await self.app.sender.answer_callback_query(
                callback_query_id=update.callback_query.id,
                text=str(exc),
                show_alert=True,
            )
            return None

        return None
