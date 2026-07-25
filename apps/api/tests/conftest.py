"""Pytest конфигурация: изолирана SQLite база и HTTP клиент.

Env променливите се задават ПРЕДИ импортиране на приложението, за да е сигурно,
че кешираните настройки сочат към тестовата база.
"""
import os
import shutil
import tempfile
from pathlib import Path

import pytest

_DB_PATH = Path(tempfile.gettempdir()) / "aifos_test.db"
_DOCS_DIR = Path(tempfile.gettempdir()) / "aifos_test_docs"
# По подразбиране SQLite (бързо, без зависимости). CI пуска СЪЩИТЕ тестове и срещу
# PostgreSQL с TEST_DATABASE_URL — това е проверката, че кодът е съвместим с
# production базата (типове, ограничения, транзакционен DDL).
_TEST_DB_URL = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_DB_PATH}"
_USING_SQLITE = _TEST_DB_URL.startswith("sqlite")
os.environ["DATABASE_URL"] = _TEST_DB_URL
os.environ["AUTO_CREATE_TABLES"] = "true"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ENVIRONMENT"] = "test"
os.environ["DOCUMENT_STORAGE_DIR"] = str(_DOCS_DIR)
os.environ["AI_PROVIDER"] = "stub"  # детерминиран AI, без мрежа
# Тестовете логват многократно от един и същ „IP“ — ограничението се включва
# точково само в тестовете, които го проверяват (виж tests/test_rate_limit.py).
os.environ["RATE_LIMIT_ENABLED"] = "false"


@pytest.fixture(scope="session", autouse=True)
def _fresh_database():
    # При PostgreSQL схемата се пресъздава от `client` фикстурата — тук няма файл
    # за триене.
    if _USING_SQLITE and _DB_PATH.exists():
        _DB_PATH.unlink()
    shutil.rmtree(_DOCS_DIR, ignore_errors=True)
    yield
    if _USING_SQLITE and _DB_PATH.exists():
        _DB_PATH.unlink()
    shutil.rmtree(_DOCS_DIR, ignore_errors=True)


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.core.database import engine
    from app.db import registry  # noqa: F401 — регистрира моделите
    from app.db.base import Base
    from app.main import app

    # Чиста схема преди всеки тест → пълна изолация между тестовете.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestClient(app) as test_client:
        yield test_client


def register_and_login(client, email: str, password: str = "supersecret1") -> str:
    """Помощна функция: регистрира потребител и връща access token."""
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Тест"},
    )
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]
