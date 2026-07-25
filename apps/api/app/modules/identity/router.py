"""API рутер за автентикация и потребители."""
from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.rate_limit import RateLimitRule, make_rate_limit_dependency
from app.core.security import create_access_token
from app.modules.identity import service
from app.modules.identity.schemas import LoginRequest, Token, UserCreate, UserOut

router = APIRouter(tags=["identity"])

# Brute force защита за вход: праг по IP + имейл, конфигурируем през Settings.
LoginRateLimit = make_rate_limit_dependency(
    "login",
    lambda: RateLimitRule(
        max_attempts=settings.LOGIN_RATE_LIMIT_ATTEMPTS,
        window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    ),
)


@router.post("/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate, db: DbSession) -> UserOut:
    if service.get_user_by_email(db, data.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Потребител с този имейл вече съществува",
        )
    user = service.create_user(db, data)
    return UserOut.model_validate(user)


@router.post("/auth/login", response_model=Token)
def login(data: LoginRequest, db: DbSession, guard: LoginRateLimit) -> Token:
    # Проверката е преди сверяването на паролата — изчерпаният праг връща 429.
    guard.check(data.email)
    user = service.authenticate(db, data.email, data.password)
    if user is None:
        guard.register_failure(data.email, reason="invalid_credentials")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Грешен имейл или парола",
        )
    guard.reset(data.email)  # успешен вход → броячът се нулира
    return Token(access_token=create_access_token(subject=str(user.id)))


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
