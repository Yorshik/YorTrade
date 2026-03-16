from sqlalchemy import Column, Integer, Float, ForeignKey, DateTime, Enum, JSON, BigInteger, String
from sqlalchemy.sql import func
import enum

from app.store.database.base import Base


class GameStatus(enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    FINISHED = "finished"


class Game(Base):
    __tablename__ = 'games'
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False)
    host_id = Column(BigInteger, nullable=False)
    platform = Column(String, nullable=False, default="TG")
    status = Column(Enum(GameStatus), nullable=False, default=GameStatus.PENDING)
    settings = Column(JSON, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)


class GameAsset(Base):
    __tablename__ = 'game_assets'
    game_id = Column(Integer, ForeignKey('games.id'), primary_key=True)
    asset_id = Column(Integer, ForeignKey('assets.id'), primary_key=True)
    start_price = Column(Float, nullable=False)
    volatility = Column(Float, nullable=False)
    shares_total = Column(Integer, nullable=False, default=1000)
    shares_available = Column(Integer, nullable=False, default=1000)


class Portfolio(Base):
    __tablename__ = 'portfolios'
    player_id = Column(Integer, ForeignKey('players.id'), primary_key=True)
    asset_id = Column(Integer, ForeignKey('assets.id'), primary_key=True)
    amount = Column(Integer, nullable=False, default=0)


class DealType(enum.Enum):
    BUY = "buy"
    SELL = "sell"


class Deal(Base):
    __tablename__ = 'deals'
    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey('players.id'), nullable=False)
    game_id = Column(Integer, ForeignKey('games.id'), nullable=False)
    asset_id = Column(Integer, ForeignKey('assets.id'), nullable=False)
    type = Column(Enum(DealType), nullable=False)
    amount = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
