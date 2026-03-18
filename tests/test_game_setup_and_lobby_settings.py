import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.utils import game_setup, lobby


def test_initialize_game_market_uses_all_companies_and_catalog_prices(
    monkeypatch,
) -> None:
    catalog = {
        "companies": [
            {
                "asset_id": 1,
                "company_id": "cmp_1",
                "name": "Alpha",
                "start_price": 9999.0,
                "volatility": 99.9,
            },
            {
                "asset_id": 2,
                "company_id": "cmp_2",
                "name": "Beta",
                "start_price": 8888.0,
                "volatility": 88.8,
            },
        ]
    }
    monkeypatch.setattr(game_setup, "ensure_market_catalog", AsyncMock(return_value=catalog))
    monkeypatch.setattr(game_setup, "_random_volatility", lambda _global: 7.7)
    monkeypatch.setattr(game_setup, "save_runtime_state", AsyncMock())

    app = SimpleNamespace(
        market=SimpleNamespace(
            game_asset=SimpleNamespace(
                delete_by_game=AsyncMock(),
                create=AsyncMock(),
            ),
            runtime=SimpleNamespace(
                set_companies=AsyncMock(),
                append_price_history=AsyncMock(),
            ),
        )
    )
    game = SimpleNamespace(
        id=77,
        chat_id=-1001,
        platform="TG",
        settings={
            "global_volatility": 9.0,
        },
    )

    state = asyncio.run(game_setup.initialize_game_market(app, game))

    assert len(state["assets"]) == 2
    prices = sorted(asset["start_price"] for asset in state["assets"].values())
    assert prices == [8888.0, 9999.0]
    assert all(asset["volatility"] == 7.7 for asset in state["assets"].values())

    create_calls = app.market.game_asset.create.await_args_list
    assert len(create_calls) == 2
    created_prices = sorted(call.kwargs["start_price"] for call in create_calls)
    assert created_prices == [8888.0, 9999.0]
    assert all(call.kwargs["volatility"] == 7.7 for call in create_calls)


def test_set_setting_value_accepts_comma_for_float_fields() -> None:
    settings = lobby.normalize_game_settings({})
    updated = lobby.set_setting_value(settings, "global_volatility", "12,5")

    assert updated["global_volatility"] == 12.5


def test_set_setting_value_accepts_integer_like_float_for_int_fields() -> None:
    settings = lobby.normalize_game_settings({})
    updated = lobby.set_setting_value(settings, "tick_seconds", "60.0")

    assert updated["tick_seconds"] == 60


def test_settings_keyboard_hides_companies_and_price_fields() -> None:
    settings = lobby.normalize_game_settings({})
    keyboard = lobby.render_settings_keyboard(settings)
    labels = [
        button.text
        for row in keyboard.inline_keyboard
        for button in row
        if button.text not in {"-", "+", "Назад"}
    ]

    assert all("Компании" not in label for label in labels)
    assert all("Мин. цена" not in label for label in labels)
    assert all("Макс. цена" not in label for label in labels)
    assert any("Волатильность" in label for label in labels)
