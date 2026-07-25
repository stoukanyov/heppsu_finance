"""Tenant & Company Management — компании и членство на потребители с роли (RBAC)."""
from __future__ import annotations

import datetime as dt
import enum
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.modules.identity.models import User


class CompanyRole(str, enum.Enum):
    """Роли в контекста на конкретна компания (по master prompt, раздел 4)."""

    OWNER = "OWNER"                        # Собственик
    MANAGER = "MANAGER"                    # Управител
    CFO = "CFO"                            # Финансов директор
    CHIEF_ACCOUNTANT = "CHIEF_ACCOUNTANT"  # Главен счетоводител
    ACCOUNTANT = "ACCOUNTANT"              # Оперативен счетоводител
    EXTERNAL_ACCOUNTANT = "EXTERNAL_ACCOUNTANT"  # Външна счетоводна къща
    AUDITOR = "AUDITOR"                    # Одитор (read-only + traceability)
    TAX_CONSULTANT = "TAX_CONSULTANT"      # Данъчен консултант
    EMPLOYEE_SUBMITTER = "EMPLOYEE_SUBMITTER"  # Служител, подаващ разход
    EMPLOYEE_APPROVER = "EMPLOYEE_APPROVER"    # Служител, одобряващ разход
    SYS_ADMIN = "SYS_ADMIN"                # Системен администратор
    SECURITY_ADMIN = "SECURITY_ADMIN"      # Security администратор
    READ_ONLY = "READ_ONLY"                # Read-only потребител


class Company(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    eik: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)          # ЕИК
    vat_number: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)   # ДДС номер
    country: Mapped[str] = mapped_column(String(2), default="BG", nullable=False)           # ISO-3166 alpha-2
    base_currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)    # ISO-4217
    is_vat_registered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ---- Контролни политики ----
    # Maker-checker („четири очи“): качилият документа не може сам да го осчетоводи.
    # NULL = компанията не е решавала → важи глобалното `MAKER_CHECKER_ENABLED`.
    # Нарочно е тристойностно: така по-късна промяна на глобалната политика хваща
    # компаниите без изрично мнение, без да прегазва тези, които са избрали сами.
    maker_checker_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # ---- Реквизити (за фактури, декларации и НАП файлове) ----
    name_latin: Mapped[str | None] = mapped_column(String(255), nullable=True)       # транслитерация
    legal_form: Mapped[str | None] = mapped_column(String(50), nullable=True)        # напр. ЕООД
    address_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address_postcode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    address_line: Mapped[str | None] = mapped_column(String(255), nullable=True)     # улица, №, ет., ап.
    manager_name: Mapped[str | None] = mapped_column(String(255), nullable=True)     # представляващ
    owner_name: Mapped[str | None] = mapped_column(String(255), nullable=True)       # собственик на капитала
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    activity: Mapped[str | None] = mapped_column(String(500), nullable=True)         # основна дейност
    vat_registration_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    incorporation_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    share_capital: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    @property
    def full_address(self) -> str:
        """Адрес на един ред — за фактури и документи."""
        parts = [p for p in (self.address_city, self.address_postcode, self.address_line) if p]
        return ", ".join(parts)

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Company {self.name}>"


class Membership(UUIDMixin, TimestampMixin, Base):
    """Връзка потребител ↔ компания с роля. Носител на tenant достъпа."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_membership_user_company"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[CompanyRole] = mapped_column(
        SAEnum(CompanyRole, native_enum=False, length=32), nullable=False
    )
    # Гъвкава роля от RBAC модула. Когато е зададена, тя определя правата; полето
    # `role` по-горе остава за съвместимост и за бърза ориентация.
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="SET NULL"), index=True, nullable=True
    )

    user: Mapped[User] = relationship(back_populates="memberships")
    company: Mapped[Company] = relationship(back_populates="memberships")
