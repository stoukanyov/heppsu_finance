"""Двуфакторна автентикация през HTTP: включване, вход на две стъпки, изключване."""
import time

import pytest
from sqlalchemy import select

from app.core import totp

EMAIL = "dvufaktor@example.com"
PASSWORD = "supersecret1"


def _register(client, email: str = EMAIL) -> None:
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Тест"},
    )
    assert r.status_code == 201, r.text


def _login(client, email: str = EMAIL, password: str = PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _code(secret: str, steps: int = 0) -> str:
    """Кодът за стъпка `steps` спрямо сега (-1 = предишната, +1 = следващата)."""
    return totp.totp(secret, timestamp=time.time() + steps * totp.STEP_SECONDS)


def _away_from_the_step_boundary() -> None:
    """Изчаква, ако 30-секундната стъпка е на свършване.

    Тестовете по-долу смятат „предишна“ и „текуща“ стъпка. Ако границата падне
    между два реда от теста, аритметиката се разминава с една стъпка и тестът
    спира да минава от само себе си — веднъж на всеки няколко десетки пускания.
    """
    left = totp.STEP_SECONDS - (time.time() % totp.STEP_SECONDS)
    if left < 3:
        time.sleep(left + 0.2)


def _forget_last_counter(email: str) -> None:
    """Забравя последния използван брояч — както след ден без влизане.

    Потвърждаването при включването изразходва една стъпка. Без това тестовете
    за прозореца биха мерили точно нея, вместо прозореца.
    """
    from app.core.database import SessionLocal
    from app.modules.identity.models import User, UserTotp

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        row = db.scalar(select(UserTotp).where(UserTotp.user_id == user.id))
        row.last_counter = None
        db.commit()


def _enable(client, email: str = EMAIL) -> tuple[str, str, list[str]]:
    """Регистрира, включва 2FA и връща (access токен, тайна, резервни кодове).

    Потвърждението е с кода от **предишната** стъпка (прозорецът го приема). Така
    текущата стъпка остава неизразходвана и следващите редове на теста могат да
    влязат веднага — иначе всеки тест би чакал 30 секунди, защото потвърденият
    код вече не минава втори път.
    """
    _away_from_the_step_boundary()
    _register(client, email)
    token = _login(client, email).json()["access_token"]

    setup = client.post("/api/v1/auth/2fa/setup", headers=_auth(token))
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]

    confirm = client.post(
        "/api/v1/auth/2fa/confirm",
        json={"code": _code(secret, -1)},
        headers=_auth(token),
    )
    assert confirm.status_code == 200, confirm.text
    return token, secret, confirm.json()["recovery_codes"]


# ------------------------------------------------------------------ включване
def test_status_is_off_for_a_fresh_account(client):
    _register(client)
    token = _login(client).json()["access_token"]
    r = client.get("/api/v1/auth/2fa/status", headers=_auth(token))
    assert r.status_code == 200
    assert r.json() == {"enabled": False, "pending": False, "recovery_codes_left": 0}


def test_setup_returns_secret_uri_and_qr(client):
    _register(client)
    token = _login(client).json()["access_token"]
    r = client.post("/api/v1/auth/2fa/setup", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["secret"]) == 32
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert f"secret={body['secret']}" in body["otpauth_uri"]
    assert body["qr_svg"].startswith("<svg")


def test_unconfirmed_secret_does_not_turn_2fa_on(client):
    """Сканирането е започнато, но не е потвърдено — входът остава едностъпков.

    Иначе всеки, който е затворил екрана по средата, остава заключен навън.
    """
    _register(client)
    token = _login(client).json()["access_token"]
    client.post("/api/v1/auth/2fa/setup", headers=_auth(token))

    status = client.get("/api/v1/auth/2fa/status", headers=_auth(token)).json()
    assert status == {"enabled": False, "pending": True, "recovery_codes_left": 0}
    assert "access_token" in _login(client).json()


