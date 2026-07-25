"""API рутер за автентикация и потребители."""
from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.core.security import create_access_token
from app.modules.identity import service
from app.modules.identity.schemas import LoginRequest, Token, UserCreate, UserOut

router = APIRouter(tags=["identity"])


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
def login(data: LoginRequest, db: DbSession) -> Token:
    user = service.authenticate(db, data.email, data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Грешен имейл или парола",
        )
    return Token(access_token=create_access_token(subject=str(user.id)))


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
