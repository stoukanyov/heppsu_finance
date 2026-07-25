"""Подавания към НАП — подготвени пакети, статуси и получени разписки.

Процесът днес е: системата подготвя пакет → потребителят го качва в портала на НАП и
подписва с КЕП → получената разписка/протокол се импортира тук и се съхранява.

Системата НЕ подава сама и не имитира действия в портала (виж решение D-012).
"""
from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class SubmissionKind(str, enum.Enum):
    VAT_RETURN = "VAT_RETURN"              # справка-декларация + дневници (+ VIES)
    INCOME_REPORT_73 = "INCOME_REPORT_73"  # справка по чл. 73 ЗДДФЛ
    SAFT = "SAFT"                          # бъдещо
    OTHER = "OTHER"


class SubmissionStatus(str, enum.Enum):
    """Жизнен цикъл на подаването (човекът подава, системата следи)."""

    PREPARED = "PREPARED"                  # пакетът е генериран
    DOWNLOADED = "DOWNLOADED"              # изтеглен от потребителя
    SUBMITTED_EXTERNALLY = "SUBMITTED_EXTERNALLY"  # подаден в портала с КЕП
    RECEIPT_IMPORTED = "RECEIPT_IMPORTED"  # разписката е приложена
    ACCEPTED = "ACCEPTED"                  # приета от НАП
    REJECTED = "REJECTED"                  # отхвърлена (с мотив)
    CANCELLED = "CANCELLED"


ALLOWED_TRANSITIONS: dict[SubmissionStatus, set[SubmissionStatus]] = {
    SubmissionStatus.PREPARED: {
        SubmissionStatus.DOWNLOADED,
        SubmissionStatus.SUBMITTED_EXTERNALLY,
        SubmissionStatus.CANCELLED,
    },
    SubmissionStatus.DOWNLOADED: {
        SubmissionStatus.SUBMITTED_EXTERNALLY,
        SubmissionStatus.CANCELLED,
    },
    SubmissionStatus.SUBMITTED_EXTERNALLY: {
        SubmissionStatus.RECEIPT_IMPORTED,
        SubmissionStatus.ACCEPTED,
        SubmissionStatus.REJECTED,
        SubmissionStatus.CANCELLED,
    },
    SubmissionStatus.RECEIPT_IMPORTED: {
        SubmissionStatus.ACCEPTED,
        SubmissionStatus.REJECTED,
    },
    SubmissionStatus.ACCEPTED: set(),
    SubmissionStatus.REJECTED: {SubmissionStatus.PREPARED},  # коригира се и се подава наново
    SubmissionStatus.CANCELLED: set(),
}


class NraSubmission(UUIDMixin, TimestampMixin, Base):
    """Едно подаване (или опит за подаване) на данъчен пакет към НАП."""

    __tablename__ = "nra_submissions"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Периодът, за който е подаването (нула за годишни справки без период).
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("accounting_periods.id", ondelete="SET NULL"), index=True, nullable=True
    )
    period_code: Mapped[str] = mapped_column(String(10), nullable=False)

    kind: Mapped[SubmissionKind] = mapped_column(
        SAEnum(SubmissionKind, native_enum=False, length=25), nullable=False
    )
    status: Mapped[SubmissionStatus] = mapped_column(
        SAEnum(SubmissionStatus, native_enum=False, length=25),
        default=SubmissionStatus.PREPARED, index=True, nullable=False,
    )
    provider_code: Mapped[str] = mapped_column(String(40), nullable=False)

    # Пакетът: пази се като документ, за да е неизменим и проследим.
    package_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    package_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    package_sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    package_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    package_contents: Mapped[str | None] = mapped_column(String(500), nullable=True)

    submission_deadline: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    submitted_at: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    # Разписка / протокол от НАП
    receipt_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    receipt_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    receipt_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    receipt_imported_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    prepared_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
