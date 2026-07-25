"""Схемата, която раждат миграциите, а не тази от `create_all`.

Причината този файл да съществува: останалите тестове вдигат базата с
``Base.metadata.create_all`` — тоест от **моделите**. В production схемата идва
от **миграциите**. Двете се разминават тихо и разликата се вижда чак когато
нещо се счупи на сървъра.

Точно това стана с `crash_reports` и `deadline_filings`: моделите носеха
`server_default=func.now()` през `TimestampMixin`, миграциите — не. Локално
всичко минаваше; `POST /mobile/crash` срещу разгърнатата среда връщаше 500.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def migrated_db(tmp_path_factory) -> sqlite3.Connection:
    """Празна база, прекарана през всички миграции.

    Alembic се пуска като отделен процес нарочно: `app.core.config.settings` е
    кеширан (`lru_cache`) от вече импортираното приложение и подмяната на
    `DATABASE_URL` в текущия процес няма да стигне до него.
    """
    path = tmp_path_factory.mktemp("migrations") / "schema.db"

    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{path}",
        "SECRET_KEY": "migration-schema-test",
        "ENVIRONMENT": "test",
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"миграциите не минаха:\n{result.stderr}"

    connection = sqlite3.connect(path)
    yield connection
    connection.close()


def _tables_with(connection: sqlite3.Connection, column: str) -> dict[str, str]:
    """Таблиците, които имат дадена колона → SQL-ът на дефиницията им."""
    rows = connection.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND sql LIKE ?",
        (f"%{column}%",),
    ).fetchall()
    return {name: sql for name, sql in rows if name != "alembic_version"}


@pytest.mark.parametrize("column", ["created_at", "updated_at"])
def test_timestamp_columns_have_a_default(migrated_db, column):
    """`NOT NULL` без стойност по подразбиране = провален INSERT в production.

    Моделите пълнят тези колони със `server_default`; ако миграцията го
    пропусне, на PostgreSQL всеки запис пада, а на dev машината — не.
    """
    missing = []
    for table, sql in _tables_with(migrated_db, column).items():
        for line in sql.splitlines():
            stripped = line.strip()
            if not stripped.startswith(column):
                continue
            if "NOT NULL" in stripped and "DEFAULT" not in stripped:
                missing.append(f"{table}.{column}")
    assert not missing, (
        "колони без стойност по подразбиране: "
        + ", ".join(missing)
        + " — добави server_default в миграцията"
    )


@pytest.mark.parametrize("table", ["crash_reports", "deadline_filings"])
def test_insert_without_timestamps_succeeds(migrated_db, table):
    """Директното възпроизвеждане на дефекта, който мина покрай тестовете.

    Приложението не подава `created_at` — разчита на базата. Ако липсва
    стойност по подразбиране, това е точно заявката, която връща 500.
    """
    columns = migrated_db.execute(f"PRAGMA table_info({table})").fetchall()
    required = {
        name: type_
        for _, name, type_, notnull, default, pk in columns
        if notnull and default is None and not pk
    }
    # Пълним само задължителните колони без стойност по подразбиране;
    # `created_at`/`updated_at` съзнателно се пропускат.
    values = {
        name: 1 if "INT" in type_.upper() else "проба"
        for name, type_ in required.items()
        if name not in ("created_at", "updated_at")
    }
    values["id"] = "00000000-0000-0000-0000-000000000001"

    placeholders = ", ".join("?" for _ in values)
    migrated_db.execute(
        f"INSERT INTO {table} ({', '.join(values)}) VALUES ({placeholders})",
        list(values.values()),
    )

    stored = migrated_db.execute(
        f"SELECT created_at, updated_at FROM {table}"
    ).fetchone()
    assert stored[0] is not None
    assert stored[1] is not None
    migrated_db.rollback()
