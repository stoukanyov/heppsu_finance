"""SQLAlchemy engine и session фабрика. Един и същ код за SQLite и PostgreSQL."""
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

_connect_args = {"check_same_thread": False} if settings.is_sqlite else {}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)


if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _register_unicode_lower(dbapi_connection, _record) -> None:  # noqa: ANN001
        """Вградените `lower`/`upper` на SQLite знаят само ASCII — кирилицата остава непроменена.

        Заменяме ги с версиите на Python, за да е търсенето без оглед на регистъра
        еднакво в локалната SQLite среда и в PostgreSQL.
        """

        def _lower(value):  # noqa: ANN001, ANN202
            return value.lower() if isinstance(value, str) else value

        def _upper(value):  # noqa: ANN001, ANN202
            return value.upper() if isinstance(value, str) else value

        dbapi_connection.create_function("lower", 1, _lower)
        dbapi_connection.create_function("upper", 1, _upper)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: сесия за заявка, гарантирано затворена накрая."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
