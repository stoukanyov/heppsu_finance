"""API рутер за модул „Документи" (tenant-scoped)."""
import uuid
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status

from app.api.deps import CurrentCompany, DbSession, require
from app.modules.accounting.schemas import JournalEntryOut
from app.modules.ai import posting as ai_posting
from app.modules.ai import service as ai_service
from app.modules.ai.schemas import ExtractionOut, PostingProposalOut
from app.modules.rbac import service as rbac_service
from app.modules.documents import service
from app.modules.documents.models import DocumentSource, DocumentStatus, DocumentType
from app.modules.documents.schemas import (
    DocumentOut,
    DocumentStatusUpdate,
    DocumentUpdate,
    ExtractionFieldsUpdate,
    PostingConfirmOut,
    ScanResultOut,
)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/scan", response_model=ScanResultOut, status_code=status.HTTP_201_CREATED)
async def scan_document(
    ctx: CurrentCompany,
    db: DbSession,
    file: UploadFile = File(...),
    note: str | None = Form(None),
) -> ScanResultOut:
    """Мобилно сканиране: качва изображението/PDF и веднага го OCR-ва.

    В един кръг: създава документ със `source=MOBILE`, пази оригинала (storage_path)
    и връща разпознатите структурирани данни. AI само предлага — не осчетоводява.

    Достъпът изисква роля с разрешен мобилен достъп; иначе се връща 403 с ясно
    съобщение да се потърси администратор.
    """
    rbac_service.require_mobile_access(db, ctx.membership)
    rbac_service.require_permission(db, ctx.membership, "documents.upload")
    content = await file.read()
    doc = service.create_document(
        db,
        ctx.company.id,
        ctx.membership.user_id,
        original_filename=file.filename or "scan.jpg",
        content_type=file.content_type or "application/octet-stream",
        content=content,
        source=DocumentSource.MOBILE,
    )
    if note:
        service.update_document(db, ctx.company.id, doc.id, DocumentUpdate(notes=note))
    extraction = ai_service.extract_document(db, ctx.company, ctx.membership.user_id, doc.id)
    # Файлиране при контрагента (създава се при нужда) — независимо от осчетоводяването,
    # за да е сканът намираем в досието му дори когато статия не може да се предложи.
    ai_posting.file_document_to_counterparty(db, ctx.company, doc)
    # Предложението е „бонус": ако се провали, сканът пак връща документа и данните.
    posting = ai_posting.safe_propose_posting(db, ctx.company, ctx.membership.user_id, doc.id)
    db.refresh(doc)
    return ScanResultOut(
        document=DocumentOut.model_validate(doc),
        extraction=ExtractionOut.model_validate(extraction),
        posting=posting,
    )


@router.post(
    "/{doc_id}/propose-posting",
    response_model=PostingProposalOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require("documents.upload")],
)
def propose_posting(doc_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> PostingProposalOut:
    """Предлага счетоводна статия (DRAFT) по разпознатите данни на документа.

    AI само предлага: потвърждението е ръчно, чрез
    `POST /accounting/journal-entries/{id}/post`. Повторно извикване връща същата
    статия, вместо да създава втора.
    """
    return ai_posting.propose_posting(db, ctx.company, ctx.membership.user_id, doc_id)


@router.post("/{doc_id}/confirm-posting", response_model=PostingConfirmOut, dependencies=[require("documents.approve")])
def confirm_posting(doc_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> PostingConfirmOut:
    """Потвърждава предложената статия: осчетоводява я и придвижва документа.

    Това е човешкото решение в потока „AI предлага, човек потвърждава" — оттук
    нататък статията е непроменима (само сторно). Документът минава
    PROPOSED → APPROVED → POSTED в един кръг, за да не остане в междинно
    състояние, ако клиентът прекъсне.
    """
    doc, entry = service.confirm_posting(db, ctx.company.id, ctx.membership.user_id, doc_id)
    return PostingConfirmOut(
        document=DocumentOut.model_validate(doc),
        entry=JournalEntryOut.model_validate(entry),
    )


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED, dependencies=[require("documents.upload")])
async def upload_document(
    ctx: CurrentCompany,
    db: DbSession,
    file: UploadFile = File(...),
    source: DocumentSource = Form(DocumentSource.UPLOAD),
) -> DocumentOut:
    content = await file.read()
    doc = service.create_document(
        db,
        ctx.company.id,
        ctx.membership.user_id,
        original_filename=file.filename or "document",
        content_type=file.content_type or "application/octet-stream",
        content=content,
        source=source,
    )
    return DocumentOut.model_validate(doc)


@router.get("", response_model=list[DocumentOut], dependencies=[require("documents.view")])
def list_documents(
    ctx: CurrentCompany,
    db: DbSession,
    response: Response,
    status: DocumentStatus | None = None,
    doc_type: DocumentType | None = None,
    counterparty_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=200, description="Свободен текст: файл, бележки, контрагент"),
    limit: int = Query(service.DEFAULT_PAGE_LIMIT, description="Брой записи (максимум 200)"),
    offset: int = Query(0, description="Отместване за следваща страница"),
) -> list[DocumentOut]:
    """Страница от документите на компанията, най-новите първи.

    Отговорът остава чист `list[DocumentOut]` заради вече написаните клиенти (уеб и
    мобилно); общият брой съвпадения се връща в хедъра `X-Total-Count`. `limit` над
    максимума се реже, вместо да върне грешка.
    """
    docs, total = service.list_documents(
        db,
        ctx.company.id,
        status_filter=status,
        doc_type=doc_type,
        counterparty_id=counterparty_id,
        q=q,
        limit=limit,
        offset=offset,
    )
    response.headers["X-Total-Count"] = str(total)
    return [DocumentOut.model_validate(d) for d in docs]


