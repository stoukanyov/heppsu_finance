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


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    now = dt.datetime.now(dt.UTC)
    expire = now + dt.timedelta(minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    # `jti` прави всеки токен различен: без него две издавания в една и съща секунда
    # за един потребител дават буквално еднакъв низ и ротацията изглежда като no-op.
    payload = {"sub": subject, "iat": now, "exp": expire, "jti": secrets.token_hex(8)}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Хвърля jwt.PyJWTError при невалиден/изтекъл токен."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


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
