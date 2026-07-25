"""Тестове за fail-fast валидацията на опасна конфигурация (SECRET_KEY, JWT alg)."""
import pytest

from app.core.config import (
    DEFAULT_SECRET_KEY,
    InsecureConfigurationError,
    Settings,
)

STRONG_KEY = "0" * 64  # както го дава `openssl rand -hex 32`


def _settings(**overrides) -> Settings:
    # _env_file=None → тестът не зависи от локален .env файл на машината.
    return Settings(_env_file=None, **overrides)


def test_production_with_default_secret_key_refuses_to_start():
    with pytest.raises(InsecureConfigurationError) as exc:
        _settings(ENVIRONMENT="production", SECRET_KEY=DEFAULT_SECRET_KEY)
    message = str(exc.value)
    assert "SECRET_KEY" in message
    assert "openssl rand -hex 32" in message  # казваме точно какво да се направи
    assert "docs/DEPLOY.md" in message


def test_production_with_empty_secret_key_refuses_to_start():
    with pytest.raises(InsecureConfigurationError):
        _settings(ENVIRONMENT="production", SECRET_KEY="   ")


def test_production_with_short_secret_key_refuses_to_start():
    with pytest.raises(InsecureConfigurationError) as exc:
        _settings(ENVIRONMENT="production", SECRET_KEY="a" * 31)
    assert "къс" in str(exc.value)


@pytest.mark.parametrize("environment", ["production", "PROD", "staging"])
def test_all_production_like_environments_are_strict(environment: str):
    with pytest.raises(InsecureConfigurationError):
        _settings(ENVIRONMENT=environment, SECRET_KEY=DEFAULT_SECRET_KEY)


def test_production_with_strong_secret_key_starts():
    s = _settings(ENVIRONMENT="production", SECRET_KEY=STRONG_KEY)
    assert s.is_production is True
    assert s.SECRET_KEY == STRONG_KEY


@pytest.mark.parametrize("environment", ["local", "development", "test"])
def test_dev_and_test_allow_default_secret_key(environment: str):
    s = _settings(ENVIRONMENT=environment, SECRET_KEY=DEFAULT_SECRET_KEY)
    assert s.is_production is False


def test_short_key_is_allowed_in_dev():
    # В dev късият ключ е неудобство, не риск — не блокираме разработката.
    assert _settings(ENVIRONMENT="local", SECRET_KEY="къс").SECRET_KEY == "къс"


@pytest.mark.parametrize("algorithm", ["none", "None", "RS256", ""])
def test_unsafe_jwt_algorithm_refuses_to_start(algorithm: str):
    with pytest.raises(InsecureConfigurationError) as exc:
        _settings(ENVIRONMENT="local", JWT_ALGORITHM=algorithm)
    assert "JWT_ALGORITHM" in str(exc.value)


def test_hs256_is_accepted():
    assert _settings(ENVIRONMENT="local", JWT_ALGORITHM="HS256").JWT_ALGORITHM == "HS256"


def test_decode_passes_algorithms_explicitly():
    """`alg=none` от токена не се приема — алгоритъмът идва от конфигурацията."""
    import jwt

    from app.core.security import create_access_token, decode_access_token

    token = create_access_token(subject="42")
    assert decode_access_token(token)["sub"] == "42"

    forged = jwt.encode({"sub": "42"}, key="", algorithm="none")
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(forged)
