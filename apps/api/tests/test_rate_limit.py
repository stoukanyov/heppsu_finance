"""Тестове за ограничаване на опитите за вход (brute force защита)."""
import time

import pytest

from tests.conftest import register_and_login

GOOD = "supersecret1"
BAD = "грешна-парола"


@pytest.fixture()
def limited():
    """Включва ограничението само за този тест и чисти броячите след него."""
    from app.core.config import settings
    from app.core.rate_limit import reset_all_limiters

    original = (
        settings.RATE_LIMIT_ENABLED,
        settings.LOGIN_RATE_LIMIT_ATTEMPTS,
        settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    )
    settings.RATE_LIMIT_ENABLED = True
    settings.LOGIN_RATE_LIMIT_ATTEMPTS = 5
    settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS = 900
    reset_all_limiters()
    yield settings
    (
        settings.RATE_LIMIT_ENABLED,
        settings.LOGIN_RATE_LIMIT_ATTEMPTS,
        settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    ) = original
    reset_all_limiters()


def _login(client, email: str, password: str):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _register(client, email: str) -> None:
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": GOOD, "full_name": "Тест"},
    )
    assert r.status_code == 201, r.text


def test_sixth_failed_attempt_returns_429(client, limited):
    _register(client, "brute@example.com")

    for _ in range(5):
        assert _login(client, "brute@example.com", BAD).status_code == 401

    r = _login(client, "brute@example.com", BAD)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    assert "опити" in r.json()["detail"]


def test_blocked_even_with_correct_password(client, limited):
    """След изчерпан праг и вярната парола се отказва — иначе няма защита."""
    _register(client, "locked@example.com")
    for _ in range(5):
        _login(client, "locked@example.com", BAD)
    assert _login(client, "locked@example.com", GOOD).status_code == 429


def test_successful_login_resets_counter(client, limited):
    _register(client, "reset@example.com")

    for _ in range(4):
        assert _login(client, "reset@example.com", BAD).status_code == 401
    assert _login(client, "reset@example.com", GOOD).status_code == 200

    # Броячът е нулиран → пак имаме пълните 5 опита.
    for _ in range(5):
        assert _login(client, "reset@example.com", BAD).status_code == 401
    assert _login(client, "reset@example.com", BAD).status_code == 429


def test_other_email_from_same_ip_is_not_blocked(client, limited):
    """Ключът е IP+имейл — блокиран акаунт не заключва колегите зад същия NAT."""
    _register(client, "victim@example.com")
    _register(client, "colleague@example.com")

    for _ in range(6):
        _login(client, "victim@example.com", BAD)
    assert _login(client, "victim@example.com", BAD).status_code == 429

    assert _login(client, "colleague@example.com", BAD).status_code == 401
    assert _login(client, "colleague@example.com", GOOD).status_code == 200


def test_window_expiry_allows_again(client, limited):
    # Кратък прозорец, за да не бави тестовете (bcrypt проверката сама по себе си е бавна).
    limited.LOGIN_RATE_LIMIT_ATTEMPTS = 2
    limited.LOGIN_RATE_LIMIT_WINDOW_SECONDS = 2
    _register(client, "window@example.com")

    for _ in range(2):
        assert _login(client, "window@example.com", BAD).status_code == 401
    assert _login(client, "window@example.com", BAD).status_code == 429

    time.sleep(2.05)  # прозорецът изтича → броячът се изпразва
    assert _login(client, "window@example.com", BAD).status_code == 401


def test_disabled_by_configuration(client, limited):
    """Изключено ограничение → неограничени опити (dev/тестове)."""
    limited.RATE_LIMIT_ENABLED = False
    _register(client, "nolimit@example.com")
    for _ in range(8):
        assert _login(client, "nolimit@example.com", BAD).status_code == 401


def test_separate_ips_are_counted_separately(client, limited):
    """Зад доверен proxy различните клиентски IP-та имат отделни броячи."""
    limited.RATE_LIMIT_TRUST_PROXY_HEADER = True
    try:
        _register(client, "shared@example.com")
        for _ in range(6):
            client.post(
                "/api/v1/auth/login",
                json={"email": "shared@example.com", "password": BAD},
                headers={"X-Forwarded-For": "10.0.0.1"},
            )
        blocked = client.post(
            "/api/v1/auth/login",
            json={"email": "shared@example.com", "password": BAD},
            headers={"X-Forwarded-For": "10.0.0.1"},
        )
        assert blocked.status_code == 429

        other_ip = client.post(
            "/api/v1/auth/login",
            json={"email": "shared@example.com", "password": BAD},
            headers={"X-Forwarded-For": "10.0.0.2"},
        )
        assert other_ip.status_code == 401
    finally:
        limited.RATE_LIMIT_TRUST_PROXY_HEADER = False


def test_existing_flow_still_works(client, limited):
    """Нормалният сценарий (регистрация + вход) не е засегнат."""
    token = register_and_login(client, "normal@example.com")
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
