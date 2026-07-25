"""Pydantic схеми за подаванията към НАП."""
import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.modules.submissions.models import SubmissionKind, SubmissionStatus


class SubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    period_id: uuid.UUID | None
    period_code: str
    kind: SubmissionKind
    status: SubmissionStatus
    provider_code: str
    package_filename: str
    package_sha256: str
    package_size: int
    package_contents: str | None
    submission_deadline: dt.date | None
    submitted_at: dt.date | None
    receipt_number: str | None
    receipt_date: dt.date | None
    receipt_document_id: uuid.UUID | None
    notes: str | None


class SubmissionPreviewOut(BaseModel):
    """Финален преглед преди подаване: какво съдържа пакетът и какво още куца."""

    period_code: str
    kind: SubmissionKind
    provider_code: str
    provider_name: str
    supports_electronic_submission: bool
    portal_url: str | None
    package_contents: list[str]
    instructions: list[str]
    submission_deadline: dt.date | None
    # Контролни проверки — блокиращите пречат на подготовката.
    controls: list[dict] = []
    has_blocking_errors: bool = False
    # Ключови стойности за преглед (клетки 50/60/80/81/82 и общи суми).
    summary: dict = {}


class SubmissionReceiptIn(BaseModel):
    """Метаданни към импортираната разписка/протокол от НАП."""

    receipt_number: str | None = Field(default=None, max_length=120)
    receipt_date: dt.date | None = None
    accepted: bool = True
    notes: str | None = Field(default=None, max_length=1000)


class SubmissionMarkSubmittedIn(BaseModel):
    submitted_at: dt.date | None = None
    notes: str | None = Field(default=None, max_length=1000)
