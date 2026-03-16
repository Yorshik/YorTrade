from sqlalchemy import Column, Enum, Float, ForeignKey, Integer, String
import enum

from app.store.database.base import Base


class Asset(Base):
    __tablename__ = 'assets'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    base_volatility = Column(Float, nullable=False)


class PhraseType(enum.Enum):
    GROWTH = "growth"
    STABLE = "stable"
    FALL = "fall"


class Phrase(Base):
    __tablename__ = 'phrases'
    id = Column(Integer, primary_key=True)
    type = Column(Enum(PhraseType), nullable=False)
    phrase = Column(String, nullable=False)
    asset_id = Column(Integer, ForeignKey('assets.id'), nullable=True)
