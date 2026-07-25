"""Alembic environment — ползва app settings и метаданните на всички модели."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app.core.config import settings
from app.db import registry  # noqa: F401 — регистрира всички модели в metadata
from app.db.base import Base

config = context.config
if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:  # pragma: no cover — логването е незадължително
        pass

target_metadata = Base.metadata


def _url() -> str:
    return settings.DATABASE_URL


def _is_sqlite() -> bool:
    return _url().startswith("sqlite")


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=_is_sqlite(),
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connect_args = {"check_same_thread": False} if _is_sqlite() else {}
    engine = create_engine(_url(), connect_args=connect_args)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=_is_sqlite(),
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
