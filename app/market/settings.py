DEFAULT_GAME_SETTINGS = {
    "companies_amount": 6,
    "tick_seconds": 60,
    "game_duration_minutes": 20,
    "global_volatility": 10.0,
    "min_start_price": 100.0,
    "max_start_price": 200.0,
    "default_balance": 1000.0,
    "event_chance": 0.5,
    "news_chance": 0.5,
    "company_news_chance": 0.8,
    "insider_chance_per_player_per_tick": 0.25,
    "max_shares_per_asset": 1000,
}


def build_default_game_settings() -> dict:
    return DEFAULT_GAME_SETTINGS.copy()