def test_confirm_with_wrong_code_does_not_enable(client):
    _register(client)
    token = _login(client).json()["access_token"]
    client.post("/api/v1/auth/2fa/setup", headers=_auth(token))

    r = client.post("/api/v1/auth/2fa/confirm", json={"code": "000000"}, headers=_auth(token))
    assert r.status_code == 400
    assert not client.get("/api/v1/auth/2fa/status", headers=_auth(token)).json()["enabled"]


def test_confirm_enables_and_returns_ten_recovery_codes(client):
    token, _, codes = _enable(client)
    assert len(codes) == 10
    assert len(set(codes)) == 10
    assert all(len(code) == 11 and code[5] == "-" for code in codes)

    status = client.get("/api/v1/auth/2fa/status", headers=_auth(token)).json()
    assert status == {"enabled": True, "pending": False, "recovery_codes_left": 10}


def test_recovery_codes_are_shown_only_once(client):
    """Повторното включване при вече включена 2FA се отказва — кодовете не се преиздават."""
    token, _, _ = _enable(client)
    r = client.post("/api/v1/auth/2fa/setup", headers=_auth(token))
    assert r.status_code == 409
    assert "Изключи" in r.json()["detail"]


def test_second_setup_replaces_an_unconfirmed_secret(client):
    """Нов QR код обезсилва стария: само потвърденият телефон остава."""
    _register(client)
    token = _login(client).json()["access_token"]
    first = client.post("/api/v1/auth/2fa/setup", headers=_auth(token)).json()["secret"]
    second = client.post("/api/v1/auth/2fa/setup", headers=_auth(token)).json()["secret"]
    assert first != second

    r = client.post(
        "/api/v1/auth/2fa/confirm", json={"code": totp.totp(first)}, headers=_auth(token)
    )
    assert r.status_code == 400
    r = client.post(
        "/api/v1/auth/2fa/confirm", json={"code": totp.totp(second)}, headers=_auth(token)
    )
    assert r.status_code == 200


def test_confirm_needs_a_started_setup(client):
    _register(client)
    token = _login(client).json()["access_token"]
    r = client.post("/api/v1/auth/2fa/confirm", json={"code": "123456"}, headers=_auth(token))
    assert r.status_code == 409


def test_2fa_endpoints_require_a_logged_in_user(client):
    for path in ("/api/v1/auth/2fa/setup", "/api/v1/auth/2fa/confirm"):
        assert client.post(path, json={"code": "123456"}).status_code == 401


# ------------------------------------------------------------ вход на две стъпки
def test_login_asks_for_a_code_instead_of_issuing_tokens(client):
    _enable(client)
    body = _login(client).json()
    assert body["mfa_required"] is True
    assert body["mfa_token"]
    assert body["expires_in"] > 0
    # Най-важното: първата стъпка не дава нищо, с което се работи.
    assert "access_token" not in body
    assert "refresh_token" not in body


