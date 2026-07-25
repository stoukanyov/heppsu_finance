"""RBAC модел: роли с права, дефинирани на ниво компания.

Ролята е набор от права (`ресурс.действие`) плюс два флага: може ли носителят да
управлява роли/екип и може ли да ползва мобилното приложение. Системните роли идват от
шаблоните и могат да се клонират, но не и да се изтриват.
"""
from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Role(UUIDMixin, TimestampMixin, Base):
    """Роля в контекста на една компания."""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_role_company_code"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Списък права; `["*"]` означава пълен достъп.
    permissions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # Мобилният достъп е отделно решение на администратора, не следствие от правата.
    can_use_mobile: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Административна роля: управлява роли и екип.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Системните роли идват от шаблон и не се изтриват.
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
