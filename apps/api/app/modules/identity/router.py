"""API рутер за автентикация и потребители."""
from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.rate_limit import RateLimitRule, make_rate_limit_dependency
from app.modules.identity import service
from app.modules.identity.schemas import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    Token,
    UserCreate,
    UserOut,
)

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


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    """User-Agent и IP на клиента — само за диагностика при разследване на кражба."""
    return request.headers.get("user-agent"), (request.client.host if request.client else None)


@router.post("/auth/login", response_model=Token)
def login(data: LoginRequest, db: DbSession, guard: LoginRateLimit, request: Request) -> Token:
    """Издава двойка токени: кратък access (JWT) и дълъг refresh (непрозрачен, отменяем)."""
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
    user_agent, client_ip = _client_meta(request)
    return service.issue_token_pair(db, user, user_agent=user_agent, client_ip=client_ip)


@router.post("/auth/refresh", response_model=Token)
def refresh(data: RefreshRequest, db: DbSession, request: Request) -> Token:
    """Разменя refresh токен срещу нова двойка (ротация).

    Старият токен се отменя веднага. Ако пристигне вече разменен токен, това значи, че
    някой го е откраднал — цялото семейство се отменя и отговорът е 401 с обяснение.
    """
    user_agent, client_ip = _client_meta(request)
    return service.rotate_refresh_token(
        db, data.refresh_token, user_agent=user_agent, client_ip=client_ip
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(data: LogoutRequest, db: DbSession) -> Response:
    """Отменя подадения refresh токен (или всички на потребителя при `all_devices`).

    Винаги 204, дори за непознат токен — иначе endpoint-ът би издавал кои токени са
    валидни. Access токенът остава валиден до изтичането си; затова е кратък.
    """
    service.logout(db, data.refresh_token, all_devices=data.all_devices)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
