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
        settings.LOGIN_RATE_LIMIT_ACCOUNT_ATTEMPTS,
        settings.LOGIN_RATE_LIMIT_IP_ATTEMPTS,
    )
    settings.RATE_LIMIT_ENABLED = True
    settings.LOGIN_RATE_LIMIT_ATTEMPTS = 5
    settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS = 900
    # Високо по подразбиране, за да не пречат на тестовете за прага „IP+акаунт“;
    # тестовете, които ги проверяват, ги свалят сами.
    settings.LOGIN_RATE_LIMIT_ACCOUNT_ATTEMPTS = 1000
    settings.LOGIN_RATE_LIMIT_IP_ATTEMPTS = 1000
    reset_all_limiters()
    yield settings
    (
        settings.RATE_LIMIT_ENABLED,
        settings.LOGIN_RATE_LIMIT_ATTEMPTS,
        settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        settings.LOGIN_RATE_LIMIT_ACCOUNT_ATTEMPTS,
        settings.LOGIN_RATE_LIMIT_IP_ATTEMPTS,
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


# --------------------------------------------------------------------------
# Прагове отвъд „IP + акаунт“
# --------------------------------------------------------------------------
def _login_from(client, ip: str, email: str, password: str = BAD, **headers):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers={"X-Real-IP": ip, **headers},
    )


def test_distributed_attack_on_one_account_is_stopped(client, limited):
    """Смяната на IP при всеки опит не дава нова квота — брои се и по акаунт.

    Точно това правеше ботнет атаката безплатна при ключ само „IP+акаунт“.
    """
    limited.RATE_LIMIT_TRUST_PROXY_HEADER = True
    limited.LOGIN_RATE_LIMIT_ACCOUNT_ATTEMPTS = 6
    try:
        _register(client, "distributed@example.com")
        for i in range(6):
            r = _login_from(client, f"10.1.0.{i}", "distributed@example.com")
            assert r.status_code == 401, f"опит {i}: {r.text}"

        # Седмият идва от още непознат адрес и въпреки това е спрян.
        assert _login_from(client, "10.1.0.99", "distributed@example.com").status_code == 429
    finally:
        limited.RATE_LIMIT_TRUST_PROXY_HEADER = False


def test_password_spraying_from_one_ip_is_stopped(client, limited):
    """Една парола срещу много акаунти — прагът „IP+акаунт“ не я вижда изобщо."""
    limited.RATE_LIMIT_TRUST_PROXY_HEADER = True
    limited.LOGIN_RATE_LIMIT_IP_ATTEMPTS = 5
    try:
        for i in range(5):
            r = _login_from(client, "10.2.0.1", f"spray{i}@example.com")
            assert r.status_code == 401, f"опит {i}: {r.text}"

        # Шестият е срещу пореден нов имейл — „IP+акаунт“ е на 1, но IP-то е изчерпано.
        assert _login_from(client, "10.2.0.1", "spray-next@example.com").status_code == 429
        # Друго IP не е засегнато.
        assert _login_from(client, "10.2.0.2", "spray-next@example.com").status_code == 401
    finally:
        limited.RATE_LIMIT_TRUST_PROXY_HEADER = False


def test_spoofed_forwarded_for_does_not_create_a_new_bucket(client, limited):
    """Клиентът не може да си избере брояч, като си подправи X-Forwarded-For.

    nginx слага `$proxy_add_x_forwarded_for`, което **добавя** реалния адрес към
    каквото клиентът е пратил — затова първият елемент е негов. Старият код
    четеше точно него и в production 12 поредни опита минаваха без нито едно 429.
    """
    limited.RATE_LIMIT_TRUST_PROXY_HEADER = True
    try:
        _register(client, "spoof@example.com")
        for i in range(5):
            r = _login_from(
                client, "10.3.0.1", "spoof@example.com", **{"X-Forwarded-For": f"203.0.113.{i}"}
            )
            assert r.status_code == 401

        blocked = _login_from(
            client, "10.3.0.1", "spoof@example.com", **{"X-Forwarded-For": "203.0.113.200"}
        )
        assert blocked.status_code == 429
    finally:
        limited.RATE_LIMIT_TRUST_PROXY_HEADER = False


def test_forwarded_for_uses_the_address_the_proxy_appended(client, limited):
    """Без X-Real-IP се чете ПОСЛЕДНИЯТ елемент — този, който proxy-то е добавило."""
    limited.RATE_LIMIT_TRUST_PROXY_HEADER = True
    try:
        _register(client, "chain@example.com")
        # Клиентът твърди, че идва от 203.0.113.7; proxy-то е добавило 10.4.0.1.
        for _ in range(5):
            r = client.post(
                "/api/v1/auth/login",
                json={"email": "chain@example.com", "password": BAD},
                headers={"X-Forwarded-For": "203.0.113.7, 10.4.0.1"},
            )
            assert r.status_code == 401

        blocked = client.post(
            "/api/v1/auth/login",
            json={"email": "chain@example.com", "password": BAD},
            headers={"X-Forwarded-For": "198.51.100.9, 10.4.0.1"},
        )
        assert blocked.status_code == 429, "смяната на подадения адрес не бива да дава нова квота"
    finally:
        limited.RATE_LIMIT_TRUST_PROXY_HEADER = False


