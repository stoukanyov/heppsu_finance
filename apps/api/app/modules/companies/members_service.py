"""Бизнес логика за членства в компания (екип, роли, RBAC)."""
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.companies.models import CompanyRole, Membership
from app.modules.identity import service as identity_service
from app.modules.identity.models import User

# Роли, които могат да управляват членства.
_MANAGER_ROLES = {CompanyRole.OWNER, CompanyRole.SYS_ADMIN}


def _err(msg: str, code: int) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


def require_manage(role: CompanyRole) -> None:
    if role not in _MANAGER_ROLES:
        raise _err("Само собственик или системен администратор управлява членства", status.HTTP_403_FORBIDDEN)


def _owner_count(db: Session, company_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count()).select_from(Membership).where(
            Membership.company_id == company_id, Membership.role == CompanyRole.OWNER
        )
    ) or 0


def list_members(db: Session, company_id: uuid.UUID) -> list[dict]:
    from app.modules.rbac.models import Role

    rows = db.execute(
        select(Membership, User).join(User, User.id == Membership.user_id)
        .where(Membership.company_id == company_id)
        .order_by(User.email)
    ).all()
    role_names = {
        r.id: r.name
        for r in db.scalars(select(Role).where(Role.company_id == company_id))
    }
    return [
        {"id": m.id, "user_id": u.id, "email": u.email, "full_name": u.full_name,
         "role": m.role, "role_id": m.role_id, "role_name": role_names.get(m.role_id)}
        for m, u in rows
    ]


def add_member(db: Session, company_id: uuid.UUID, email: str, role: CompanyRole) -> dict:
    user = identity_service.get_user_by_email(db, email)
    if user is None:
        raise _err("Потребител с този имейл трябва първо да се регистрира", status.HTTP_404_NOT_FOUND)
    existing = db.scalar(
        select(Membership).where(Membership.company_id == company_id, Membership.user_id == user.id)
    )
    if existing is not None:
        raise _err("Потребителят вече е член на компанията", status.HTTP_409_CONFLICT)
    membership = Membership(user_id=user.id, company_id=company_id, role=role)
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return {"id": membership.id, "user_id": user.id, "email": user.email, "full_name": user.full_name, "role": role}


def _get_membership(db: Session, company_id: uuid.UUID, membership_id: uuid.UUID) -> Membership:
    m = db.get(Membership, membership_id)
    if m is None or m.company_id != company_id:
        raise _err("Членството не е намерено", status.HTTP_404_NOT_FOUND)
    return m


def update_role(db: Session, company_id: uuid.UUID, membership_id: uuid.UUID, role: CompanyRole) -> dict:
    m = _get_membership(db, company_id, membership_id)
    if m.role == CompanyRole.OWNER and role != CompanyRole.OWNER and _owner_count(db, company_id) <= 1:
        raise _err("Не може да се премахне последният собственик", status.HTTP_409_CONFLICT)
    m.role = role
    db.commit()
    user = db.get(User, m.user_id)
    return {"id": m.id, "user_id": user.id, "email": user.email, "full_name": user.full_name, "role": role}


def remove_member(db: Session, company_id: uuid.UUID, membership_id: uuid.UUID) -> None:
    m = _get_membership(db, company_id, membership_id)
    if m.role == CompanyRole.OWNER and _owner_count(db, company_id) <= 1:
        raise _err("Не може да се премахне последният собственик", status.HTTP_409_CONFLICT)
    db.delete(m)
    db.commit()
