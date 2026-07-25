"""Бизнес логика на модул „Документи": приемане, дедупликация, статуси."""
import hashlib
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.accounting.models import JournalEntry
from app.modules.counterparties.models import Counterparty
from app.modules.documents import storage
from app.modules.documents.models import (
    Document,
    DocumentSource,
    DocumentStatus,
    DocumentType,
)
from app.modules.documents.schemas import DocumentUpdate

# Допустими преходи между статуси (жизнен цикъл на документа).
ALLOWED_TRANSITIONS: dict[DocumentStatus, set[DocumentStatus]] = {
    DocumentStatus.RECEIVED: {DocumentStatus.OCR_PROCESSING, DocumentStatus.NEEDS_REVIEW, DocumentStatus.CANCELLED},
    DocumentStatus.OCR_PROCESSING: {DocumentStatus.RECOGNIZED, DocumentStatus.NEEDS_REVIEW, DocumentStatus.MISSING_DATA, DocumentStatus.CANCELLED},
    DocumentStatus.RECOGNIZED: {DocumentStatus.NEEDS_REVIEW, DocumentStatus.PROPOSED, DocumentStatus.CANCELLED},
    DocumentStatus.NEEDS_REVIEW: {DocumentStatus.PROPOSED, DocumentStatus.RETURNED, DocumentStatus.MISSING_DATA, DocumentStatus.CANCELLED},
    DocumentStatus.MISSING_DATA: {DocumentStatus.NEEDS_REVIEW, DocumentStatus.CANCELLED},
    DocumentStatus.POTENTIAL_DUPLICATE: {DocumentStatus.NEEDS_REVIEW, DocumentStatus.CANCELLED},
    DocumentStatus.PROPOSED: {DocumentStatus.APPROVED, DocumentStatus.RETURNED, DocumentStatus.CANCELLED},
    DocumentStatus.RETURNED: {DocumentStatus.NEEDS_REVIEW, DocumentStatus.PROPOSED, DocumentStatus.CANCELLED},
    DocumentStatus.APPROVED: {DocumentStatus.POSTED, DocumentStatus.RETURNED, DocumentStatus.CANCELLED},
    DocumentStatus.POSTED: {DocumentStatus.ARCHIVED},
    DocumentStatus.ARCHIVED: set(),
    DocumentStatus.CANCELLED: set(),
}


def _err(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


def create_document(
    db: Session,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    original_filename: str,
    content_type: str,
    content: bytes,
    source: DocumentSource = DocumentSource.UPLOAD,
) -> Document:
    if content_type not in settings.ALLOWED_CONTENT_TYPES:
        raise _err(f"Неподдържан тип файл: {content_type}", status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
    size = len(content)
    if size == 0:
        raise _err("Празен файл")
    if size > settings.MAX_UPLOAD_BYTES:
        raise _err(
            f"Файлът надвишава максималния размер ({settings.MAX_UPLOAD_BYTES} байта)",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    sha = hashlib.sha256(content).hexdigest()
    duplicate = db.scalar(
        select(Document).where(
            Document.company_id == company_id,
            Document.sha256 == sha,
            Document.status != DocumentStatus.CANCELLED,
        )
    )

    rel_path = storage.save_file(company_id, original_filename, content)
    doc = Document(
        company_id=company_id,
        original_filename=original_filename[:255],
        content_type=content_type,
        size_bytes=size,
        storage_path=rel_path,
        sha256=sha,
        source=source,
        status=DocumentStatus.POTENTIAL_DUPLICATE if duplicate else DocumentStatus.RECEIVED,
        duplicate_of_id=duplicate.id if duplicate else None,
        uploaded_by_id=user_id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def list_documents(
    db: Session,
    company_id: uuid.UUID,
    status_filter: DocumentStatus | None = None,
    doc_type: DocumentType | None = None,
    counterparty_id: uuid.UUID | None = None,
) -> list[Document]:
    stmt = select(Document).where(Document.company_id == company_id)
    if status_filter is not None:
        stmt = stmt.where(Document.status == status_filter)
    if doc_type is not None:
        stmt = stmt.where(Document.doc_type == doc_type)
    if counterparty_id is not None:
        stmt = stmt.where(Document.counterparty_id == counterparty_id)
    return list(db.scalars(stmt.order_by(Document.created_at.desc())))


def get_document(db: Session, company_id: uuid.UUID, doc_id: uuid.UUID) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None or doc.company_id != company_id:
        raise _err("Документът не е намерен", status.HTTP_404_NOT_FOUND)
    return doc


def update_document(
    db: Session, company_id: uuid.UUID, doc_id: uuid.UUID, data: DocumentUpdate
) -> Document:
    doc = get_document(db, company_id, doc_id)
    fields = data.model_dump(exclude_unset=True)

    if fields.get("counterparty_id") is not None:
        cp = db.get(Counterparty, fields["counterparty_id"])
        if cp is None or cp.company_id != company_id:
            raise _err("Контрагентът не съществува в тази компания")
    if fields.get("journal_entry_id") is not None:
        je = db.get(JournalEntry, fields["journal_entry_id"])
        if je is None or je.company_id != company_id:
            raise _err("Счетоводната операция не съществува в тази компания")

    for key, value in fields.items():
        setattr(doc, key, value)
    db.commit()
    db.refresh(doc)
    return doc


def update_status(
    db: Session, company_id: uuid.UUID, doc_id: uuid.UUID, new_status: DocumentStatus
) -> Document:
    doc = get_document(db, company_id, doc_id)
    if new_status == doc.status:
        return doc
    if new_status not in ALLOWED_TRANSITIONS.get(doc.status, set()):
        raise _err(
            f"Недопустим преход на статус: {doc.status.value} → {new_status.value}",
            status.HTTP_409_CONFLICT,
        )
    doc.status = new_status
    db.commit()
    db.refresh(doc)
    return doc


def get_file(db: Session, company_id: uuid.UUID, doc_id: uuid.UUID) -> tuple[Document, bytes]:
    doc = get_document(db, company_id, doc_id)
    return doc, storage.read_file(doc.storage_path)
