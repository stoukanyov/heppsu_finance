"""Тестове за мобилния модул: политика за версиите и отчети за сривове."""
import datetime as dt

import pytest

from app.core.config import settings
from app.core.rate_limit import reset_all_limiters
from app.modules.mobile import service
from tests.conftest import register_and_login

RELEASE = "/api/v1/mobile/release"
CRASH = "/api/v1/mobile/crash"


@pytest.fixture(autouse=True)
def _restore_settings():
    """Политиката се чете от Settings — всеки тест я връща както я е заварил."""
    keep = {
        name: getattr(settings, name)
        for name in (
            "MOBILE_MIN_SUPPORTED_VERSION",
            "MOBILE_LATEST_VERSION",
            "MOBILE_IOS_STORE_URL",
            "MOBILE_ANDROID_STORE_URL",
            "MOBILE_UPDATE_MESSAGE",
            "CRASH_REPORTING_ENABLED",
            "RATE_LIMIT_ENABLED",
        )
    }
    reset_all_limiters()
    yield
    for name, value in keep.items():
        setattr(settings, name, value)
    reset_all_limiters()


def _stored_reports() -> list:
    """Записаните доклади — четат се направо от базата.

    През API не става: списъкът иска право `audit.view`, тоест регистриран
    потребител и компания, а половината тук проверяват точно анонимния случай.
    """
    from app.core.database import SessionLocal
    from app.modules.mobile.models import CrashReport

    with SessionLocal() as db:
        return db.query(CrashReport).all()


def _crash_payload(**over) -> dict:
    return {
        "platform": "ios",
        "app_version": "1.0.0",
        "kind": "DART",
        "message": "Изключение при осчетоводяване",
        "stack_trace": "#0 postDocument (package:heppsu/posting.dart:42)",
        "occurred_at": dt.datetime(2026, 7, 25, 10, 0, tzinfo=dt.UTC).isoformat(),
        **over,
    }


# ============================== сравнение на версии ==============================


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.4.12", (1, 4, 12)),
        ("1.4.12+87", (1, 4, 12)),  # номерът на билда не носи съвместимост
        ("2.0", (2, 0)),
        ("v3.1.0", (3, 1, 0)),
        ("", (0,)),
        (None, (0,)),
        ("боклук", (0,)),  # непрочетимото се третира като най-старо
    ],
)
def test_parse_version(raw, expected):
    assert service.parse_version(raw) == expected


def test_versions_of_different_length_compare_correctly():
    """„1.4“ и „1.4.0“ са една и съща версия — иначе клиент би се блокирал сам."""
    settings.MOBILE_MIN_SUPPORTED_VERSION = "1.4.0"
    assert service.release_policy("ios", "1.4").update_required is False


# ============================== политика за версиите ==============================


def test_old_version_is_blocked(client):
    settings.MOBILE_MIN_SUPPORTED_VERSION = "2.0.0"
    settings.MOBILE_IOS_STORE_URL = "https://apps.apple.com/app/id1"
    settings.MOBILE_UPDATE_MESSAGE = "Поправка в изчисляването на ДДС."

    body = client.get(RELEASE, params={"platform": "ios", "version": "1.9.9"}).json()

    assert body["update_required"] is True
    assert body["store_url"] == "https://apps.apple.com/app/id1"
    assert body["message"] == "Поправка в изчисляването на ДДС."


def test_current_version_passes(client):
    settings.MOBILE_MIN_SUPPORTED_VERSION = "2.0.0"
    settings.MOBILE_LATEST_VERSION = "2.0.0"

    body = client.get(RELEASE, params={"platform": "ios", "version": "2.0.0"}).json()

    assert body["update_required"] is False
    assert body["update_available"] is False


def test_newer_release_is_offered_without_blocking(client):
    settings.MOBILE_MIN_SUPPORTED_VERSION = "1.0.0"
    settings.MOBILE_LATEST_VERSION = "2.1.0"

    body = client.get(RELEASE, params={"platform": "android", "version": "2.0.0"}).json()

    assert body["update_required"] is False
    assert body["update_available"] is True


def test_blocked_version_is_not_also_offered(client):
    """При блокиране няма смисъл от втори, по-мек сигнал — иначе UI-ът показва две неща."""
    settings.MOBILE_MIN_SUPPORTED_VERSION = "2.0.0"
    settings.MOBILE_LATEST_VERSION = "2.1.0"

    body = client.get(RELEASE, params={"platform": "ios", "version": "1.0.0"}).json()

    assert body["update_required"] is True
    assert body["update_available"] is False


def test_release_needs_no_authentication(client):
    """Спреният клиент често не може да влезе — точно затова е спрян."""
    assert client.get(RELEASE, params={"platform": "ios", "version": "1.0.0"}).status_code == 200


def test_unknown_platform_is_rejected(client):
    r = client.get(RELEASE, params={"platform": "symbian", "version": "1.0.0"})
    assert r.status_code == 400


