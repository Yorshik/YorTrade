from sqlalchemy import select

from app.market.models import Deal, DealType, Game, GameAsset, GameStatus, Portfolio
from app.store.database.accessor import DatabaseAccessor
from app.store.market.runtime_accessor import RuntimeAccessor


class _GameAccessor:
    def __init__(self, db: DatabaseAccessor):
        self.db = db

    def _current_game_stmt(self, chat_id: int, platform: str = "TG"):
        return (
            select(Game)
            .where(
                Game.chat_id == chat_id,
                Game.platform == str(platform).upper(),
                Game.status.in_((GameStatus.PENDING, GameStatus.ACTIVE)),
            )
            .order_by(Game.id.desc())
        )

    async def get_by_id(self, game_id: int) -> Game | None:
        async with self.db.session as session:
            stmt = select(Game).where(Game.id == game_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def create_game(
        self,
        user_id: int,
        chat_id: int,
        settings: dict | None = None,
        platform: str = "TG",
    ) -> Game:
        async with self.db.session as session:
            normalized_platform = str(platform).upper()
            existing_game = await session.execute(
                self._current_game_stmt(chat_id, normalized_platform)
            )
            current_game = existing_game.scalars().first()
            if current_game is not None:
                return current_game
            new_game = Game(
                chat_id=chat_id,
                host_id=user_id,
                settings=settings,
                platform=normalized_platform,
            )
            session.add(new_game)
            await session.commit()
            await session.refresh(new_game)
            return new_game

    async def get_by_chat_id(self, chat_id: int, platform: str = "TG") -> Game | None:
        async with self.db.session as session:
            stmt = self._current_game_stmt(chat_id, platform)
            result = await session.execute(stmt)
            return result.scalars().first()

    async def is_host(self, user_id: int, chat_id: int, platform: str = "TG") -> bool:
        game = await self.get_by_chat_id(chat_id, platform=platform)
        if not game:
            return False
        return game.host_id == user_id

    async def save(self, game: Game) -> Game:
        async with self.db.session as session:
            session.add(game)
            await session.commit()
            return game


class MarketAccessor:
    def __init__(self, db: DatabaseAccessor):
        self.game = _GameAccessor(db)
        self.game_asset = _GameAssetAccessor(db)
        self.portfolio = _PortfolioAccessor(db)
        self.deal = _DealAccessor(db)
        self.runtime = RuntimeAccessor(db)


class _GameAssetAccessor:
    def __init__(self, db: DatabaseAccessor):
        self.db = db

    async def list_by_game(self, game_id: int) -> list[GameAsset]:
        async with self.db.session as session:
            stmt = select(GameAsset).where(GameAsset.game_id == game_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def delete_by_game(self, game_id: int) -> None:
        async with self.db.session as session:
            assets = await session.execute(
                select(GameAsset).where(GameAsset.game_id == game_id)
            )
            for asset in assets.scalars().all():
                await session.delete(asset)
            await session.commit()

    async def create(
        self,
        *,
        game_id: int,
        asset_id: int,
        company_id: str | None = None,
        start_price: float,
        volatility: float,
        shares_total: int,
        shares_available: int,
    ) -> GameAsset:
        async with self.db.session as session:
            game_asset = GameAsset(
                game_id=game_id,
                asset_id=asset_id,
                company_id=company_id,
                start_price=start_price,
                volatility=volatility,
                shares_total=shares_total,
                shares_available=shares_available,
            )
            session.add(game_asset)
            await session.commit()
            await session.refresh(game_asset)
            return game_asset

    async def get(self, game_id: int, asset_id: int) -> GameAsset | None:
        async with self.db.session as session:
            stmt = select(GameAsset).where(
                GameAsset.game_id == game_id,
                GameAsset.asset_id == asset_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_by_company_id(self, game_id: int, company_id: str) -> GameAsset | None:
        async with self.db.session as session:
            stmt = select(GameAsset).where(
                GameAsset.game_id == game_id,
                GameAsset.company_id == str(company_id),
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def save(self, game_asset: GameAsset) -> GameAsset:
        async with self.db.session as session:
            session.add(game_asset)
            await session.commit()
            await session.refresh(game_asset)
            return game_asset


class _PortfolioAccessor:
    def __init__(self, db: DatabaseAccessor):
        self.db = db

    async def get(self, player_id: int, asset_id: int) -> Portfolio | None:
        async with self.db.session as session:
            stmt = select(Portfolio).where(
                Portfolio.player_id == player_id,
                Portfolio.asset_id == asset_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def list_by_player(self, player_id: int) -> list[Portfolio]:
        async with self.db.session as session:
            stmt = select(Portfolio).where(Portfolio.player_id == player_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_or_create(self, player_id: int, asset_id: int) -> Portfolio:
        portfolio = await self.get(player_id, asset_id)
        if portfolio:
            return portfolio
        async with self.db.session as session:
            portfolio = Portfolio(player_id=player_id, asset_id=asset_id, amount=0)
            session.add(portfolio)
            await session.commit()
            await session.refresh(portfolio)
            return portfolio

    async def save(self, portfolio: Portfolio) -> Portfolio:
        async with self.db.session as session:
            session.add(portfolio)
            await session.commit()
            await session.refresh(portfolio)
            return portfolio


class _DealAccessor:
    def __init__(self, db: DatabaseAccessor):
        self.db = db

    async def create(
        self,
        *,
        player_id: int,
        game_id: int,
        asset_id: int,
        deal_type: DealType,
        amount: int,
        price: float,
    ) -> Deal:
        async with self.db.session as session:
            deal = Deal(
                player_id=player_id,
                game_id=game_id,
                asset_id=asset_id,
                type=deal_type,
                amount=amount,
                price=price,
            )
            session.add(deal)
            await session.commit()
            await session.refresh(deal)
            return deal

    async def list_by_player(self, player_id: int, limit: int = 20) -> list[Deal]:
        async with self.db.session as session:
            stmt = (
                select(Deal)
                .where(Deal.player_id == player_id)
                .order_by(Deal.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())
