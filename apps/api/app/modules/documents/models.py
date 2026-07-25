"""Модул „Документи": приемане, съхранение и жизнен цикъл (master prompt 6.11)."""
from __future__ import annotations

import enum
import uuid

from sqlalchemy import (
    BigInteger,
    Enum as SAEnum,
    ForeignKey,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class DocumentType(str, enum.Enum):
    UNKNOWN = "UNKNOWN"
    INVOICE_PURCHASE = "INVOICE_PURCHASE"   # Фактура (покупка)
    INVOICE_SALE = "INVOICE_SALE"           # Фактура (продажба)
    CREDIT_NOTE = "CREDIT_NOTE"             # Кредитно известие
    DEBIT_NOTE = "DEBIT_NOTE"               # Дебитно известие
    RECEIPT = "RECEIPT"                     # Касова бележка
    BANK_STATEMENT = "BANK_STATEMENT"       # Банково извлечение
    CONTRACT = "CONTRACT"                   # Договор
    OTHER = "OTHER"


class DocumentSource(str, enum.Enum):
    UPLOAD = "UPLOAD"
    EMAIL = "EMAIL"
    MOBILE = "MOBILE"
    API = "API"
    INTEGRATION = "INTEGRATION"


class DocumentStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    OCR_PROCESSING = "OCR_PROCESSING"
    RECOGNIZED = "RECOGNIZED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    MISSING_DATA = "MISSING_DATA"
    POTENTIAL_DUPLICATE = "POTENTIAL_DUPLICATE"
    PROPOSED = "PROPOSED"          # предложен за осчетоводяване
    RETURNED = "RETURNED"          # върнат за корекция
    APPROVED = "APPROVED"
    POSTED = "POSTED"              # осчетоводен
    ARCHIVED = "ARCHIVED"
    CANCELLED = "CANCELLED"


class Document(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)  # относителен път
    sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    doc_type: Mapped[DocumentType] = mapped_column(
        SAEnum(DocumentType, native_enum=False, length=20), default=DocumentType.UNKNOWN, nullable=False
    )
    source: Mapped[DocumentSource] = mapped_column(
        SAEnum(DocumentSource, native_enum=False, length=20), default=DocumentSource.UPLOAD, nullable=False
    )
    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus, native_enum=False, length=25), default=DocumentStatus.RECEIVED, nullable=False
    )

    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True
    )
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
    )
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
