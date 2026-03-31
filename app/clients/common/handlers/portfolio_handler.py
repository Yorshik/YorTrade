from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import MessagePayload, MessageType, Update
from app.utils.trading import (
    TradeError,
    build_portfolio_snapshot,
    get_active_player_context,
)


class PortfolioHandler(BaseHandler):
    async def check(self, update: Update) -> bool:
        if update.type != MessageType.TEXT or not update.text or not update.from_user:
            return False
        if not update.message or update.message.chat.type != "private":
            return False
        command = self.cut_prefix(update.text)
        return command in {"portfolio", "deals"}

    async def handle(self, update: Update) -> MessagePayload | None:
        command = self.cut_prefix(update.text or "")
        source_platform = (update.source_platform or "TG").upper()
        try:
            if command == "portfolio":
                snapshot = await build_portfolio_snapshot(
                    self.app,
                    update.from_user.id,
                    platform=source_platform,
                )
                lines = snapshot["lines"]
                if not lines:
                    body = "Портфель пуст."
                else:
                    body = "\n".join(
                        f"{line['asset_name']} [id={line['asset_id']}]: {line['amount']} шт. x {line['current_price']} = {line['capital']}"
                        for line in lines[:20]
                    )
                return MessagePayload(
                    chat_id=update.chat_id,
                    text=(
                        f"Баланс: {snapshot['balance']}\n"
                        f"Капитал активов: {snapshot['assets_capital']}\n"
                        f"Общий капитал: {snapshot['total_capital']}\n\n"
                        f"Место в лидерборде: {snapshot['rank'] or '-'}\n\n"
                        f"{body}"
                    ),
                )

            if command == "market":
                _, _, _, state = await get_active_player_context(
                    self.app,
                    update.from_user.id,
                    platform=source_platform,
                )
                assets = sorted(
                    state.get("assets", {}).values(), key=lambda asset: asset["name"]
                )
                return MessagePayload(
                    chat_id=update.chat_id,
                    text="\n".join(
                        f"{asset['name']} [id={asset['asset_id']}]: {asset['current_price']}"
                        for asset in assets[:100]
                    )
                    or "Рынок пуст.",
                )

            _, player, _, _ = await get_active_player_context(
                self.app,
                update.from_user.id,
                platform=source_platform,
            )
            deals = await self.app.market.deal.list_by_player(player.id, limit=10)
            if not deals:
                return MessagePayload(chat_id=update.chat_id, text="Сделок пока нет.")

            lines = []
            for deal in deals:
                asset = await self.app.data.asset.get_by_id(deal.asset_id)
                asset_name = asset.name if asset else f"актив:{deal.asset_id}"
                deal_label = "ПОКУПКА" if deal.type.value == "buy" else "ПРОДАЖА"
                lines.append(f"{deal_label} {asset_name} x{deal.amount} @ {deal.price}")
            return MessagePayload(chat_id=update.chat_id, text="\n".join(lines))
        except TradeError as exc:
            return MessagePayload(chat_id=update.chat_id, text=str(exc))