def test_no_latest_version_configured_means_no_prompt(client):
    settings.MOBILE_MIN_SUPPORTED_VERSION = "1.0.0"
    settings.MOBILE_LATEST_VERSION = ""

    body = client.get(RELEASE, params={"platform": "ios", "version": "1.0.0"}).json()

    assert body["update_available"] is False
    assert body["latest_version"] is None


# ================================ изчистване на данни ================================


@pytest.mark.parametrize(
    "raw,must_not_contain",
    [
        ("Провал за ivan@example.com", "ivan@example.com"),
        ("Токен eyJhbGciOi.eyJzdWIi.signature изтече", "eyJhbGciOi"),
        ("Превод към BG80BNBG96611020345678 отказан", "BG80BNBG96611020345678"),
        ("ЕГН 8001015555 не е валиден", "8001015555"),
    ],
)
def test_sensitive_data_is_scrubbed(raw, must_not_contain):
    assert must_not_contain not in (service.scrub(raw) or "")


def test_amounts_survive_scrubbing():
    """Сумите са нужни за възпроизвеждане — само дългите номера се крият."""
    assert "1250.40" in (service.scrub("Разлика от 1250.40 лв.") or "")


def test_scrubbing_applies_on_the_server_too(client):
    """Клиентът чисти преди изпращане, но сървърът не разчита на това."""
    r = client.post(
        CRASH,
        json=_crash_payload(message="Грешка за petar@example.com при запис"),
    )
    assert r.status_code == 202
    assert "petar@example.com" not in _stored_reports()[0].message


# ================================ отчети за сривове ================================


def test_crash_is_accepted_without_login(client):
    """Сривът на екрана за вход е точно този, който най-много трябва да се види."""
    r = client.post(CRASH, json=_crash_payload())
    assert r.status_code == 202


def test_same_defect_gets_one_fingerprint():
    """Различни адреси в паметта и различни числа не са различни дефекти."""
    a = service.fingerprint("Null при 0x7f12ab", "#0 post (posting.dart:42)")
    b = service.fingerprint("Null при 0x9911cd", "#0 post (posting.dart:57)")
    assert a == b


def test_different_defects_get_different_fingerprints():
    a = service.fingerprint("Null при запис", "#0 post (posting.dart:42)")
    b = service.fingerprint("Няма мрежа", "#0 upload (queue.dart:11)")
    assert a != b


def test_crash_reporting_can_be_switched_off(client):
    settings.CRASH_REPORTING_ENABLED = False
    r = client.post(CRASH, json=_crash_payload())
    # Не е грешка: клиентът трябва да изхвърли доклада, а не да го повтаря.
    assert r.status_code == 202
    assert r.json()["status"] == "disabled"


def test_anonymous_report_cannot_claim_a_company(client):
    """Иначе всеки без токен би могъл да закача доклади за чужд тенант."""
    token = register_and_login(client, "crash-owner@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post(
        "/api/v1/companies",
        headers=auth,
        json={"name": "Акме ЕООД", "eik": "203123456"},
    ).json()["id"]

    r = client.post(CRASH, json=_crash_payload(), headers={"X-Company-Id": company_id})
    assert r.status_code == 202
    assert _stored_reports()[0].company_id is None


def test_report_with_valid_token_is_linked(client):
    token = register_and_login(client, "crash-linked@example.com")
    r = client.post(
        CRASH,
        json=_crash_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 202
    assert _stored_reports()[0].user_id is not None


def test_broken_token_does_not_lose_the_report(client):
    """Счупената сесия често е самата причина за срива."""
    r = client.post(
        CRASH,
        json=_crash_payload(),
        headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.broken.signature"},
    )
    assert r.status_code == 202


def test_oversized_stack_trace_is_rejected(client):
    r = client.post(CRASH, json=_crash_payload(stack_trace="x" * 20_001))
    assert r.status_code == 422


def test_rate_limit_stops_a_flood(client):
    settings.RATE_LIMIT_ENABLED = True
    reset_all_limiters()
    limit = settings.CRASH_REPORT_RATE_LIMIT

    for _ in range(limit):
        assert client.post(CRASH, json=_crash_payload()).status_code == 202

    r = client.post(CRASH, json=_crash_payload())
    assert r.status_code == 429
    # Съобщението за „неуспешни опити“ тук би било подвеждащо — няма опити.
    assert "неуспешни опити" not in r.json()["detail"]


def test_crash_groups_collapse_repeats(client):
    for i in range(3):
        client.post(CRASH, json=_crash_payload(app_version=f"1.0.{i}"))

    token = register_and_login(client, "crash-admin@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post(
        "/api/v1/companies",
        headers=auth,
        json={"name": "Акме ЕООД", "eik": "203123456"},
    ).json()["id"]

    groups = client.get(
        "/api/v1/mobile/crash-groups",
        headers={**auth, "X-Company-Id": company_id},
    ).json()

    assert len(groups) == 1
    assert groups[0]["count"] == 3
    assert sorted(groups[0]["versions"]) == ["1.0.0", "1.0.1", "1.0.2"]
