"""Логика на RBAC: роли, права и проверки за достъп.

Ключова идея: правата се четат от ролята на членството (`Membership.role_id`). Ако
компанията още не е минала на гъвкави роли, се ползва картата от старите enum роли, за
да няма прекъсване на достъпа.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AccessDeniedError
from app.modules.companies.models import CompanyRole, Membership
from app.modules.rbac.models import Role
from app.modules.rbac.permissions import (
    ALL_PERMISSIONS,
    ROLE_TEMPLATES,
    ROLE_TEMPLATES_BY_CODE,
    WILDCARD,
    expand,
)
from app.modules.rbac.schemas import RoleCreate, RoleUpdate

# Съответствие старите enum роли → шаблони, за компании без дефинирани роли.
_LEGACY_MAP: dict[CompanyRole, str] = {
    CompanyRole.OWNER: "MANAGER",
    CompanyRole.MANAGER: "MANAGER",
    CompanyRole.SYS_ADMIN: "MANAGER",
    CompanyRole.CFO: "CFO",
    CompanyRole.CHIEF_ACCOUNTANT: "CHIEF_ACCOUNTANT",
    CompanyRole.ACCOUNTANT: "ACCOUNTANT",
    CompanyRole.EXTERNAL_ACCOUNTANT: "EXTERNAL_ACCOUNTANT",
    CompanyRole.AUDITOR: "AUDITOR",
    CompanyRole.TAX_CONSULTANT: "TAX_CONSULTANT",
    CompanyRole.EMPLOYEE_SUBMITTER: "EMPLOYEE",
    CompanyRole.EMPLOYEE_APPROVER: "APPROVER",
    CompanyRole.SECURITY_ADMIN: "MANAGER",
    CompanyRole.READ_ONLY: "READ_ONLY",
}

_ADMIN_CONTACT = "Обърни се към администратор на дружеството."


def _err(msg: str, code: int = status.HTTP_403_FORBIDDEN) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


# ============================ Роли ============================
def seed_roles(db: Session, company_id: uuid.UUID) -> list[Role]:
    """Създава предефинираните роли за компанията (идемпотентно)."""
    existing = {r.code for r in list_roles(db, company_id)}
    created: list[Role] = []
    for tpl in ROLE_TEMPLATES:
        if tpl.code in existing:
            continue
        role = Role(
            company_id=company_id,
            code=tpl.code,
            name=tpl.name,
            description=tpl.description,
            permissions=list(tpl.permissions),
            can_use_mobile=tpl.can_use_mobile,
            is_admin=tpl.is_admin,
            is_system=True,
        )
        db.add(role)
        created.append(role)
    db.commit()
    return created


def list_roles(db: Session, company_id: uuid.UUID) -> list[Role]:
    return list(
        db.scalars(
            select(Role).where(Role.company_id == company_id).order_by(Role.is_system.desc(), Role.name)
        )
    )


def get_role(db: Session, company_id: uuid.UUID, role_id: uuid.UUID) -> Role:
    role = db.get(Role, role_id)
    if role is None or role.company_id != company_id:
        raise _err("Ролята не е намерена", status.HTTP_404_NOT_FOUND)
    return role


def _validate_permissions(permissions: list[str]) -> list[str]:
    unknown = [p for p in permissions if p != WILDCARD and p not in ALL_PERMISSIONS]
    if unknown:
        raise _err(
            f"Непознати права: {', '.join(sorted(unknown))}",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return permissions


def create_role(db: Session, company_id: uuid.UUID, data: RoleCreate) -> Role:
    code = data.code.strip().upper()
    if db.scalar(select(Role).where(Role.company_id == company_id, Role.code == code)):
        raise _err(f"Роля с код {code} вече съществува", status.HTTP_409_CONFLICT)
    role = Role(
        company_id=company_id,
        code=code,
        name=data.name,
        description=data.description,
        permissions=_validate_permissions(data.permissions),
        can_use_mobile=data.can_use_mobile,
        is_admin=data.is_admin,
        is_system=False,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


def clone_role(db: Session, company_id: uuid.UUID, role_id: uuid.UUID, new_code: str, new_name: str) -> Role:
    """Клонира роля (напр. системна) в редактируема собствена роля."""
    src = get_role(db, company_id, role_id)
    return create_role(db, company_id, RoleCreate(
        code=new_code, name=new_name, description=f"Копие на „{src.name}“",
        permissions=list(src.permissions), can_use_mobile=src.can_use_mobile, is_admin=src.is_admin,
    ))


def update_role(db: Session, company_id: uuid.UUID, role_id: uuid.UUID, data: RoleUpdate) -> Role:
    role = get_role(db, company_id, role_id)
    payload = data.model_dump(exclude_unset=True)
    if "permissions" in payload and payload["permissions"] is not None:
        if role.is_system:
            raise _err(
                "Правата на системна роля не се променят — клонирай я и редактирай копието.",
                status.HTTP_409_CONFLICT,
            )
        role.permissions = _validate_permissions(payload["permissions"])
    for field in ("name", "description", "can_use_mobile", "is_admin", "is_active"):
        if field in payload and payload[field] is not None:
            if role.is_system and field == "is_admin":
                continue  # административният характер на системна роля е фиксиран
            setattr(role, field, payload[field])
    db.commit()
    db.refresh(role)
    return role


def delete_role(db: Session, company_id: uuid.UUID, role_id: uuid.UUID) -> None:
    role = get_role(db, company_id, role_id)
    if role.is_system:
        raise _err("Системна роля не се изтрива — деактивирай я.", status.HTTP_409_CONFLICT)
    in_use = db.scalar(select(Membership).where(Membership.role_id == role.id))
    if in_use is not None:
        raise _err(
            "Ролята е присвоена на член от екипа — първо я смени.", status.HTTP_409_CONFLICT
        )
    db.delete(role)
    db.commit()


# ============================ Права на членство ============================
def role_for_membership(db: Session, membership: Membership) -> Role | None:
    if membership.role_id is not None:
        return db.get(Role, membership.role_id)
    # Компанията още няма гъвкави роли: ползваме съответстващия шаблон.
    return db.scalar(
        select(Role).where(
            Role.company_id == membership.company_id,
            Role.code == _LEGACY_MAP.get(membership.role, "READ_ONLY"),
        )
    )


def permissions_for(db: Session, membership: Membership) -> set[str]:
    role = role_for_membership(db, membership)
    if role is not None:
        if not role.is_active:
            return set()
        return expand(list(role.permissions))
    # Крайно резервно поведение: правата на съответния шаблон.
    tpl = ROLE_TEMPLATES_BY_CODE.get(_LEGACY_MAP.get(membership.role, "READ_ONLY"))
    return expand(list(tpl.permissions)) if tpl else set()


def has_permission(db: Session, membership: Membership, permission: str) -> bool:
    return permission in permissions_for(db, membership)


def can_use_mobile(db: Session, membership: Membership) -> bool:
    role = role_for_membership(db, membership)
    if role is not None:
        return bool(role.is_active and role.can_use_mobile)
    tpl = ROLE_TEMPLATES_BY_CODE.get(_LEGACY_MAP.get(membership.role, "READ_ONLY"))
    return bool(tpl and tpl.can_use_mobile)


def is_admin(db: Session, membership: Membership) -> bool:
    role = role_for_membership(db, membership)
    if role is not None:
        return bool(role.is_active and (role.is_admin or WILDCARD in role.permissions))
    return membership.role in (CompanyRole.OWNER, CompanyRole.SYS_ADMIN)


# ============================ Проверки за достъп ============================
def require_permission(db: Session, membership: Membership, permission: str) -> None:
    if not has_permission(db, membership, permission):
        role = role_for_membership(db, membership)
        raise AccessDeniedError(
            f"Нямате право за това действие ({permission}). {_ADMIN_CONTACT}",
            code="PERMISSION_DENIED",
            required_permission=permission,
            role=role.name if role else None,
        )


def require_mobile_access(db: Session, membership: Membership) -> None:
    """Мобилният достъп е отделно право — съобщението е ясно за мобилния клиент."""
    if not can_use_mobile(db, membership):
        role = role_for_membership(db, membership)
        raise AccessDeniedError(
            "Вашата роля не позволява достъп през мобилното приложение. " + _ADMIN_CONTACT,
            code="MOBILE_ACCESS_DENIED",
            role=role.name if role else None,
        )


def require_admin(db: Session, membership: Membership) -> None:
    if not is_admin(db, membership):
        raise AccessDeniedError(
            "Само администратор управлява роли и екип. " + _ADMIN_CONTACT,
            code="ADMIN_REQUIRED",
        )


def assign_role(
    db: Session, company_id: uuid.UUID, membership_id: uuid.UUID, role_id: uuid.UUID | None
) -> Membership:
    """Присвоява роля на член от екипа (или я маха, за да важи старият enum)."""
    membership = db.get(Membership, membership_id)
    if membership is None or membership.company_id != company_id:
        raise _err("Членството не е намерено", status.HTTP_404_NOT_FOUND)
    if role_id is not None:
        role = get_role(db, company_id, role_id)
        # Пазим поне един администратор в дружеството.
        if not role.is_admin and WILDCARD not in role.permissions and is_admin(db, membership):
            others = [
                m for m in db.scalars(
                    select(Membership).where(
                        Membership.company_id == company_id, Membership.id != membership.id
                    )
                ) if is_admin(db, m)
            ]
            if not others:
                raise _err(
                    "Дружеството трябва да има поне един администратор.",
                    status.HTTP_409_CONFLICT,
                )
        membership.role_id = role.id
    else:
        membership.role_id = None
    db.commit()
    db.refresh(membership)
    return membership
