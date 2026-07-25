"""Pydantic схеми за модул „Документи"."""
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.modules.accounting.schemas import JournalEntryOut
from app.modules.ai.schemas import (  # leaf модул — без цикъл
    ExtractionOut,
    PostingProposalOut,
)
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


class ExtractionFieldsUpdate(BaseModel):
    """Ръчна корекция на разпознатите данни (когато AI е разчел зле).

    `fields` съдържа САМО полетата за промяна — сливат се върху съществуващите
    (merge, не replace). Коригираните полета се маркират като човешки потвърдени
    и вече не свалят общата увереност.
    """

    fields: dict = Field(default_factory=dict)
    recalculate: bool = True   # да се преизчисли ли предложението за статия


class ScanResultOut(BaseModel):
    """Резултат от мобилно сканиране: документът, разпознатите данни и предложената статия."""

    document: DocumentOut
    extraction: ExtractionOut
    # None, ако предложението не може да се направи — сканът не се проваля заради това.
    posting: PostingProposalOut | None = None


class PostingConfirmOut(BaseModel):
    """Резултат от човешкото потвърждение: осчетоводената статия и документът."""

    document: DocumentOut
    entry: JournalEntryOut
