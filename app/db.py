import os
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from app.config import Config

log = logging.getLogger("kazi-q.db")


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = Config.DB_URL
    if url.startswith("sqlite"):
        path = url.replace("sqlite:///", "")
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
    return create_engine(url, echo=False, future=True)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db() -> None:
    """Create tables if they don't exist."""
    from app import models  # noqa: F401  (register models on Base)
    Base.metadata.create_all(engine)
    log.info("database initialized at %s", Config.DB_URL)


def get_session() -> Session:
    """Return a new session. Caller is responsible for closing it."""
    return SessionLocal()