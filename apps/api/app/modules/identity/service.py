"""Бизнес логика за Identity: регистрация, автентикация, refresh токени и 2FA."""
from __future__ import annotations

import datetime as dt
import uuid

import jwt
from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core import totp as totp_lib
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_mfa_challenge_token,
    decode_mfa_challenge_token,
    generate_recovery_code,
    generate_refresh_token,
    hash_password,
    hash_recovery_code,
    hash_refresh_token,
    verify_password,
)
from app.modules.identity.models import RefreshToken, RevokeReason, TotpRecoveryCode, User, UserTotp
from app.modules.identity.schemas import MfaChallenge, Token, TotpSetup, TotpStatus, UserCreate

# Съобщенията са нарочно еднакви за „няма такъв токен“ и „токенът е отменен“ —
# нападателят не бива да научава дали е познал съществуващ токен.
_INVALID_REFRESH = "Невалиден или изтекъл refresh токен. Влезте отново."
_REUSE_DETECTED = (
    "Този refresh токен вече е използван. От съображения за сигурност всички сесии "
    "на този потребител са прекратени — влезте отново с имейл и парола."
)


# Хеш на случайна парола, срещу който се сверява при непознат имейл — само за да
# отнеме толкова време, колкото и истинска проверка. Строи се веднъж при импорт и
# затова носи същата цена (rounds), каквато има и всяка реална парола.
_DUMMY_PASSWORD_HASH = hash_password(uuid.uuid4().hex)


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
        # Сверяваме срещу фиктивен хеш, вместо да се върнем веднага. Отговорът е
        # един и същ текст и за непознат имейл, и за грешна парола, но без това
        # *времето* го издава: bcrypt отнема ~100 ms, а ранното връщане — почти
        # нула. Разликата е достатъчна, за да се изброят кои имейли съществуват.
        verify_password(password, _DUMMY_PASSWORD_HASH)
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


# ==================== Двуфакторна автентикация (TOTP) ====================
# Текстовете са еднакви за „грешен TOTP код“ и „грешен резервен код“ — отговорът
# не бива да казва коя от двете азбуки е била разпозната.
_INVALID_CODE = "Грешен или вече използван код."
_MFA_NOT_ENABLED = "Двуфакторната автентикация не е включена за този акаунт."
_MFA_ALREADY_ENABLED = (
    "Двуфакторната автентикация вече е включена. Изключи я, за да свържеш друго устройство."
)
_MFA_SETUP_MISSING = "Няма започнато включване. Започни отначало и сканирай новия QR код."
_MFA_CHALLENGE_INVALID = "Междинната стъпка е изтекла. Влез отново с имейл и парола."


def get_totp(db: Session, user_id: uuid.UUID) -> UserTotp | None:
    return db.scalar(select(UserTotp).where(UserTotp.user_id == user_id))


def totp_enabled(db: Session, user: User) -> bool:
    """Включена ли е 2FA — тоест има ли **потвърдена** тайна.

    Започнатото, но непотвърдено включване нарочно не се брои: иначе човек, който
    е затворил екрана, преди да сканира кода, остава заключен извън акаунта си.
    """
    row = get_totp(db, user.id)
    return row is not None and row.confirmed_at is not None


def _unused_recovery_codes(db: Session, user_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(TotpRecoveryCode)
            .where(TotpRecoveryCode.user_id == user_id, TotpRecoveryCode.used_at.is_(None))
        )
        or 0
    )


def totp_status(db: Session, user: User) -> TotpStatus:
    row = get_totp(db, user.id)
    enabled = row is not None and row.confirmed_at is not None
    return TotpStatus(
        enabled=enabled,
        pending=row is not None and row.confirmed_at is None,
        recovery_codes_left=_unused_recovery_codes(db, user.id) if enabled else 0,
    )


def begin_totp_setup(db: Session, user: User) -> TotpSetup:
    """Издава нова тайна и връща QR кода. Докато не бъде потвърдена, не важи нищо.

    Повторното започване подменя непотвърдената тайна: първият QR код може да е
    останал на екрана на чужд телефон или в изтрит имейл, а потвърждението е
    единственото доказателство кое устройство наистина е в ръцете на човека.
    """
    row = get_totp(db, user.id)
    if row is not None and row.confirmed_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_MFA_ALREADY_ENABLED)

    secret = totp_lib.generate_secret()
    if row is None:
        row = UserTotp(id=uuid.uuid4(), user_id=user.id, secret=secret)
        db.add(row)
    else:
        row.secret = secret
        row.last_counter = None
    db.commit()

    uri = totp_lib.otpauth_uri(secret, account=user.email, issuer=settings.TOTP_ISSUER)
    return TotpSetup(secret=secret, otpauth_uri=uri, qr_svg=totp_lib.qr_svg(uri))