@router.get("/{doc_id}", response_model=DocumentOut, dependencies=[require("documents.view")])
def get_document(doc_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> DocumentOut:
    return DocumentOut.model_validate(service.get_document(db, ctx.company.id, doc_id))


@router.get(
    "/{doc_id}/extraction",
    response_model=ExtractionOut | None,
    dependencies=[require("documents.view")],
)
def get_extraction(
    doc_id: uuid.UUID, ctx: CurrentCompany, db: DbSession
) -> ExtractionOut | None:
    """Последното разпознаване за документа, или `null`, ако още няма.

    Нужен е на клиентите, които показват документ, без да са го качили те —
    например мобилното при отваряне на вече съществуващ документ.
    """
    doc = service.get_document(db, ctx.company.id, doc_id)  # и проверка за достъп
    extraction = ai_posting.latest_extraction(db, doc)
    return None if extraction is None else ExtractionOut.model_validate(extraction)


@router.get("/{doc_id}/file", dependencies=[require("documents.view")])
def download_document(doc_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> Response:
    doc, data = service.get_file(db, ctx.company.id, doc_id)
    disposition = f"inline; filename*=UTF-8''{quote(doc.original_filename)}"
    return Response(content=data, media_type=doc.content_type, headers={"Content-Disposition": disposition})


@router.patch("/{doc_id}", response_model=DocumentOut, dependencies=[require("documents.upload")])
def update_document(
    doc_id: uuid.UUID, data: DocumentUpdate, ctx: CurrentCompany, db: DbSession
) -> DocumentOut:
    return DocumentOut.model_validate(service.update_document(db, ctx.company.id, doc_id, data))


@router.patch(
    "/{doc_id}/extraction",
    response_model=ScanResultOut,
    dependencies=[require("documents.upload")],
)
def correct_extraction(
    doc_id: uuid.UUID, data: ExtractionFieldsUpdate, ctx: CurrentCompany, db: DbSession
) -> ScanResultOut:
    """Ръчна корекция на разпознатите данни, когато AI е разчел зле документа.

    Подадените полета се сливат върху съществуващите (merge, не replace) и се
    маркират като човешки потвърдени — така вече не свалят общата увереност.
    При `recalculate=true` черновата по старите данни се изхвърля и се предлага
    нова статия. Осчетоводен документ не се коригира — тогава отговорът е 409 и
    поправката минава през сторно.

    Отговорът е същият `ScanResultOut` като при `/documents/scan`, за да преизползва
    мобилното целия си код за показване.
    """
    doc, extraction, posting = ai_service.correct_extraction(
        db,
        ctx.company,
        ctx.membership.user_id,
        doc_id,
        fields=data.fields,
        recalculate=data.recalculate,
    )
    return ScanResultOut(
        document=DocumentOut.model_validate(doc),
        extraction=ExtractionOut.model_validate(extraction),
        posting=posting,
    )


@router.patch("/{doc_id}/status", response_model=DocumentOut, dependencies=[require("documents.approve")])
def update_document_status(
    doc_id: uuid.UUID, data: DocumentStatusUpdate, ctx: CurrentCompany, db: DbSession
) -> DocumentOut:
    """Придвижва документа по жизнения му цикъл.

    Одобряващите преходи (APPROVED/POSTED) минават и през maker-checker, ако
    компанията го е включила — качилият документа не може да го одобри сам.
    """
    return DocumentOut.model_validate(
        service.update_status(
            db, ctx.company.id, doc_id, data.status, user_id=ctx.membership.user_id
        )
    )
