"""Тестове за refresh токените: ротация, отмяна и откриване на преизползване."""
import datetime as dt

AUTH = "/api/v1/auth"
PASSWORD = "supersecret1"


def _register(client, email: str) -> None:
    r = client.post(
        f"{AUTH}/register",
        json={"email": email, "password": PASSWORD, "full_name": "Иван Тестов"},
    )
    assert r.status_code == 201, r.text


def _login(client, email: str) -> dict:
    r = client.post(f"{AUTH}/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()


def _new_user(client, email: str) -> dict:
    _register(client, email)
    return _login(client, email)


def _refresh(client, refresh_token: str):
    return client.post(f"{AUTH}/refresh", json={"refresh_token": refresh_token})


def _me(client, access_token: str):
    return client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {access_token}"})


def _rows(user_email: str) -> list:
    """Записите за refresh токени на потребителя, подредени по веригата на ротация.

    Подредбата е по `parent_id`, а не по `created_at`: CURRENT_TIMESTAMP на SQLite е с
    точност до секунда и няколко ротации в един тест получават еднакъв час.
    """
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.modules.identity.models import RefreshToken, User

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == user_email))
        assert user is not None
        rows = list(db.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id)))

    child_of = {row.parent_id: row for row in rows}
    ordered: list = []
    node = child_of.get(None)
    while node is not None:
        ordered.append(node)
        node = child_of.get(node.id)
    # При няколко семейства (вход от две устройства) веригата не е една — връщаме както е.
    return ordered if len(ordered) == len(rows) else rows