def test_second_step_issues_the_token_pair(client):
    _, secret, _ = _enable(client)
    challenge = _login(client).json()

    r = client.post(
        "/api/v1/auth/login/2fa",
        json={"mfa_token": challenge["mfa_token"], "code": _code(secret)},
    )
    assert r.status_code == 200, r.text
    tokens = r.json()
    assert tokens["access_token"] and tokens["refresh_token"]

    me = client.get("/api/v1/auth/me", headers=_auth(tokens["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == EMAIL


def test_intermediate_token_is_not_an_access_token(client):
    """Междинното състояние не бива да е годно за нищо друго.

    Ако `typ` не се проверява, междинният токен (също подписан, също с `sub`)
    отваря целия API и вторият фактор става украшение.
    """
    _enable(client)
    mfa_token = _login(client).json()["mfa_token"]

    assert client.get("/api/v1/auth/me", headers=_auth(mfa_token)).status_code == 401
    assert client.get("/api/v1/companies", headers=_auth(mfa_token)).status_code == 401
    assert client.get("/api/v1/auth/2fa/status", headers=_auth(mfa_token)).status_code == 401


def test_access_token_is_not_accepted_as_an_intermediate_token(client):
    """И обратното: достъпен токен не замества стъпката с паролата."""
    token, secret, _ = _enable(client)
    r = client.post(
        "/api/v1/auth/login/2fa", json={"mfa_token": token, "code": _code(secret)}
    )
    assert r.status_code == 401


def test_second_step_refuses_a_wrong_code(client):
    _enable(client)
    challenge = _login(client).json()
    r = client.post(
        "/api/v1/auth/login/2fa", json={"mfa_token": challenge["mfa_token"], "code": "000000"}
    )
    assert r.status_code == 401
    assert "код" in r.json()["detail"]


def test_wrong_password_never_reaches_the_second_step(client):
    _enable(client)
    r = _login(client, password="грешна")
    assert r.status_code == 401
    assert "mfa_token" not in r.json()


def test_the_same_code_does_not_work_twice(client):
    """Повторно ползване на един и същ код: подслушан код не върши работа."""
    _, secret, _ = _enable(client)
    code = _code(secret)

    first = client.post(
        "/api/v1/auth/login/2fa", json={"mfa_token": _login(client).json()["mfa_token"], "code": code}
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/auth/login/2fa", json={"mfa_token": _login(client).json()["mfa_token"], "code": code}
    )
    assert second.status_code == 401


def test_code_from_the_previous_step_is_accepted(client):
    """Прозорецът за часовата разлика е ±1 стъпка — иначе телефоните не влизат."""
    _, secret, _ = _enable(client)
    _forget_last_counter(EMAIL)
    _away_from_the_step_boundary()
    r = client.post(
        "/api/v1/auth/login/2fa",
        json={"mfa_token": _login(client).json()["mfa_token"], "code": _code(secret, -1)},
    )
    assert r.status_code == 200, r.text


def test_code_from_two_steps_back_is_refused(client):
    _, secret, _ = _enable(client)
    _forget_last_counter(EMAIL)
    _away_from_the_step_boundary()
    stale = _code(secret, -2)
    r = client.post(
        "/api/v1/auth/login/2fa",
        json={"mfa_token": _login(client).json()["mfa_token"], "code": stale},
    )
    assert r.status_code == 401


def test_older_code_is_refused_after_a_newer_one_was_used(client):
    """Приет по-нов брояч заключва целия прозорец назад."""
    _, secret, _ = _enable(client)
    _forget_last_counter(EMAIL)
    _away_from_the_step_boundary()
    earlier, current = _code(secret, -1), _code(secret)

    ok = client.post(
        "/api/v1/auth/login/2fa",
        json={"mfa_token": _login(client).json()["mfa_token"], "code": current},
    )
    assert ok.status_code == 200
    again = client.post(
        "/api/v1/auth/login/2fa",
        json={"mfa_token": _login(client).json()["mfa_token"], "code": earlier},
    )
    assert again.status_code == 401


@pytest.mark.parametrize("bad", ["не-е-токен", "", "a.b.c"])
def test_garbage_intermediate_token_is_refused(client, bad):
    _, secret, _ = _enable(client)
    r = client.post("/api/v1/auth/login/2fa", json={"mfa_token": bad or "x", "code": _code(secret)})
    assert r.status_code == 401


def test_expired_intermediate_token_is_refused(client):
    from app.core.security import create_mfa_challenge_token

    _, secret, _ = _enable(client)
    # Токен, издаден с отрицателен живот — вече изтекъл в момента на създаването.
    token = create_mfa_challenge_token(subject="00000000-0000-0000-0000-000000000001", expires_seconds=-10)
    r = client.post("/api/v1/auth/login/2fa", json={"mfa_token": token, "code": _code(secret)})
    assert r.status_code == 401


# ---------------------------------------------------------------- резервни кодове
def test_recovery_code_works_once(client):
    _, _, codes = _enable(client)
    code = codes[0]

    first = client.post(
        "/api/v1/auth/login/2fa", json={"mfa_token": _login(client).json()["mfa_token"], "code": code}
    )
    assert first.status_code == 200, first.text
    token = first.json()["access_token"]
    assert client.get("/api/v1/auth/2fa/status", headers=_auth(token)).json()[
        "recovery_codes_left"
    ] == 9

    second = client.post(
        "/api/v1/auth/login/2fa", json={"mfa_token": _login(client).json()["mfa_token"], "code": code}
    )
    assert second.status_code == 401


def test_recovery_code_is_case_and_dash_insensitive(client):
    _, _, codes = _enable(client)
    r = client.post(
        "/api/v1/auth/login/2fa",
        json={
            "mfa_token": _login(client).json()["mfa_token"],
            "code": codes[0].lower().replace("-", ""),
        },
    )
    assert r.status_code == 200, r.text


def test_unknown_recovery_code_is_refused(client):
    _enable(client)
    r = client.post(
        "/api/v1/auth/login/2fa",
        json={"mfa_token": _login(client).json()["mfa_token"], "code": "ZZZZZ-ZZZZZ"},
    )
    assert r.status_code == 401


def test_recovery_codes_of_one_user_do_not_work_for_another(client):
    _, _, codes = _enable(client, "parvi@example.com")
    _, secret_two, _ = _enable(client, "vtori@example.com")
    challenge = _login(client, "vtori@example.com").json()
    r = client.post(
        "/api/v1/auth/login/2fa", json={"mfa_token": challenge["mfa_token"], "code": codes[0]}
    )
    assert r.status_code == 401
    # Своят код работи — проверката не е отказала всичко наред.
    ok = client.post(
        "/api/v1/auth/login/2fa",
        json={"mfa_token": _login(client, "vtori@example.com").json()["mfa_token"],
              "code": _code(secret_two)},
    )
    assert ok.status_code == 200


# ------------------------------------------------------------------ изключване
def test_disable_needs_password_and_code(client):
    token, secret, _ = _enable(client)

    wrong_password = client.post(
        "/api/v1/auth/2fa/disable",
        json={"password": "грешна", "code": _code(secret)},
        headers=_auth(token),
    )
    # 400, не 401: заявката е автентикирана, сгрешена е паролата. С 401 уеб клиентът
    # я чете като изтекла сесия и изхвърля човека от приложението (проверено наживо).
    assert wrong_password.status_code == 400
    assert client.get("/api/v1/auth/2fa/status", headers=_auth(token)).json()["enabled"]

    wrong_code = client.post(
        "/api/v1/auth/2fa/disable",
        json={"password": PASSWORD, "code": "000000"},
        headers=_auth(token),
    )
    assert wrong_code.status_code == 400
    assert client.get("/api/v1/auth/2fa/status", headers=_auth(token)).json()["enabled"]


def test_disable_turns_login_back_into_one_step(client):
    token, secret, _ = _enable(client)
    r = client.post(
        "/api/v1/auth/2fa/disable",
        json={"password": PASSWORD, "code": _code(secret)},
        headers=_auth(token),
    )
    assert r.status_code == 204, r.text

    status = client.get("/api/v1/auth/2fa/status", headers=_auth(token)).json()
    assert status == {"enabled": False, "pending": False, "recovery_codes_left": 0}
    assert "access_token" in _login(client).json()


def test_disable_with_a_recovery_code_is_allowed(client):
    """Изгубен телефон: резервният код служи и за изключване."""
    token, _, codes = _enable(client)
    r = client.post(
        "/api/v1/auth/2fa/disable",
        json={"password": PASSWORD, "code": codes[0]},
        headers=_auth(token),
    )
    assert r.status_code == 204, r.text


def test_disabling_removes_the_recovery_codes(client):
    """Нов цикъл на включване не бива да приема стари кодове."""
    token, secret, codes = _enable(client)
    client.post(
        "/api/v1/auth/2fa/disable",
        json={"password": PASSWORD, "code": _code(secret)},
        headers=_auth(token),
    )
    new_setup = client.post("/api/v1/auth/2fa/setup", headers=_auth(token)).json()
    client.post(
        "/api/v1/auth/2fa/confirm",
        json={"code": _code(new_setup["secret"], -1)},
        headers=_auth(token),
    )
    r = client.post(
        "/api/v1/auth/login/2fa",
        json={"mfa_token": _login(client).json()["mfa_token"], "code": codes[0]},
    )
    assert r.status_code == 401


def test_disable_on_an_account_without_2fa_is_409(client):
    _register(client)
    token = _login(client).json()["access_token"]
    r = client.post(
        "/api/v1/auth/2fa/disable",
        json={"password": PASSWORD, "code": "123456"},
        headers=_auth(token),
    )
    assert r.status_code == 409


def test_intermediate_token_stops_working_after_2fa_is_disabled(client):
    token, secret, _ = _enable(client)
    challenge = _login(client).json()
    client.post(
        "/api/v1/auth/2fa/disable",
        json={"password": PASSWORD, "code": _code(secret)},
        headers=_auth(token),
    )
    r = client.post(
        "/api/v1/auth/login/2fa", json={"mfa_token": challenge["mfa_token"], "code": "123456"}
    )
    assert r.status_code == 401


# ---------------------------------------------- ограничаване на опитите за кода
def _bad_code(client) -> int:
    """Един опит с грешен код през пълната първа стъпка. Връща кода на отговора."""
    challenge = _login(client)
    if challenge.status_code != 200:
        return challenge.status_code
    return client.post(
        "/api/v1/auth/login/2fa",
        json={"mfa_token": challenge.json()["mfa_token"], "code": "000000"},
    ).status_code


def test_wrong_codes_hit_the_same_counter_as_wrong_passwords(client, limited):
    """Кодът минава през брояча на входа, не през свой.

    Отделен брояч би дал на налучкването на 6 цифри втора пълна квота — тоест
    двойно повече опити, отколкото пази паролата.
    """
    _enable(client)
    for _ in range(limited.LOGIN_RATE_LIMIT_ATTEMPTS):
        assert _bad_code(client) == 401
    assert _bad_code(client) == 429


def test_failed_password_and_failed_code_add_up(client, limited):
    """Три сгрешени пароли и два сгрешени кода изчерпват същите пет опита."""
    _enable(client)
    for _ in range(3):
        assert _login(client, password="грешна").status_code == 401
    for _ in range(2):
        assert _bad_code(client) == 401
    assert _bad_code(client) == 429


def test_a_correct_password_does_not_reset_the_counter_for_the_code(client, limited):
    """Иначе налучкването на кода е безкрайно.

    Нападател, който знае паролата, би изчиствал наказанието си с нов
    `/auth/login` след всеки пети сгрешен код. Затова броячът се нулира чак
    когато бъдат издадени истински токени.
    """
    _enable(client)
    for _ in range(limited.LOGIN_RATE_LIMIT_ATTEMPTS):
        assert _bad_code(client) == 401

    # Паролата е вярна и първата стъпка минава — но квотата е изчерпана.
    assert _bad_code(client) == 429


def test_the_counter_clears_after_a_successful_second_step(client, limited):
    """Истинският вход освобождава потребителя — иначе сгрешен код го заключва."""
    _, secret, _ = _enable(client)
    for _ in range(limited.LOGIN_RATE_LIMIT_ATTEMPTS - 1):
        assert _bad_code(client) == 401

    ok = client.post(
        "/api/v1/auth/login/2fa",
        json={"mfa_token": _login(client).json()["mfa_token"], "code": _code(secret)},
    )
    assert ok.status_code == 200, ok.text
    # След нулирането има нова пълна квота.
    assert _bad_code(client) == 401
