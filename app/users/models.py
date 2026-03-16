from sqlalchemy import JSON, BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.store.database.base import Base


class User(Base):
    __tablename__ = 'users'
    __table_args__ = (
        UniqueConstraint("platform", "tg_user_id", name="uq_users_platform_tg_user_id"),
    )

    id = Column(Integer, primary_key=True)
    platform = Column(String, nullable=False, default="TG")
    tg_user_id = Column(BigInteger, nullable=False)
    username = Column(String, nullable=True)
    dm_chat_id = Column(BigInteger, nullable=True)
    fsm_state = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Player(Base):
    __tablename__ = 'players'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    game_id = Column(Integer, ForeignKey('games.id'), nullable=False)
    balance = Column(Float, nullable=False, default=1000.0)
    is_active = Column(Boolean, nullable=False, default=True)
    update_mode = Column(String, nullable=False, default="server")
    final_capital = Column(Float, nullable=True)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    left_at = Column(DateTime(timezone=True), nullable=True)
