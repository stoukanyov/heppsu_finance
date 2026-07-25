"""Pydantic схеми за модул „Документи"."""
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ai.schemas import ExtractionOut  # leaf модул — без цикъл
from app.modules.documents.models import DocumentSource, DocumentStatus, DocumentType


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    doc_type: DocumentType
    source: DocumentSource
    status: DocumentStatus
    counterparty_id: uuid.UUID | None
    journal_entry_id: uuid.UUID | None
    duplicate_of_id: uuid.UUID | None
    notes: str | None


class DocumentUpdate(BaseModel):
    """Обновяване на метаданни (не на самия файл)."""

    doc_type: DocumentType | None = None
    counterparty_id: uuid.UUID | None = None
    journal_entry_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=1000)


class DocumentStatusUpdate(BaseModel):
    status: DocumentStatus


class ScanResultOut(BaseModel):
    """Резултат от мобилно сканиране: и документът (изображение), и разпознатите данни."""

    document: DocumentOut
    extraction: ExtractionOut
