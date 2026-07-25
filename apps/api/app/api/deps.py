"""Общи FastAPI dependencies: текущ потребител и тенант-скоуп (компания + роля)."""
import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.modules.companies.models import Company, Membership
from app.modules.identity.models import User

_bearer = HTTPBearer(auto_error=True)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Невалиден или изтекъл токен",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(credentials.credentials)
        subject = payload.get("sub")
        if subject is None:
            raise cred_exc
        user_id = uuid.UUID(subject)
    except (jwt.PyJWTError, ValueError):
        raise cred_exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise cred_exc
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


class CompanyContext:
    """Резултат от тенант-скоупа: компанията и ролята на текущия потребител в нея."""

    def __init__(self, company: Company, membership: Membership):
        self.company = company
        self.membership = membership
        self.role = membership.role


def get_company_context(
    db: DbSession,
    user: CurrentUser,
    x_company_id: Annotated[uuid.UUID | None, Header(alias="X-Company-Id")] = None,
) -> CompanyContext:
    """Изисква header `X-Company-Id` и проверява членството на потребителя."""
    if x_company_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Липсва header X-Company-Id (изберете активна компания)",
        )
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id, Membership.company_id == x_company_id
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нямате достъп до тази компания",
        )
    company = db.get(Company, x_company_id)
    if company is None or not company.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Компанията не е намерена")
    return CompanyContext(company=company, membership=membership)


CurrentCompany = Annotated[CompanyContext, Depends(get_company_context)]