# ============================ Формат на отговора ============================
def test_login_returns_both_tokens_in_expected_shape(client):
    """Мобилният клиент чака точно тези имена на полета."""
    body = _new_user(client, "pair@example.com")

    assert set(body) == {"access_token", "refresh_token", "token_type", "expires_in"}
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]

    from app.core.config import settings

    assert body["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def test_login_still_returns_working_access_token(client):
    """Обратна съвместимост: уебът и старите тестове четат само `access_token`."""
    body = _new_user(client, "compat@example.com")
    r = _me(client, body["access_token"])
    assert r.status_code == 200
    assert r.json()["email"] == "compat@example.com"


def test_refresh_token_is_opaque_not_jwt(client):
    """Refresh токенът не е JWT — не носи никакви твърдения в себе си."""
    import jwt

    body = _new_user(client, "opaque@example.com")
    assert body["refresh_token"].count(".") == 0
    try:
        jwt.decode(body["refresh_token"], options={"verify_signature": False})
    except jwt.PyJWTError:
        pass
    else:  # pragma: no cover — би значело, че сме издали JWT
        raise AssertionError("refresh токенът не бива да е JWT")


def test_refresh_token_is_stored_only_as_hash(client):
    """В базата няма и следа от чистия вид на токена."""
    from app.core.security import hash_refresh_token

    body = _new_user(client, "hashed@example.com")
    rows = _rows("hashed@example.com")

    assert len(rows) == 1
    assert rows[0].token_hash == hash_refresh_token(body["refresh_token"])
    assert body["refresh_token"] not in rows[0].token_hash
    # семейството започва от самия токен, без предшественик
    assert rows[0].family_id == rows[0].id
    assert rows[0].parent_id is None


# ============================ Ротация ============================
def test_refresh_rotates_and_invalidates_the_old_token(client):
    first = _new_user(client, "rotate@example.com")

    r = _refresh(client, first["refresh_token"])
    assert r.status_code == 200, r.text
    second = r.json()

    # нова двойка, различна от старата и по двата токена
    assert second["refresh_token"] != first["refresh_token"]
    assert second["access_token"] != first["access_token"]
    assert _me(client, second["access_token"]).status_code == 200

    # старият refresh вече не работи (преизползване → 401)
    again = _refresh(client, first["refresh_token"])
    assert again.status_code == 401, again.text

    rows = _rows("rotate@example.com")
    assert len(rows) == 2
    old, new = rows
    assert old.used_at is not None and old.revoked_at is not None
    assert new.parent_id == old.id            # връзка към предшественика
    assert new.family_id == old.family_id     # същото семейство


def test_refresh_chain_survives_many_rotations(client):
    """Няколко последователни ротации остават в едно семейство."""
    body = _new_user(client, "chain@example.com")
    token = body["refresh_token"]
    for _ in range(3):
        r = _refresh(client, token)
        assert r.status_code == 200, r.text
        token = r.json()["refresh_token"]

    rows = _rows("chain@example.com")
    assert len(rows) == 4
    assert len({row.family_id for row in rows}) == 1
    # само последният е още активен
    assert [row.revoked_at is None for row in rows] == [False, False, False, True]


# ============================ Откриване на преизползване ============================
def test_reused_refresh_token_revokes_the_whole_family(client):
    """Вече разменен токен = кражба → всички сесии от веригата падат."""
    first = _new_user(client, "stolen@example.com")

    ok = _refresh(client, first["refresh_token"])
    assert ok.status_code == 200
    live = ok.json()["refresh_token"]  # токенът в ръцете на легитимния клиент

    # Нападателят ползва стария (или легитимният клиент е ретрайнал — не знаем кой).
    attack = _refresh(client, first["refresh_token"])
    assert attack.status_code == 401, attack.text
    assert "вече е използван" in attack.json()["detail"]
    assert "всички сесии" in attack.json()["detail"]

    # Валидният до момента наследник също е обезсилен.
    assert _refresh(client, live).status_code == 401

    rows = _rows("stolen@example.com")
    assert all(row.revoked_at is not None for row in rows)
    assert any(row.revoked_reason == "REUSE_DETECTED" for row in rows)


def test_reuse_detection_does_not_touch_other_users(client):
    """Отменя се семейството на жертвата, не сесиите на всички."""
    victim = _new_user(client, "victim@example.com")
    bystander = _new_user(client, "bystander@example.com")

    _refresh(client, victim["refresh_token"])
    assert _refresh(client, victim["refresh_token"]).status_code == 401

    assert _refresh(client, bystander["refresh_token"]).status_code == 200


def test_unknown_refresh_token_is_rejected(client):
    r = _refresh(client, "izmislen-token-koito-nikoga-ne-e-izdavan")
    assert r.status_code == 401
    assert "Невалиден" in r.json()["detail"]


# ============================ Изтичане ============================
def test_expired_refresh_token_is_rejected(client):
    body = _new_user(client, "expired@example.com")

    # „Пренавиваме часовника“ директно в базата — по-честно от monkeypatch на времето.
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.modules.identity.models import RefreshToken

    with SessionLocal() as db:
        row = db.scalar(select(RefreshToken))
        assert row is not None
        row.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
        db.commit()

    r = _refresh(client, body["refresh_token"])
    assert r.status_code == 401, r.text
    assert "Невалиден" in r.json()["detail"]

    rows = _rows("expired@example.com")
    assert rows[0].revoked_reason == "EXPIRED"


# ============================ Изход ============================
def test_logout_revokes_the_refresh_token(client):
    body = _new_user(client, "logout@example.com")

    r = client.post(f"{AUTH}/logout", json={"refresh_token": body["refresh_token"]})
    assert r.status_code == 204, r.text

    assert _refresh(client, body["refresh_token"]).status_code == 401
    assert _rows("logout@example.com")[0].revoked_reason == "LOGOUT"


def test_logout_all_devices_revokes_every_session(client):
    _register(client, "alldev@example.com")
    phone = _login(client, "alldev@example.com")
    laptop = _login(client, "alldev@example.com")
    assert phone["refresh_token"] != laptop["refresh_token"]

    r = client.post(
        f"{AUTH}/logout", json={"refresh_token": phone["refresh_token"], "all_devices": True}
    )
    assert r.status_code == 204, r.text

    assert _refresh(client, phone["refresh_token"]).status_code == 401
    assert _refresh(client, laptop["refresh_token"]).status_code == 401


def test_logout_of_one_device_keeps_the_other(client):
    _register(client, "onedev@example.com")
    phone = _login(client, "onedev@example.com")
    laptop = _login(client, "onedev@example.com")

    assert client.post(
        f"{AUTH}/logout", json={"refresh_token": phone["refresh_token"]}
    ).status_code == 204

    assert _refresh(client, phone["refresh_token"]).status_code == 401
    assert _refresh(client, laptop["refresh_token"]).status_code == 200


def test_logout_with_unknown_token_is_silent(client):
    """Endpoint-ът не бива да издава кои токени съществуват."""
    r = client.post(f"{AUTH}/logout", json={"refresh_token": "nyama-takyv-token"})
    assert r.status_code == 204
