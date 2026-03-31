from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.market.models import Game, GameStatus
from app.store.database.accessor import DatabaseAccessor
from app.users.models import AchievementStats, Player, User
from app.utils.platform import normalize_platform


class _UserAccessor:
    def __init__(self, db: DatabaseAccessor):
        self.db = db

    @staticmethod
    def _platform(platform: str | None) -> str:
        return normalize_platform(platform)

    async def get_by_id(self, user_id: int) -> User | None:
        async with self.db.session as session:
            stmt = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_by_external(
        self, platform: str, external_user_id: int
    ) -> User | None:
        platform = self._platform(platform)
        async with self.db.session as session:
            stmt = select(User).where(
                User.platform == platform,
                User.tg_user_id == external_user_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def create(
        self, platform: str, external_user_id: int, username: str | None = None
    ) -> User:
        platform = self._platform(platform)
        async with self.db.session as session:
            new_user = User(
                platform=platform,
                tg_user_id=external_user_id,
                username=username,
            )
            session.add(new_user)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                stmt = select(User).where(
                    User.platform == platform,
                    User.tg_user_id == external_user_id,
                )
                result = await session.execute(stmt)
                existing_user = result.scalar_one_or_none()
                if existing_user is None:
                    raise
                return existing_user
            await session.refresh(new_user)
            return new_user

    async def get_or_create(
        self,
        platform: str,
        external_user_id: int,
        username: str | None = None,
    ) -> tuple[User, bool]:
        platform = self._platform(platform)
        async with self.db.session as session:
            stmt = select(User).where(
                User.platform == platform,
                User.tg_user_id == external_user_id,
            )
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if user is not None:
                if username and user.username != username:
                    user.username = username
                    session.add(user)
                    await session.commit()
                    await session.refresh(user)
                return user, False

            user = User(
                platform=platform,
                tg_user_id=external_user_id,
                username=username,
            )
            session.add(user)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                result = await session.execute(stmt)
                existing_user = result.scalar_one_or_none()
                if existing_user is None:
                    raise
                return existing_user, False

            await session.refresh(user)
            return user, True

    async def update_private_chat(self, user: User, dm_chat_id: int) -> User:
        async with self.db.session as session:
            user.dm_chat_id = dm_chat_id
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def get_fsm_state(self, platform: str, external_user_id: int) -> dict | None:
        platform = self._platform(platform)
        async with self.db.session as session:
            stmt = select(User.fsm_state).where(
                User.platform == platform,
                User.tg_user_id == external_user_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def set_fsm_state(
        self, platform: str, external_user_id: int, fsm_state: dict | None
    ) -> None:
        platform = self._platform(platform)
        async with self.db.session as session:
            stmt = select(User).where(
                User.platform == platform,
                User.tg_user_id == external_user_id,
            )
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if user is None:
                return
            user.fsm_state = fsm_state
            session.add(user)
            await session.commit()


class _PlayerAccessor:
    def __init__(self, db: DatabaseAccessor):
        self.db = db

    async def get_by_user_and_game(self, user_id: int, game_id: int) -> Player | None:
        async with self.db.session as session:
            stmt = select(Player).where(
                Player.user_id == user_id, Player.game_id == game_id
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def list_by_game(self, game_id: int) -> list[Player]:
        async with self.db.session as session:
            stmt = select(Player).where(Player.game_id == game_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_active_by_user(self, user_id: int) -> Player | None:
        async with self.db.session as session:
            stmt = (
                select(Player)
                .join(Game, Game.id == Player.game_id)
                .where(
                    Player.user_id == user_id,
                    Player.is_active.is_(True),
                    Game.status == GameStatus.ACTIVE,
                )
                .order_by(Player.joined_at.desc())
            )
            result = await session.execute(stmt)
            return result.scalars().first()

    async def list_by_user(self, user_id: int) -> list[Player]:
        async with self.db.session as session:
            stmt = select(Player).where(Player.user_id == user_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def create(
        self,
        user_id: int,
        game_id: int,
        *,
        initial_balance: float = 1000.0,
        update_mode: str = "server",
    ) -> Player:
        async with self.db.session as session:
            new_player = Player(
                user_id=user_id,
                game_id=game_id,
                balance=initial_balance,
                update_mode=update_mode,
            )
            session.add(new_player)
            await session.commit()
            await session.refresh(new_player)
            return new_player

    async def get_or_create(
        self,
        user_id: int,
        game_id: int,
        *,
        initial_balance: float = 1000.0,
        update_mode: str = "server",
    ) -> Player:
        player = await self.get_by_user_and_game(user_id, game_id)
        if player:
            return player
        return await self.create(
            user_id,
            game_id,
            initial_balance=initial_balance,
            update_mode=update_mode,
        )

    async def save(self, player: Player) -> Player:
        async with self.db.session as session:
            session.add(player)
            await session.commit()
            await session.refresh(player)
            return player

    async def leave(self, player: Player, final_capital: float | None = None) -> Player:
        async with self.db.session as session:
            player.is_active = False
            player.left_at = datetime.now(timezone.utc)
            player.final_capital = final_capital
            session.add(player)
            await session.commit()
            await session.refresh(player)
            return player

    async def remove_from_game(self, user_id: int, game_id: int) -> bool:
        async with self.db.session as session:
            stmt = select(Player).where(
                Player.user_id == user_id,
                Player.game_id == game_id,
            )
            result = await session.execute(stmt)
            player = result.scalar_one_or_none()
            if player is None:
                return False
            await session.delete(player)
            await session.commit()
            return True


class _AchievementStatsAccessor:
    def __init__(self, db: DatabaseAccessor):
        self.db = db

    async def get(self, user_id: int) -> AchievementStats | None:
        async with self.db.session as session:
            stmt = select(AchievementStats).where(AchievementStats.user_id == user_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def create(self, user_id: int) -> AchievementStats:
        async with self.db.session as session:
            stats = AchievementStats(user_id=user_id)
            session.add(stats)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                stmt = select(AchievementStats).where(
                    AchievementStats.user_id == user_id
                )
                result = await session.execute(stmt)
                existing_stats = result.scalar_one_or_none()
                if existing_stats is None:
                    raise
                return existing_stats
            await session.refresh(stats)
            return stats

    async def get_or_create(self, user_id: int) -> AchievementStats:
        stats = await self.get(user_id)
        if stats is not None:
            return stats
        return await self.create(user_id)

    async def save(self, stats: AchievementStats) -> AchievementStats:
        async with self.db.session as session:
            stats.updated_at = datetime.now(timezone.utc)
            session.add(stats)
            await session.commit()
            await session.refresh(stats)
            return stats


class UserAccessor:
    def __init__(self, db: DatabaseAccessor):
        self.user = _UserAccessor(db)
        self.player = _PlayerAccessor(db)
        self.achievement = _AchievementStatsAccessor(db)
