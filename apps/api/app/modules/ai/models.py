"""AI модул — съхранени резултати от AI обработка (OCR извличания, класификации)."""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class DocumentExtraction(UUIDMixin, TimestampMixin, Base):
    """Резултат от AI извличане на данни от документ (OCR/vision)."""

    __tablename__ = "document_extractions"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    # Структурираните разпознати данни (полета + confidence), както са върнати от модела.
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class ExpenseClassification(UUIDMixin, TimestampMixin, Base):
    """AI преценка за данъчното третиране на разход — одитна следа.

    Пази се защо разходът е приет за признат/непризнат по ЗКПО и какво е правото на
    данъчен кредит по ЗДДС, заедно с обосновките. Това е основанието при проверка;
    решението остава ревизируемо от човек.
    """

    __tablename__ = "expense_classifications"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    model: Mapped[str] = mapped_column(String(64), nullable=False)

    account_code: Mapped[str] = mapped_column(String(20), nullable=False)
    account_rationale: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Данъчно третиране по ЗКПО
    is_deductible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deductible_ratio: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    tax_rationale: Mapped[str] = mapped_column(String(1000), nullable=False)
    # Право на данъчен кредит по ЗДДС: FULL | PARTIAL | NONE | UNKNOWN
    vat_credit: Mapped[str] = mapped_column(String(10), default="UNKNOWN", nullable=False)
    vat_rationale: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    expense_category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0"), nullable=False)
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