def _issue_recovery_codes(db: Session, user: User) -> list[str]:
    """Нови резервни кодове; старите се изтриват. Чистият вид се връща само тук."""
    db.execute(delete(TotpRecoveryCode).where(TotpRecoveryCode.user_id == user.id))
    codes = [generate_recovery_code() for _ in range(settings.TOTP_RECOVERY_CODE_COUNT)]
    for code in codes:
        db.add(
            TotpRecoveryCode(id=uuid.uuid4(), user_id=user.id, code_hash=hash_recovery_code(code))
        )
    return codes


def confirm_totp_setup(db: Session, user: User, code: str) -> list[str]:
    """Потвърждава включването с истински код и връща резервните кодове.

    Чак тук тайната става активна. Връщаните кодове са единственият им чист вид —
    в базата остават само хешовете.
    """
    row = get_totp(db, user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_MFA_SETUP_MISSING)
    if row.confirmed_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_MFA_ALREADY_ENABLED)

    counter = totp_lib.verify(row.secret, code, window=settings.TOTP_WINDOW_STEPS)
    if counter is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_CODE)

    row.confirmed_at = _now()
    # Кодът от потвърждението е изразходван — същата стъпка не минава втори път.
    row.last_counter = counter
    codes = _issue_recovery_codes(db, user)
    db.commit()
    return codes


def verify_second_factor(db: Session, user: User, code: str) -> bool:
    """Приема TOTP код или неизползван резервен код. Всеки от двата е еднократен.

    Редът на проверките е по дължина на входа, а не „първо едното, после другото“:
    TOTP кодът е 6 цифри, резервният — 10 знака от буквено-цифрова азбука, тоест
    двете не могат да се сбъркат.
    """
    row = get_totp(db, user.id)
    if row is None or row.confirmed_at is None:
        return False

    if len(totp_lib.normalize_code(code)) == totp_lib.DIGITS:
        counter = totp_lib.verify(
            row.secret,
            code,
            window=settings.TOTP_WINDOW_STEPS,
            last_counter=row.last_counter,
        )
        if counter is None:
            return False
        row.last_counter = counter
        db.commit()
        return True

    recovery = db.scalar(
        select(TotpRecoveryCode).where(
            TotpRecoveryCode.user_id == user.id,
            TotpRecoveryCode.code_hash == hash_recovery_code(code),
            TotpRecoveryCode.used_at.is_(None),
        )
    )
    if recovery is None:
        return False
    # Редът не се трие: следата „влизано е с резервен код“ е сигнал за изгубен телефон.
    recovery.used_at = _now()
    db.commit()
    return True


def disable_totp(db: Session, user: User, password: str, code: str) -> None:
    """Изключва 2FA. Иска и парола, и текущ код — открадната сесия не стига.

    Иначе достъпът до вече влязъл браузър би бил достатъчен, за да падне вторият
    фактор, и защитата щеше да важи само до първия отворен таб.
    """
    if not totp_enabled(db, user):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_MFA_NOT_ENABLED)
    if not verify_password(password, user.hashed_password):
        # 400, а не 401: заявката Е автентикирана (валиден access токен), сгрешена е
        # паролата, която се иска втори път за това действие. С 401 клиентът го чете
        # като „сесията изтече" и изхвърля човека от приложението — проверено в
        # браузъра: сгрешена парола в диалога за изключване водеше до изход.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Грешна парола")
    if not verify_second_factor(db, user, code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_INVALID_CODE)

    db.execute(delete(TotpRecoveryCode).where(TotpRecoveryCode.user_id == user.id))
    db.execute(delete(UserTotp).where(UserTotp.user_id == user.id))
    db.commit()


def mfa_challenge(user: User) -> MfaChallenge:
    """Отговорът на първата стъпка: паролата е вярна, чака се код."""
    return MfaChallenge(
        mfa_token=create_mfa_challenge_token(
            subject=str(user.id), expires_seconds=settings.MFA_CHALLENGE_TTL_SECONDS
        ),
        expires_in=settings.MFA_CHALLENGE_TTL_SECONDS,
    )


def user_from_mfa_token(db: Session, raw_token: str) -> User:
    """Потребителят от междинния токен; всичко нередно е 401 с един и същ текст."""
    try:
        payload = decode_mfa_challenge_token(raw_token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise _unauthorized(_MFA_CHALLENGE_INVALID) from None

    user = db.get(User, user_id)
    if user is None or not user.is_active or not totp_enabled(db, user):
        raise _unauthorized(_MFA_CHALLENGE_INVALID)
    return user
