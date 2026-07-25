"""SQLAlchemy engine и session фабрика. Един и същ код за SQLite и PostgreSQL."""
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

_connect_args = {"check_same_thread": False} if settings.is_sqlite else {}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: сесия за заявка, гарантирано затворена накрая."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
