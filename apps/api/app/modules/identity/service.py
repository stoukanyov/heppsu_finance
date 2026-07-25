"""Бизнес логика за Identity: регистрация, автентикация и refresh токени."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.modules.identity.models import RefreshToken, RevokeReason, User
from app.modules.identity.schemas import Token, UserCreate

# Съобщенията са нарочно еднакви за „няма такъв токен“ и „токенът е отменен“ —
# нападателят не бива да научава дали е познал съществуващ токен.
_INVALID_REFRESH = "Невалиден или изтекъл refresh токен. Влезте отново."
_REUSE_DETECTED = (
    "Този refresh токен вече е използван. От съображения за сигурност всички сесии "
    "на този потребител са прекратени — влезте отново с имейл и парола."
)


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower()))


def create_user(db: Session, data: UserCreate) -> User:
    user = User(
        email=data.email.lower(),
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


# ============================ Refresh токени ============================
def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    """SQLite връща datetime без часова зона — приемаме, че е UTC.

    Без това сравнението „изтекъл ли е“ би хвърляло TypeError при SQLite и би
    работило само при PostgreSQL, тоест грешката щеше да излезе чак в production.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def _clip(value: str | None, length: int) -> str | None:
    """Реже диагностичните полета до дължината на колоната (празното е None)."""
    text = (value or "").strip()
    return text[:length] or None


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=message,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _access_token_ttl_seconds() -> int:
    return settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def revoke_family(
    db: Session, family_id: uuid.UUID, reason: RevokeReason, *, commit: bool = True
) -> int:
    """Отменя всички още валидни токени от едно семейство. Връща броя им."""
    now = _now()
    result = db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason=reason.value)
    )
    if commit:
        db.commit()
    return int(result.rowcount or 0)


def revoke_all_for_user(
    db: Session, user_id: uuid.UUID, reason: RevokeReason = RevokeReason.USER_REVOKED
) -> int:
    """Отменя всички активни refresh токени на потребителя (изход от всички устройства)."""
    now = _now()
    result = db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason=reason.value)
    )
    db.commit()
    return int(result.rowcount or 0)


def _create_refresh_token(
    db: Session,
    user: User,
    *,
    family_id: uuid.UUID | None = None,
    parent: RefreshToken | None = None,
    user_agent: str | None = None,
    client_ip: str | None = None,
) -> tuple[RefreshToken, str]:
    """Създава нов запис + връща токена в чист вид (единственият момент, в който го знаем)."""
    raw = generate_refresh_token()
    row = RefreshToken(
        id=uuid.uuid4(),
        token_hash=hash_refresh_token(raw),
        user_id=user.id,
        parent_id=parent.id if parent is not None else None,
        expires_at=_now() + dt.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        user_agent=_clip(user_agent, 255),
        client_ip=_clip(client_ip, 45),
    )
    # Първият токен от веригата е самият корен на семейството.
    row.family_id = family_id or row.id
    db.add(row)
    return row, raw


def issue_token_pair(
    db: Session,
    user: User,
    *,
    user_agent: str | None = None,
    client_ip: str | None = None,
) -> Token:
    """Издава нова двойка при успешен вход — ново семейство refresh токени."""
    _, raw = _create_refresh_token(db, user, user_agent=user_agent, client_ip=client_ip)
    db.commit()
    return Token(
        access_token=create_access_token(subject=str(user.id)),
        refresh_token=raw,
        expires_in=_access_token_ttl_seconds(),
    )


def get_refresh_token(db: Session, raw_token: str) -> RefreshToken | None:
    """Намира записа по хеша на подадения токен (чистият вид никъде не се пази)."""
    if not raw_token:
        return None
    return db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
    )


def rotate_refresh_token(
    db: Session,
    raw_token: str,
    *,
    user_agent: str | None = None,
    client_ip: str | None = None,
) -> Token:
    """Разменя refresh токен срещу нова двойка. Старият се отменя веднага.

    Откриване на преизползване: ако токенът вече е бил разменен (`used_at`), значи
    двама държат един и същ токен — законният клиент и някой, който го е откраднал.
    Кой от двамата е кой не се знае, затова цялото семейство се отменя и вход става
    само с имейл и парола. Това е стандартната защита при ротация (OAuth 2.1 BCP).
    """
    row = get_refresh_token(db, raw_token)
    if row is None:
        raise _unauthorized(_INVALID_REFRESH)

    if row.used_at is not None:
        # Вече разменен → кражба. Отменяме цялото семейство, включително наследника,
        # който в момента е в ръцете на легитимния клиент.
        revoke_family(db, row.family_id, RevokeReason.REUSE_DETECTED)
        raise _unauthorized(_REUSE_DETECTED)

    if row.revoked_at is not None:
        raise _unauthorized(_INVALID_REFRESH)

    expires_at = _aware(row.expires_at)
    if expires_at is None or expires_at <= _now():
        row.revoked_at = _now()
        row.revoked_reason = RevokeReason.EXPIRED.value
        db.commit()
        raise _unauthorized(_INVALID_REFRESH)

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        revoke_family(db, row.family_id, RevokeReason.USER_REVOKED)
        raise _unauthorized(_INVALID_REFRESH)

    now = _now()
    row.used_at = now
    row.revoked_at = now
    row.revoked_reason = RevokeReason.ROTATED.value
    _, raw = _create_refresh_token(
        db,
        user,
        family_id=row.family_id,
        parent=row,
        user_agent=user_agent or row.user_agent,
        client_ip=client_ip or row.client_ip,
    )
    db.commit()
    return Token(
        access_token=create_access_token(subject=str(user.id)),
        refresh_token=raw,
        expires_in=_access_token_ttl_seconds(),
    )


def logout(db: Session, raw_token: str, *, all_devices: bool = False) -> int:
    """Отменя подадения refresh токен (или всички на потребителя). Връща броя отменени.

    Изходът не издава дали токенът е съществувал: непознат токен просто отменя 0 реда
    и връща 204. Иначе endpoint-ът щеше да е оракул за валидност на токени.
    """
    row = get_refresh_token(db, raw_token)
    if row is None:
        return 0
    if all_devices:
        return revoke_all_for_user(db, row.user_id, RevokeReason.LOGOUT)
    if row.revoked_at is None:
        row.revoked_at = _now()
        row.revoked_reason = RevokeReason.LOGOUT.value
        db.commit()
        return 1
    return 0
