import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.market import event_engine, tick_processor


def test_scaled_curve_keeps_shape_for_base_duration() -> None:
    curve = tick_processor._scaled_curve(6)
    assert curve == [0.5, 0.8, 1.0, 1.0, 0.8, 0.5]


def test_process_tick_applies_event_news_insider_order_impact_and_noise(monkeypatch) -> None:
    monkeypatch.setattr(tick_processor.random, "uniform", lambda _a, _b: 0.0)

    company = SimpleNamespace(id="cmp_1", name="Company A", current_price=100.0)
    active_event = SimpleNamespace(
        id="evt1",
        template_id="tpl1",
        company_id="cmp_1",
        strength=0.0,
        start_tick=1,
        end_tick=1,
        meta={"title": "Event A"},
    )
    template = SimpleNamespace(
        id="tpl1",
        title="Event A",
        effects={"strength": 0.05, "direction": "up"},
    )
    news = SimpleNamespace(company_id="cmp_1", direction="down", strength=0.02)
    insider = SimpleNamespace(
        company_id="cmp_1",
        direction="up",
        strength=0.03,
        is_true=False,
    )

    runtime = SimpleNamespace(
        list_companies=AsyncMock(return_value=[company]),
        list_active_events_for_tick=AsyncMock(return_value=[active_event]),
        list_event_templates=AsyncMock(return_value=[template]),
        list_news_for_tick=AsyncMock(return_value=[news]),
        list_insider_for_tick=AsyncMock(return_value=[insider]),
        update_company_prices=AsyncMock(),
        append_price_history=AsyncMock(),
        delete_finished_events=AsyncMock(),
    )
    app = SimpleNamespace(market=SimpleNamespace(runtime=runtime))
    state = {
        "tick": 1,
        "assets": {
            "7": {
                "asset_id": 7,
                "company_id": "cmp_1",
                "name": "Company A",
                "current_price": 100.0,
                "history": [100.0],
                "pending_order_impact": 2.0,
            }
        },
    }

    updated_state, tick_events = asyncio.run(
        tick_processor.process_tick(app, game_id=10, state=state)
    )

    assert tick_events
    assert updated_state["assets"]["7"]["current_price"] == 102.0
    assert updated_state["assets"]["7"]["pending_order_impact"] == 0.0
    runtime.update_company_prices.assert_awaited_once_with(10, {"cmp_1": 102.0})


def test_process_tick_clamps_to_ten_percent(monkeypatch) -> None:
    monkeypatch.setattr(tick_processor.random, "uniform", lambda _a, _b: 0.0)

    company = SimpleNamespace(id="cmp_1", name="Company A", current_price=100.0)
    active_event = SimpleNamespace(
        id="evt1",
        template_id="tpl1",
        company_id="cmp_1",
        strength=0.0,
        start_tick=1,
        end_tick=1,
        meta={"title": "Event A"},
    )
    template = SimpleNamespace(
        id="tpl1",
        title="Event A",
        effects={"strength": 1.0, "direction": "up"},
    )

    runtime = SimpleNamespace(
        list_companies=AsyncMock(return_value=[company]),
        list_active_events_for_tick=AsyncMock(return_value=[active_event]),
        list_event_templates=AsyncMock(return_value=[template]),
        list_news_for_tick=AsyncMock(return_value=[]),
        list_insider_for_tick=AsyncMock(return_value=[]),
        update_company_prices=AsyncMock(),
        append_price_history=AsyncMock(),
        delete_finished_events=AsyncMock(),
    )
    app = SimpleNamespace(market=SimpleNamespace(runtime=runtime))
    state = {
        "tick": 1,
        "assets": {
            "7": {
                "asset_id": 7,
                "company_id": "cmp_1",
                "name": "Company A",
                "current_price": 100.0,
                "history": [100.0],
                "pending_order_impact": 0.0,
            }
        },
    }

    updated_state, _ = asyncio.run(tick_processor.process_tick(app, game_id=10, state=state))
    assert updated_state["assets"]["7"]["current_price"] == 110.0


