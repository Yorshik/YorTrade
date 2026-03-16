from enum import StrEnum


class FSM(StrEnum):
    IDLE = "idle"
    IN_LOBBY = "in_lobby"
    GAME_SETTINGS = "game_settings"
    PLAYING_MAIN = "playing_main"
    PLAYING_ASSET = "playing_asset"
    PLAYING_BUY = "playing_buy"
    PLAYING_SELL = "playing_sell"
    PLAYING_PORTFOLIO = "playing_portfolio"
    PLAYING_DEALS = "playing_deals"
    # legacy — kept for existing sessions in DB
    PLAYING_DEAL_HISTORY = "playing_deal_history"
    PLAYING_PORTFOLIO_ASSET = "playing_portfolio_asset"
    PLAYING_PRICE_HISTORY = "playing_price_history"

    def __str__(self):
        return self.value
