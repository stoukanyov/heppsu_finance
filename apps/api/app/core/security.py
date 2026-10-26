"""Хеширане на пароли (bcrypt), JWT access tokens (PyJWT) и refresh токени."""
import datetime as dt
import hashlib
import hmac
import secrets

import bcrypt
import jwt

from app.core.config import settings

# bcrypt приема максимум 72 байта; отрязваме безопасно, за да няма ValueError.
_BCRYPT_MAX_BYTES = 72


def _truncate(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_truncate(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_truncate(password), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- видове токени
# Всеки подписан токен носи `typ`. Без това полe междинният токен от първата
# стъпка на двуфакторния вход (той също е подписан и също носи `sub`) би минал
# навсякъде, където се чака access токен — тоест паролата сама би отваряла целия
# API, а вторият фактор щеше да е украшение. Виж `decode_access_token`.
ACCESS_TOKEN_TYPE = "access"
MFA_TOKEN_TYPE = "mfa"


def _encode(payload: dict) -> str:
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _base_payload(subject: str, expires_in: dt.timedelta, token_type: str) -> dict:
    now = dt.datetime.now(dt.UTC)
    # `jti` прави всеки токен различен: без него две издавания в една и съща секунда
    # за един потребител дават буквално еднакъв низ и ротацията изглежда като no-op.
    return {
        "sub": subject,
        "iat": now,
        "exp": now + expires_in,
        "jti": secrets.token_hex(8),
        "typ": token_type,
    }


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    minutes = expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    return _encode(_base_payload(subject, dt.timedelta(minutes=minutes), ACCESS_TOKEN_TYPE))


def create_mfa_challenge_token(subject: str, expires_seconds: int) -> str:
    """Междинен токен между паролата и кода — не отваря нито една крайна точка.

    Кратък живот и собствен `typ`; единственото място, което го приема, е
    `/auth/login/2fa`. Състоянието е в самия токен, защото няма какво да се пази
    на сървъра: кодът така или иначе е еднократен (виж `core.totp`).
    """
    return _encode(_base_payload(subject, dt.timedelta(seconds=expires_seconds), MFA_TOKEN_TYPE))


def _decode(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def decode_access_token(token: str) -> dict:
    """Хвърля jwt.PyJWTError при невалиден/изтекъл токен или **чужд вид** токен.

    Липсващ `typ` се приема за access: токените, издадени преди въвеждането на
    полето, не бива да изхвърлят хората при обновяване на сървъра.
    """
    payload = _decode(token)
    token_type = payload.get("typ", ACCESS_TOKEN_TYPE)
    if token_type != ACCESS_TOKEN_TYPE:
        raise jwt.InvalidTokenError(f"очакван access токен, получен '{token_type}'")
    return payload


def decode_mfa_challenge_token(token: str) -> dict:
    """Чете междинния токен. Access токен тук се отказва — и обратното."""
    payload = _decode(token)
    if payload.get("typ") != MFA_TOKEN_TYPE:
        raise jwt.InvalidTokenError("очакван междинен токен за втори фактор")
    return payload


# ---------------------------------------------------------------- refresh токени
# Refresh токенът НЕ е JWT: той е непрозрачен случаен низ, чиято единствена истина е
# редът в базата. Така отмяната е незабавна — за разлика от подписан токен, който важи
# до изтичането си, каквото и да реши сървърът.
REFRESH_TOKEN_BYTES = 48  # 384 бита ентропия → 64 символа base64url


def generate_refresh_token() -> str:
    """Нов непрозрачен refresh токен (криптографски случаен)."""
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    """SHA-256 хеш на refresh токена — в базата се пази само той.

    Тук нарочно НЕ ползваме bcrypt: за разлика от паролата, токенът е с 384 бита
    ентропия и подбирането му е невъзможно, а bcrypt би направил всяка заявка към
    `/auth/refresh` скъпа. Освен това хешът е детерминиран, което позволява
    търсене по индексирана колона вместо обхождане на всички редове.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_tokens_match(raw_token: str, stored_hash: str) -> bool:
    """Сравнение в константно време (защита срещу timing атаки)."""
    return hmac.compare_digest(hash_refresh_token(raw_token), stored_hash)


# ------------------------------------------------------------- резервни кодове
# Резервният код замества TOTP кода, когато телефонът е изгубен. Азбуката е без
# 0/O/1/I/L — кодът се чете от екран и се препечатва на ръка.
RECOVERY_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
RECOVERY_CODE_LENGTH = 10


def generate_recovery_code() -> str:
    """Нов резервен код, показан като `XXXXX-XXXXX` (около 50 бита ентропия)."""
    raw = "".join(secrets.choice(RECOVERY_CODE_ALPHABET) for _ in range(RECOVERY_CODE_LENGTH))
    half = RECOVERY_CODE_LENGTH // 2
    return f"{raw[:half]}-{raw[half:]}"


def normalize_recovery_code(code: str) -> str:
    """Горен регистър без тирета и интервали — така, както се пази в базата."""
    return "".join(ch for ch in (code or "").upper() if ch in RECOVERY_CODE_ALPHABET)


def hash_recovery_code(code: str) -> str:
    """SHA-256 на нормализирания код.

    Както при refresh токените, bcrypt тук е излишен: кодът е случаен с ~50 бита
    ентропия, не е избран от човек, и подбирането му е невъзможно през мрежа —
    още по-малко през брояча на неуспешните опити. Детерминираният хеш пък
    позволява търсене по индекс вместо сверяване срещу всеки ред на потребителя.
    """
    return hashlib.sha256(normalize_recovery_code(code).encode("utf-8")).hexdigest()
