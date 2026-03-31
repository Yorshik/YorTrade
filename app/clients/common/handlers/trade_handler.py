from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import MessagePayload, MessageType, Update
from app.market.models import DealType
from app.utils.trading import TradeError, execute_trade


class TradeHandler(BaseHandler):
    async def check(self, update: Update) -> bool:
        if update.type != MessageType.TEXT or not update.text or not update.from_user:
            return False
        if not update.message or update.message.chat.type != "private":
            return False
        command = self.cut_prefix(update.text).split()
        return bool(command and command[0] in {"buy", "sell"})

    async def handle(self, update: Update) -> MessagePayload | None:
        source_platform = (update.source_platform or "TG").upper()
        parts = self.cut_prefix(update.text or "").split()
        if len(parts) != 3:
            return MessagePayload(
                chat_id=update.chat_id,
                text="Формат: /buy <asset_id> <amount> или /sell <asset_id> <amount>",
            )

        command, asset_id_raw, amount_raw = parts
        try:
            amount = int(amount_raw)
        except ValueError:
            return MessagePayload(
                chat_id=update.chat_id,
                text="Количество должно быть числом.",
            )
        asset_id: int | str
        asset_id = int(asset_id_raw) if asset_id_raw.isdigit() else asset_id_raw

        deal_type = DealType.BUY if command == "buy" else DealType.SELL
        try:
            result = await execute_trade(
                self.app,
                update.from_user.id,
                asset_id,
                amount,
                deal_type,
                platform=source_platform,
            )
        except TradeError as exc:
            return MessagePayload(chat_id=update.chat_id, text=str(exc))

        action = "Куплено" if deal_type == DealType.BUY else "Продано"
        return MessagePayload(
            chat_id=update.chat_id,
            text=(
                f"{action}: {result['asset_name']}\n"
                f"Количество: {result['amount']}\n"
                f"Цена: {result['price']}\n"
                f"Сумма: {result['total_value']}\n"
                f"Баланс: {result['balance']}\n"
                f"Теперь акций: {result['portfolio_amount']}"
            ),
        )