def test_counters_survive_a_new_process(client, limited):
    """Броячите са в базата, не в паметта — рестарт/деплой не ги нулира.

    Проверката е през ново хранилище: така се доказва, че състоянието не живее в
    обекта, а в общата таблица.
    """
    from app.core.rate_limit import ThrottleStore

    _register(client, "restart@example.com")
    for _ in range(5):
        assert _login(client, "restart@example.com", BAD).status_code == 401

    count, _oldest = ThrottleStore().count_since(
        "login", 0.0, client_ip=None, subject="restart@example.com"
    )
    assert count == 5
    assert _login(client, "restart@example.com", BAD).status_code == 429


def test_successful_logins_do_not_refund_the_attackers_ip_quota(client, limited):
    """Успешен вход на жертвата не бива да сваля брояча по IP на нападателя.

    Регресия от ревюто: `reset()` триеше редовете, а те са едни и същи за трите
    прага. Пръскане срещу пет акаунта се нулираше само защото петте жертви после
    са влезли нормално — точно прагът, заради който изобщо съществува.
    """
    limited.RATE_LIMIT_TRUST_PROXY_HEADER = True
    limited.LOGIN_RATE_LIMIT_IP_ATTEMPTS = 5
    try:
        victims = [f"refund{i}@example.com" for i in range(5)]
        for email in victims:
            _register(client, email)

        # Нападателят пръска една парола от един адрес срещу петте акаунта.
        for email in victims:
            assert _login_from(client, "10.7.0.1", email).status_code == 401
        assert _login_from(client, "10.7.0.1", "refund-next@example.com").status_code == 429

        # Всяка жертва влиза нормално от собствения си адрес.
        for i, email in enumerate(victims):
            assert _login_from(client, f"10.7.9.{i}", email, GOOD).status_code == 200

        # Нападателят все още е блокиран — квотата му по IP не е върната.
        assert _login_from(client, "10.7.0.1", "refund-next@example.com").status_code == 429
    finally:
        limited.RATE_LIMIT_TRUST_PROXY_HEADER = False


def test_successful_login_still_frees_the_victim(client, limited):
    """Другата страна на същата монета: маркирането не бива да заключи потребителя."""
    _register(client, "freed@example.com")
    for _ in range(4):
        assert _login(client, "freed@example.com", BAD).status_code == 401
    assert _login(client, "freed@example.com", GOOD).status_code == 200
    # Броячът по акаунт е изчистен → пак има пълните пет опита.
    for _ in range(5):
        assert _login(client, "freed@example.com", BAD).status_code == 401
    assert _login(client, "freed@example.com", BAD).status_code == 429


def test_cleanup_does_not_prune_another_counter(client, limited):
    """Чистенето на един брояч не бива да трие редовете на друг.

    `login` има прозорец 900 с, отчетите за сривове — 3600 с. Изтриване без
    условие по брояч върви с давността на този, който случайно го е задействал,
    и другият лимит тихо се обезсилва.
    """
    import time as _time

    from app.core.rate_limit import ThrottleStore

    store = ThrottleStore()
    now = _time.time()
    with store._session_factory() as db:
        from app.modules.security.models import AuthThrottleEvent

        # Скорошен ред на другия брояч — в неговия прозорец, но извън давността на login.
        db.add(
            AuthThrottleEvent(
                scope="crash-report", client_ip="10.8.0.1", subject="crash", occurred_at=now - 5000
            )
        )
        db.commit()

    # Задействаме чистенето от името на „login" с неговата давност.
    store._last_cleanup["login"] = 0.0
    store.register("login", "10.8.0.1", "cleanup@example.com", retention=3600)

    survived, _ = store.count_since("crash-report", 0.0, client_ip=None, subject=None)
    assert survived == 1, "чистенето на login е изтрило ред на друг брояч"


def test_unknown_email_takes_as_long_as_a_wrong_password(client, limited):
    """Времето на отговора не бива да издава кои имейли съществуват.

    Прагът е широк нарочно — целта е да се хване регресия от рода на „връщаме се
    веднага, ако няма такъв потребител“, която прави разликата десетки пъти,
    а не да се мери микробенчмарк.
    """
    limited.RATE_LIMIT_ENABLED = False
    _register(client, "exists@example.com")

    start = time.perf_counter()
    assert _login(client, "exists@example.com", BAD).status_code == 401
    known = time.perf_counter() - start

    start = time.perf_counter()
    assert _login(client, "no-such-user@example.com", BAD).status_code == 401
    unknown = time.perf_counter() - start

    assert unknown > known / 3, (
        f"непознат имейл отговаря твърде бързо ({unknown:.3f}s срещу {known:.3f}s) — "
        "времето издава кои акаунти съществуват"
    )
