import enum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.store.database.base import Base

JSON_RUNTIME = JSON().with_variant(JSONB, "postgresql")


class GameStatus(enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    FINISHED = "finished"


class Game(Base):
    __tablename__ = "games"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False)
    host_id = Column(BigInteger, nullable=False)
    platform = Column(String, nullable=False, default="TG")
    status = Column(Enum(GameStatus), nullable=False, default=GameStatus.PENDING)
    settings = Column(JSON, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)


class GameAsset(Base):
    __tablename__ = "game_assets"
    game_id = Column(Integer, ForeignKey("games.id"), primary_key=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), primary_key=True)
    company_id = Column(String, nullable=True)
    start_price = Column(Float, nullable=False)
    volatility = Column(Float, nullable=False)
    shares_total = Column(Integer, nullable=False, default=1000)
    shares_available = Column(Integer, nullable=False, default=1000)


class Portfolio(Base):
    __tablename__ = "portfolios"
    player_id = Column(Integer, ForeignKey("players.id"), primary_key=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), primary_key=True)
    amount = Column(Integer, nullable=False, default=0)


class DealType(enum.Enum):
    BUY = "buy"
    SELL = "sell"


class Deal(Base):
    __tablename__ = "deals"
    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False)
    type = Column(Enum(DealType), nullable=False)
    amount = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MarketDirection(enum.Enum):
    UP = "up"
    DOWN = "down"


class GameRuntimeState(Base):
    __tablename__ = "game_runtime_state"

    game_id = Column(Integer, ForeignKey("games.id"), primary_key=True)
    state = Column(JSON_RUNTIME, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class Company(Base):
    __tablename__ = "companies"
    game_id = Column(Integer, ForeignKey("games.id"), primary_key=True)
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    current_price = Column(Float, nullable=False)
    volatility = Column(Float, nullable=False)


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    company_id = Column(String, nullable=False)
    tick = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)


class EventTemplate(Base):
    __tablename__ = "event_templates"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=False)
    effects = Column(JSON_RUNTIME, nullable=False, default=dict)
    duration_ticks = Column(Integer, nullable=False)
    image_id = Column(String, nullable=True)


class ActiveEvent(Base):
    __tablename__ = "active_events"

    id = Column(String, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    template_id = Column(String, ForeignKey("event_templates.id"), nullable=False)
    company_id = Column(String, nullable=True)
    strength = Column(Float, nullable=False, default=0.0)
    start_tick = Column(Integer, nullable=False)
    end_tick = Column(Integer, nullable=False)
    meta = Column(JSON_RUNTIME, nullable=False, default=dict)


class News(Base):
    __tablename__ = "news"

    id = Column(String, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    company_id = Column(String, nullable=False)
    direction = Column(Enum(MarketDirection), nullable=False)
    strength = Column(Float, nullable=False)
    tick = Column(Integer, nullable=False)


class InsiderInfo(Base):
    __tablename__ = "insider_info"

    id = Column(String, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    company_id = Column(String, nullable=False)
    direction = Column(Enum(MarketDirection), nullable=False)
    strength = Column(Float, nullable=False)
    target_tick = Column(Integer, nullable=False)
    is_true = Column(Boolean, nullable=False)