def test_process_tick_supports_list_effects_for_global_event(monkeypatch) -> None:
    monkeypatch.setattr(tick_processor.random, "uniform", lambda _a, _b: 0.0)

    company_a = SimpleNamespace(id="cmp_1", name="Company A", current_price=100.0)
    company_b = SimpleNamespace(id="cmp_2", name="Company B", current_price=100.0)
    active_event = SimpleNamespace(
        id="evt1",
        template_id="tpl1",
        company_id=None,
        strength=0.0,
        start_tick=1,
        end_tick=1,
        meta={"title": "Event A"},
    )
    template = SimpleNamespace(
        id="tpl1",
        title="Event A",
        effects=[
            {"company_id": "cmp_1", "direction": "up", "strength": 0.1},
        ],
    )

    runtime = SimpleNamespace(
        list_companies=AsyncMock(return_value=[company_a, company_b]),
        list_active_events_for_tick=AsyncMock(return_value=[active_event]),
        list_event_templates=AsyncMock(return_value=[template]),
        list_news_for_tick=AsyncMock(return_value=[]),
        list_insider_for_tick=AsyncMock(return_value=[]),
        update_company_prices=AsyncMock(),
        append_price_history=AsyncMock(),
        delete_finished_events=AsyncMock(),
    )
    app = SimpleNamespace(market=SimpleNamespace(runtime=runtime))
    state = {
        "tick": 1,
        "assets": {
            "7": {
                "asset_id": 7,
                "company_id": "cmp_1",
                "name": "Company A",
                "current_price": 100.0,
                "history": [100.0],
                "pending_order_impact": 0.0,
            },
            "8": {
                "asset_id": 8,
                "company_id": "cmp_2",
                "name": "Company B",
                "current_price": 100.0,
                "history": [100.0],
                "pending_order_impact": 0.0,
            },
        },
    }

    updated_state, _ = asyncio.run(
        tick_processor.process_tick(app, game_id=10, state=state)
    )

    assert updated_state["assets"]["7"]["current_price"] == 110.0
    assert updated_state["assets"]["8"]["current_price"] == 100.0
    runtime.update_company_prices.assert_awaited_once_with(
        10, {"cmp_1": 110.0, "cmp_2": 100.0}
    )


def test_schedule_market_drivers_is_deterministic(monkeypatch) -> None:
    companies = [SimpleNamespace(id="cmp_1", volatility=10.0)]
    template = SimpleNamespace(
        id="tpl_1",
        title="Template",
        description="Desc",
        duration_ticks=2,
        effects={"strength": 0.01},
        image_id="pic_1",
    )

    runtime = SimpleNamespace(
        list_companies=AsyncMock(return_value=companies),
        list_event_templates=AsyncMock(return_value=[template]),
        create_active_event=AsyncMock(),
        create_news=AsyncMock(),
        create_insider_info=AsyncMock(),
    )
    game = SimpleNamespace(
        settings={
            "event_chance": 1.0,
            "news_chance": 1.0,
            "insider_chance_per_player_per_tick": 1.0,
        }
    )
    app = SimpleNamespace(
        market=SimpleNamespace(
            game=SimpleNamespace(get_by_id=AsyncMock(return_value=game)),
            runtime=runtime,
        )
    )
    monkeypatch.setattr(
        event_engine,
        "load_news_catalog",
        lambda: [
            {"company_id": "cmp_1", "direction": "up", "text": "Новость по cmp_1"}
        ],
    )
    state = {
        "tick": 5,
        "assets": {"1": {"asset_id": 1, "company_id": "cmp_1", "name": "A"}},
        "last_news": [],
    }

    first_state, first_generated = asyncio.run(
        event_engine.schedule_market_drivers(app, 77, dict(state))
    )
    second_state, second_generated = asyncio.run(
        event_engine.schedule_market_drivers(app, 77, dict(state))
    )

    assert first_generated == second_generated
    assert first_state["last_event"] == second_state["last_event"]
    assert first_state["last_insider_info"] == second_state["last_insider_info"]
