from sqlalchemy import select

from app.data.models import Asset, Phrase, PhraseType
from app.store.database.accessor import DatabaseAccessor


class _AssetAccessor:
    def __init__(self, db: DatabaseAccessor):
        self.db = db

    async def get_by_id(self, asset_id: int) -> Asset | None:
        async with self.db.session as session:
            stmt = select(Asset).where(Asset.id == asset_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Asset | None:
        async with self.db.session as session:
            stmt = select(Asset).where(Asset.name == name)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def create(self, name: str, base_volatility: float = 0.0) -> Asset:
        async with self.db.session as session:
            asset = Asset(name=name, base_volatility=base_volatility)
            session.add(asset)
            await session.commit()
            await session.refresh(asset)
            return asset

    async def get_or_create(
        self, name: str, base_volatility: float = 0.0
    ) -> tuple[Asset, bool]:
        asset = await self.get_by_name(name)
        if asset:
            return asset, False
        return await self.create(name, base_volatility), True

    async def list_all(self) -> list[Asset]:
        async with self.db.session as session:
            stmt = select(Asset).order_by(Asset.id)
            result = await session.execute(stmt)
            return list(result.scalars().all())


class _PhraseAccessor:
    def __init__(self, db: DatabaseAccessor):
        self.db = db

    async def get(
        self,
        *,
        phrase_type: PhraseType,
        phrase: str,
        asset_id: int | None = None,
    ) -> Phrase | None:
        async with self.db.session as session:
            stmt = select(Phrase).where(
                Phrase.type == phrase_type,
                Phrase.phrase == phrase,
                Phrase.asset_id == asset_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def create(
        self,
        *,
        phrase_type: PhraseType,
        phrase: str,
        asset_id: int | None = None,
    ) -> Phrase:
        async with self.db.session as session:
            phrase_model = Phrase(
                type=phrase_type,
                phrase=phrase,
                asset_id=asset_id,
            )
            session.add(phrase_model)
            await session.commit()
            await session.refresh(phrase_model)
            return phrase_model

    async def get_or_create(
        self,
        *,
        phrase_type: PhraseType,
        phrase: str,
        asset_id: int | None = None,
    ) -> tuple[Phrase, bool]:
        phrase_model = await self.get(
            phrase_type=phrase_type,
            phrase=phrase,
            asset_id=asset_id,
        )
        if phrase_model:
            return phrase_model, False
        return await self.create(
            phrase_type=phrase_type,
            phrase=phrase,
            asset_id=asset_id,
        ), True

    async def list_for_asset(
        self, asset_id: int, phrase_type: PhraseType
    ) -> list[Phrase]:
        async with self.db.session as session:
            stmt = select(Phrase).where(
                Phrase.asset_id == asset_id,
                Phrase.type == phrase_type,
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())


class DataAccessor:
    def __init__(self, db: DatabaseAccessor):
        self.asset = _AssetAccessor(db)
        self.phrase = _PhraseAccessor(db)
