"""Бизнес логика на модул „Документи": приемане, дедупликация, статуси."""
import hashlib
import uuid

from fastapi import HTTPException, status
from sqlalchemy import Select, func, or_, select
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


# Пагинация на списъка с документи: при няколко хиляди записа пълният списък
# натоварва и сървъра, и телефона.
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200


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
    trusted: bool = False,
) -> Document:
    # `trusted` е за файлове, генерирани от самата система (напр. ZIP пакет за НАП);
    # качванията от потребители винаги минават през белия списък на типовете.
    if not trusted and content_type not in settings.ALLOWED_CONTENT_TYPES:
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


def _escape_like(text: str) -> str:
    """Екранира спецсимволите на LIKE, за да не се тълкуват като шаблон."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _documents_query(
    company_id: uuid.UUID,
    status_filter: DocumentStatus | None,
    doc_type: DocumentType | None,
    counterparty_id: uuid.UUID | None,
    q: str | None,
) -> Select:
    """Общата заявка за списъка — ползва се и за страницата, и за общия брой."""
    stmt = select(Document).where(Document.company_id == company_id)
    if status_filter is not None:
        stmt = stmt.where(Document.status == status_filter)
    if doc_type is not None:
        stmt = stmt.where(Document.doc_type == doc_type)
    if counterparty_id is not None:
        stmt = stmt.where(Document.counterparty_id == counterparty_id)

    text = (q or "").strip()
    if text:
        pattern = f"%{_escape_like(text.lower())}%"
        # Свободният текст търси по име на файл, бележки и име на контрагента.
        # LEFT JOIN, защото документ без контрагент също трябва да се намира.
        stmt = stmt.outerjoin(Counterparty, Document.counterparty_id == Counterparty.id).where(
            or_(
                func.lower(Document.original_filename).like(pattern, escape="\\"),
                func.lower(Document.notes).like(pattern, escape="\\"),
                func.lower(Counterparty.name).like(pattern, escape="\\"),
            )
        )
    return stmt


def list_documents(
    db: Session,
    company_id: uuid.UUID,
    status_filter: DocumentStatus | None = None,
    doc_type: DocumentType | None = None,
    counterparty_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
    offset: int = 0,
) -> tuple[list[Document], int]:
    """Страница от документите + общия брой съвпадения (за `X-Total-Count`).

    `limit` се реже до `MAX_PAGE_LIMIT` вместо да връща грешка — клиентът получава
    най-многото, което сървърът е готов да даде, без излишен неуспех.
    """
    limit = min(max(int(limit), 1), MAX_PAGE_LIMIT)
    offset = max(int(offset), 0)

    stmt = _documents_query(company_id, status_filter, doc_type, counterparty_id, q)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(
            stmt.order_by(Document.created_at.desc(), Document.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, total


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


def confirm_posting(
    db: Session, company_id: uuid.UUID, user_id: uuid.UUID, doc_id: uuid.UUID
) -> tuple[Document, JournalEntry]:
    """Потвърждава предложената статия: осчетоводява я и придвижва документа.

    Човешкото решение в потока „AI предлага, човек потвърждава". Документът
    минава PROPOSED → APPROVED → POSTED наведнъж, за да не увисне в междинно
    състояние. Ако статията вече е осчетоводена, връща я без промяна
    (идемпотентност при повторно натискане от клиента).
    """
    # Локален импорт: accounting е по-долен слой и не бива да се зарежда на
    # ниво модул тук, за да остане зависимостта еднопосочна.
    from app.modules.accounting import service as accounting_service
    from app.modules.accounting.models import EntryStatus

    doc = get_document(db, company_id, doc_id)
    if doc.journal_entry_id is None:
        raise _err(
            "Документът няма предложена счетоводна статия за потвърждаване",
            status.HTTP_409_CONFLICT,
        )

    entry = accounting_service.get_entry(db, company_id, doc.journal_entry_id)
    if entry.status == EntryStatus.DRAFT:
        entry = accounting_service.post_entry(db, company_id, entry.id, user_id)

    # Придвижваме документа само напред и само по допустими преходи.
    for target in (DocumentStatus.APPROVED, DocumentStatus.POSTED):
        if doc.status == target:
            continue
        if target in ALLOWED_TRANSITIONS.get(doc.status, set()):
            doc.status = target

    db.commit()
    db.refresh(doc)
    db.refresh(entry)
    return doc, entry


def get_file(db: Session, company_id: uuid.UUID, doc_id: uuid.UUID) -> tuple[Document, bytes]:
    doc = get_document(db, company_id, doc_id)
    return doc, storage.read_file(doc.storage_path)
