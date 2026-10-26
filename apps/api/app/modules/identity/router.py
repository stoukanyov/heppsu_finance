"""API рутер за автентикация и потребители."""
from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.rate_limit import RateLimitRule, ThrottlePolicy, make_throttle_dependency
from app.modules.identity import service
from app.modules.identity.schemas import (
    LoginRequest,
    LogoutRequest,
    MfaChallenge,
    RefreshRequest,
    Token,
    TotpConfirmRequest,
    TotpDisableRequest,
    TotpRecoveryCodes,
    TotpSetup,
    TotpStatus,
    TwoFactorLoginRequest,
    UserCreate,
    UserOut,
)

router = APIRouter(tags=["identity"])

# Brute force защита за вход. И трите прага са нужни: „IP+имейл" спира обикновеното
# налучкване, „имейл" — същото, разпределено през много адреси, „IP" — spraying на
# една парола срещу много акаунти. Виж `core.rate_limit` за компромисите.
LoginRateLimit = make_throttle_dependency(
    "login",
    lambda: ThrottlePolicy(
        pair=RateLimitRule(
            max_attempts=settings.LOGIN_RATE_LIMIT_ATTEMPTS,
            window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        ),
        subject=RateLimitRule(
            max_attempts=settings.LOGIN_RATE_LIMIT_ACCOUNT_ATTEMPTS,
            window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        ),
        ip=RateLimitRule(
            max_attempts=settings.LOGIN_RATE_LIMIT_IP_ATTEMPTS,
            window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        ),
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


@router.post("/auth/login", response_model=Token | MfaChallenge)
def login(
    data: LoginRequest, db: DbSession, guard: LoginRateLimit, request: Request
) -> Token | MfaChallenge:
    """Издава двойка токени, или — при включена 2FA — иска код (втора стъпка).

    Отговорът е един от двата: `Token` (access + refresh) или `MfaChallenge`
    (`mfa_required: true` + междинен токен). Клиентът различава двата по
    `mfa_required`; стар клиент, който не знае за 2FA, няма да намери
    `access_token` и ще покаже грешка, вместо да реши, че е влязъл.
    """
    # Проверката е преди сверяването на паролата — изчерпаният праг връща 429.
    guard.check(data.email)
    user = service.authenticate(db, data.email, data.password)
    if user is None:
        guard.register_failure(data.email, reason="invalid_credentials")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Грешен имейл или парола",
        )
    if service.totp_enabled(db, user):
        # Броячът НЕ се нулира тук. Вярната парола още не е вход, а нулирането би
        # дало неограничени опити за кода: нападател, който знае паролата, щеше да
        # изчиства наказанието си с нов `/auth/login` след всеки пети сгрешен код.
        return service.mfa_challenge(user)
    guard.reset(data.email)  # успешен вход → броячът се нулира
    user_agent, client_ip = _client_meta(request)
    return service.issue_token_pair(db, user, user_agent=user_agent, client_ip=client_ip)


@router.post("/auth/login/2fa", response_model=Token)
def login_second_factor(
    data: TwoFactorLoginRequest, db: DbSession, guard: LoginRateLimit, request: Request
) -> Token:
    """Втората стъпка: междинен токен + код (TOTP или резервен) → двойка токени.

    Опитите минават през **същия** брояч, с който се пази паролата (scope
    „login“, субект — имейлът). Отделен брояч би дал на налучкването на кода
    пълна собствена квота, тоест 6 цифри срещу 5 опита биха станали 6 цифри
    срещу 10.
    """
    user = service.user_from_mfa_token(db, data.mfa_token)
    guard.check(user.email)
    if not service.verify_second_factor(db, user, data.code):
        guard.register_failure(user.email, reason="invalid_2fa_code")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Грешен или вече използван код.",
        )
    guard.reset(user.email)
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


# ==================== Двуфакторна автентикация ====================
# 2FA е на потребителя, не на дружеството: една сметка е в няколко дружества с
# различни роли, а телефонът е един. Затова тук няма право от RBAC каталога —
# всеки управлява своя втори фактор и нищо повече.
@router.get("/auth/2fa/status", response_model=TotpStatus)
def totp_status(user: CurrentUser, db: DbSession) -> TotpStatus:
    return service.totp_status(db, user)


@router.post("/auth/2fa/setup", response_model=TotpSetup)
def totp_setup(user: CurrentUser, db: DbSession) -> TotpSetup:
    """Издава нова тайна и QR код. Тайната НЕ важи, докато не бъде потвърдена."""
    return service.begin_totp_setup(db, user)


@router.post("/auth/2fa/confirm", response_model=TotpRecoveryCodes)
def totp_confirm(
    data: TotpConfirmRequest, user: CurrentUser, db: DbSession, guard: LoginRateLimit
) -> TotpRecoveryCodes:
    """Потвърждава включването с код от автентикатора и връща резервните кодове.

    Кодовете се виждат **само в този отговор** — в базата остават само хешовете.
    """
    guard.check(user.email)
    try:
        codes = service.confirm_totp_setup(db, user, data.code)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_400_BAD_REQUEST:
            guard.register_failure(user.email, reason="invalid_2fa_setup_code")
        raise
    return TotpRecoveryCodes(recovery_codes=codes)


@router.post("/auth/2fa/disable", status_code=status.HTTP_204_NO_CONTENT)
def totp_disable(
    data: TotpDisableRequest, user: CurrentUser, db: DbSession, guard: LoginRateLimit
) -> Response:
    """Изключва 2FA. Иска парола И текущ код — открадната сесия не е достатъчна."""
    guard.check(user.email)
    try:
        service.disable_totp(db, user, data.password, data.code)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_400_BAD_REQUEST:
            guard.register_failure(user.email, reason="invalid_2fa_disable")
        raise
    guard.reset(user.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
