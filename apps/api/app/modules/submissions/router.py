"""API рутер за подаванията към НАП (tenant-scoped).

Съзнателно НЯМА endpoint „подай към НАП": системата подготвя пакет, а подаването се
извършва от потребителя в портала на НАП с КЕП. Разписката се импортира обратно тук.
"""
import uuid
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Response, UploadFile, status

from app.api.deps import CurrentCompany, DbSession
from app.modules.submissions import service
from app.modules.submissions.schemas import (
    SubmissionMarkSubmittedIn,
    SubmissionOut,
    SubmissionPreviewOut,
    SubmissionReceiptIn,
)
from app.tax_engine.submission.registry import available_providers, get_submission_provider

router = APIRouter(prefix="/submissions", tags=["submissions"])


@router.get("/providers")
def list_providers() -> dict:
    """Регистрираните провайдъри за подаване и техните възможности."""
    active = get_submission_provider()
    return {
        "active": active.code,
        "providers": [
            {
                "code": p.code,
                "name": p.name,
                "capabilities": list(p.capabilities),
                "electronic_submission": p.supports_electronic_submission,
                "available": p.code == active.code,
            }
            for p in available_providers()
        ],
        "note": (
            "Днес подаването е ръчно през портала на НАП с КЕП. Автоматизация чрез "
            "имитиране на кликове не се реализира; електронно подаване ще се добави "
            "като нов провайдър при публикуван официален API."
        ),
    }


@router.get("/vat/{period_id}/preview", response_model=SubmissionPreviewOut)
def preview_vat(period_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> SubmissionPreviewOut:
    """Финален преглед и контролни проверки преди подготовката на пакета."""
    return service.preview_vat_submission(db, ctx.company, period_id)


@router.post("/vat/{period_id}/prepare", response_model=SubmissionOut, status_code=status.HTTP_201_CREATED)
def prepare_vat(period_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> SubmissionOut:
    """„Подготви пакет за НАП" — генерира декларацията, дневниците и VIES (при нужда)."""
    sub = service.prepare_vat_package(db, ctx.company, ctx.membership.user_id, period_id)
    return SubmissionOut.model_validate(sub)


@router.get("", response_model=list[SubmissionOut])
def list_submissions(
    ctx: CurrentCompany, db: DbSession, period_id: uuid.UUID | None = None
) -> list[SubmissionOut]:
    return [
        SubmissionOut.model_validate(s)
        for s in service.list_submissions(db, ctx.company.id, period_id)
    ]


@router.get("/{submission_id}", response_model=SubmissionOut)
def get_submission(submission_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> SubmissionOut:
    return SubmissionOut.model_validate(service.get_submission(db, ctx.company.id, submission_id))


@router.get("/{submission_id}/package")
def download_package(submission_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> Response:
    """Изтегля пакета за качване в портала („Експортирай за подаване")."""
    sub, data = service.download_package(db, ctx.company.id, submission_id)
    disposition = f"attachment; filename*=UTF-8''{quote(sub.package_filename)}"
    return Response(
        content=data, media_type="application/zip",
        headers={"Content-Disposition": disposition},
    )


@router.post("/{submission_id}/mark-submitted", response_model=SubmissionOut)
def mark_submitted(
    submission_id: uuid.UUID,
    data: SubmissionMarkSubmittedIn,
    ctx: CurrentCompany,
    db: DbSession,
) -> SubmissionOut:
    """Отбелязва, че пакетът е подаден в портала на НАП с КЕП (извън системата)."""
    return SubmissionOut.model_validate(
        service.mark_submitted(db, ctx.company.id, submission_id, data)
    )


@router.post("/{submission_id}/receipt", response_model=SubmissionOut, status_code=status.HTTP_201_CREATED)
async def import_receipt(
    submission_id: uuid.UUID,
    ctx: CurrentCompany,
    db: DbSession,
    file: UploadFile = File(...),
    receipt_number: str | None = Form(None),
    receipt_date: str | None = Form(None),
    accepted: bool = Form(True),
    notes: str | None = Form(None),
) -> SubmissionOut:
    """„Импортирай разписка" — съхранява разписката/протокола от НАП."""
    import datetime as dt

    content = await file.read()
    parsed_date = None
    if receipt_date:
        try:
            parsed_date = dt.date.fromisoformat(receipt_date)
        except ValueError:
            parsed_date = None
    data = SubmissionReceiptIn(
        receipt_number=receipt_number, receipt_date=parsed_date, accepted=accepted, notes=notes
    )
    sub = service.import_receipt(
        db, ctx.company.id, ctx.membership.user_id, submission_id,
        filename=file.filename or "razpiska.pdf",
        content_type=file.content_type or "application/pdf",
        content=content,
        data=data,
    )
    return SubmissionOut.model_validate(sub)
