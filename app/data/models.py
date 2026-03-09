from sqlalchemy import Column, Integer, String, Float, ForeignKey, Enum
from sqlalchemy.ext.declarative import declarative_base
import enum

Base = declarative_base()


class Asset(Base):
    __tablename__ = 'assets'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    sector_id = Column(Integer, ForeignKey('sectors.id'))
    base_volatility = Column(Float, nullable=False)


class Sector(Base):
    __tablename__ = 'sectors'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)


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
    sector_id = Column(Integer, ForeignKey('sectors.id'), nullable=True)
