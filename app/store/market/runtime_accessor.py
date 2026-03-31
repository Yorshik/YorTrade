from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import delete, select, update

from app.market.models import (
    ActiveEvent,
    Company,
    EventTemplate,
    GameRuntimeState,
    InsiderInfo,
    MarketDirection,
    News,
    PriceHistory,
)
from app.store.database.accessor import DatabaseAccessor


class RuntimeAccessor:
    def __init__(self, db: DatabaseAccessor):
        self.db = db

    async def get_state(self, game_id: int) -> dict | None:
        async with self.db.session as session:
            stmt = select(GameRuntimeState).where(GameRuntimeState.game_id == game_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return dict(row.state or {})

    async def save_state(self, game_id: int, state: dict) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        payload = dict(state)
        payload["updated_at"] = now
        async with self.db.session as session:
            stmt = select(GameRuntimeState).where(GameRuntimeState.game_id == game_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                row = GameRuntimeState(game_id=game_id, state=payload)
            else:
                row.state = payload
                row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            await session.commit()
        return payload

    async def set_companies(self, game_id: int, companies: Iterable[dict]) -> None:
        async with self.db.session as session:
            await session.execute(delete(Company).where(Company.game_id == game_id))
            for payload in companies:
                session.add(
                    Company(
                        game_id=game_id,
                        id=str(payload["id"]),
                        name=str(payload["name"]),
                        current_price=float(payload["current_price"]),
                        volatility=float(payload["volatility"]),
                    )
                )
            await session.commit()

    async def list_companies(self, game_id: int) -> list[Company]:
        async with self.db.session as session:
            stmt = (
                select(Company)
                .where(Company.game_id == game_id)
                .order_by(Company.id.asc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def update_company_prices(self, game_id: int, prices: dict[str, float]) -> None:
        if not prices:
            return
        async with self.db.session as session:
            for company_id, price in prices.items():
                await session.execute(
                    update(Company)
                    .where(Company.game_id == game_id, Company.id == str(company_id))
                    .values(current_price=float(price))
                )
            await session.commit()

    async def append_price_history(self, rows: Iterable[dict]) -> None:
        items = list(rows)
        if not items:
            return
        async with self.db.session as session:
            for row in items:
                session.add(
                    PriceHistory(
                        game_id=int(row["game_id"]),
                        company_id=str(row["company_id"]),
                        tick=int(row["tick"]),
                        price=float(row["price"]),
                    )
                )
            await session.commit()

    async def list_price_history(self, game_id: int) -> list[PriceHistory]:
        async with self.db.session as session:
            stmt = (
                select(PriceHistory)
                .where(PriceHistory.game_id == game_id)
                .order_by(PriceHistory.company_id.asc(), PriceHistory.tick.asc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def upsert_event_templates(self, templates: Iterable[dict]) -> int:
        created_or_updated = 0
        async with self.db.session as session:
            for payload in templates:
                template_id = str(payload["id"])
                stmt = select(EventTemplate).where(EventTemplate.id == template_id)
                result = await session.execute(stmt)
                model = result.scalar_one_or_none()
                if model is None:
                    model = EventTemplate(id=template_id)
                model.title = str(payload["title"])
                model.description = str(payload["description"])
                model.effects = payload.get("effects") or {}
                model.duration_ticks = int(payload.get("duration_ticks", 1) or 1)
                model.image_id = str(payload.get("image_id")) if payload.get("image_id") else None
                session.add(model)
                created_or_updated += 1
            await session.commit()
        return created_or_updated

    async def list_event_templates(self) -> list[EventTemplate]:
        async with self.db.session as session:
            stmt = select(EventTemplate).order_by(EventTemplate.id.asc())
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def create_active_event(self, payload: dict) -> ActiveEvent:
        async with self.db.session as session:
            stmt = select(ActiveEvent).where(ActiveEvent.id == str(payload["id"]))
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                model = ActiveEvent(id=str(payload["id"]))
            model.game_id = int(payload["game_id"])
            model.template_id = str(payload["template_id"])
            model.company_id = (
                str(payload["company_id"]) if payload.get("company_id") is not None else None
            )
            model.strength = float(payload.get("strength", 0.0))
            model.start_tick = int(payload["start_tick"])
            model.end_tick = int(payload["end_tick"])
            model.meta = payload.get("meta") or {}
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return model

    async def list_active_events_for_tick(self, game_id: int, tick: int) -> list[ActiveEvent]:
        async with self.db.session as session:
            stmt = (
                select(ActiveEvent)
                .where(
                    ActiveEvent.game_id == game_id,
                    ActiveEvent.start_tick <= tick,
                    ActiveEvent.end_tick >= tick,
                )
                .order_by(ActiveEvent.start_tick.asc(), ActiveEvent.id.asc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def delete_finished_events(self, game_id: int, tick: int) -> int:
        async with self.db.session as session:
            stmt = delete(ActiveEvent).where(
                ActiveEvent.game_id == game_id,
                ActiveEvent.end_tick < tick,
            )
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)

    async def create_news(self, payload: dict) -> News:
        async with self.db.session as session:
            stmt = select(News).where(News.id == str(payload["id"]))
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                model = News(id=str(payload["id"]))
            model.game_id = int(payload["game_id"])
            model.company_id = str(payload["company_id"])
            model.direction = MarketDirection(str(payload["direction"]).lower())
            model.strength = float(payload["strength"])
            model.tick = int(payload["tick"])
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return model

    async def list_news_for_tick(self, game_id: int, tick: int) -> list[News]:
        async with self.db.session as session:
            stmt = (
                select(News)
                .where(News.game_id == game_id, News.tick == tick)
                .order_by(News.id.asc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def create_insider_info(self, payload: dict) -> InsiderInfo:
        async with self.db.session as session:
            stmt = select(InsiderInfo).where(InsiderInfo.id == str(payload["id"]))
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                model = InsiderInfo(id=str(payload["id"]))
            model.game_id = int(payload["game_id"])
            model.company_id = str(payload["company_id"])
            model.direction = MarketDirection(str(payload["direction"]).lower())
            model.strength = float(payload["strength"])
            model.target_tick = int(payload["target_tick"])
            model.is_true = bool(payload["is_true"])
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return model

    async def list_insider_for_tick(self, game_id: int, tick: int) -> list[InsiderInfo]:
        async with self.db.session as session:
            stmt = (
                select(InsiderInfo)
                .where(InsiderInfo.game_id == game_id, InsiderInfo.target_tick == tick)
                .order_by(InsiderInfo.id.asc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())
