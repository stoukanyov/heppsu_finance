"""Логика на подаванията към НАП.

Потокът е точно този, който е реалистичен днес:
1) системата изчислява и валидира ДДС;
2) генерира целия пакет във формата на НАП;
3) показва финален преглед и контролни проверки;
4) потребителят натиска „Подготви пакет за НАП";
5) създава се пакет с декларацията, двата дневника и VIES (когато е приложима);
6) потребителят подава в портала на НАП с КЕП — извън системата;
7) разписката/протоколът се импортира и се съхранява тук.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.accounting.models import AccountingPeriod
from app.modules.companies.models import Company
from app.modules.documents import service as documents_service
from app.modules.documents.models import DocumentSource, DocumentType
from app.modules.submissions.models import (
    ALLOWED_TRANSITIONS,
    NraSubmission,
    SubmissionKind,
    SubmissionStatus,
)
from app.modules.submissions.schemas import (
    SubmissionMarkSubmittedIn,
    SubmissionPreviewOut,
    SubmissionReceiptIn,
)
from app.modules.vat import service as vat_service
from app.tax_engine.submission.registry import get_submission_provider

_VAT_PACKAGE_CONTENTS = [
    "DEKLAR.TXT — справка-декларация по ЗДДС",
    "PRODAGBI.TXT — дневник за продажбите",
    "POKUPKI.TXT — дневник за покупките",
]
_VIES_CONTENT = "VIES.TXT — VIES декларация (при вътреобщностни доставки)"


def _err(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


def _period(db: Session, company_id: uuid.UUID, period_id: uuid.UUID) -> AccountingPeriod:
    period = db.get(AccountingPeriod, period_id)
    if period is None or period.company_id != company_id:
        raise _err("Периодът не е намерен", status.HTTP_404_NOT_FOUND)
    return period


def _deadline(period: AccountingPeriod) -> dt.date:
    day_after = period.end_date + dt.timedelta(days=1)
    return dt.date(day_after.year, day_after.month, settings.VAT_SUBMISSION_DAY)


def _transition(sub: NraSubmission, target: SubmissionStatus) -> None:
    if target == sub.status:
        return
    if target not in ALLOWED_TRANSITIONS.get(sub.status, set()):
        raise _err(
            f"Недопустим преход на подаването: {sub.status.value} → {target.value}",
            status.HTTP_409_CONFLICT,
        )
    sub.status = target


# ============================ Финален преглед ============================
def preview_vat_submission(
    db: Session, company: Company, period_id: uuid.UUID
) -> SubmissionPreviewOut:
    """Стъпки 1–3: изчисление, валидации и какво ще съдържа пакетът."""
    period = _period(db, company.id, period_id)
    provider = get_submission_provider()
    declaration = vat_service.get_vat_declaration(db, company.id, period_id)
    vat_return = vat_service.get_vat_return(db, company.id, period_id)

    cells = {c.cell: Decimal(c.amount) for c in declaration.cells}
    contents = list(_VAT_PACKAGE_CONTENTS)
    if Decimal(cells.get("15", 0)) > 0:   # има ВОД → VIES е приложима
        contents.append(_VIES_CONTENT)

    controls = [
        {"level": c.level, "code": c.code, "message": c.message} for c in declaration.controls
    ]
    if not company.is_vat_registered:
        controls.insert(0, {
            "level": "ERROR", "code": "NOT_VAT_REGISTERED",
            "message": "Дружеството не е регистрирано по ЗДДС.",
        })
    if not (company.vat_number or company.eik):
        controls.insert(0, {
            "level": "ERROR", "code": "MISSING_IDENTIFIER",
            "message": "Липсва ДДС номер/ЕИК на дружеството — задай реквизитите.",
        })

    return SubmissionPreviewOut(
        period_code=period.code,
        kind=SubmissionKind.VAT_RETURN,
        provider_code=provider.code,
        provider_name=provider.name,
        supports_electronic_submission=provider.supports_electronic_submission,
        portal_url=provider.portal_url,
        package_contents=contents,
        instructions=[
            "Влез в портала на НАП с КЕП.",
            "Качи файловете от пакета за съответния данъчен период.",
            "Подпиши с КЕП и подай.",
            "Свали разписката и я импортирай тук.",
        ],
        submission_deadline=_deadline(period),
        controls=controls,
        has_blocking_errors=any(c["level"] == "ERROR" for c in controls),
        summary={
            "sales_base": str(vat_return.sales.total_base),
            "sales_vat": str(vat_return.sales.total_vat),
            "purchases_base": str(vat_return.purchases.total_base),
            "vat_credit": str(vat_return.purchases.total_credit),
            "cell_20": str(cells.get("20", Decimal("0.00"))),
            "cell_40": str(cells.get("40", Decimal("0.00"))),
            "cell_50": str(cells.get("50", Decimal("0.00"))),
            "cell_60": str(cells.get("60", Decimal("0.00"))),
        },
    )


# ============================ Подготовка на пакета ============================
def prepare_vat_package(
    db: Session, company: Company, user_id: uuid.UUID, period_id: uuid.UUID
) -> NraSubmission:
    """Стъпки 4–5: „Подготви пакет за НАП" — генерира и съхранява пакета.

    Пакетът се пази като документ, за да е неизменен и проследим при проверка.
    Системата НЕ подава — подаването е ръчно, в портала, с КЕП.
    """
    period = _period(db, company.id, period_id)
    preview = preview_vat_submission(db, company, period_id)
    if preview.has_blocking_errors:
        blocking = "; ".join(c["message"] for c in preview.controls if c["level"] == "ERROR")
        raise _err(f"Има блокиращи грешки — пакетът не е подготвен: {blocking}")

    payload, _filename = vat_service.build_nap_files(db, company.id, period_id)
    provider = get_submission_provider()
    package = provider.prepare_package(company, period.code, payload, preview.package_contents)

    doc = documents_service.create_document(
        db, company.id, user_id,
        original_filename=package.filename,
        content_type="application/zip",
        content=package.content,
        source=DocumentSource.API,
        trusted=True,   # ZIP пакетът е генериран от системата
    )
    doc.doc_type = DocumentType.OTHER
    doc.notes = f"Пакет за НАП · {period.code} · {provider.name}"

    sub = NraSubmission(
        company_id=company.id,
        period_id=period_id,
        period_code=period.code,
        kind=SubmissionKind.VAT_RETURN,
        status=SubmissionStatus.PREPARED,
        provider_code=provider.code,
        package_document_id=doc.id,
        package_filename=package.filename,
        package_sha256=hashlib.sha256(package.content).hexdigest(),
        package_size=len(package.content),
        package_contents=" | ".join(package.contents)[:500],
        submission_deadline=preview.submission_deadline,
        prepared_by_id=user_id,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def get_submission(db: Session, company_id: uuid.UUID, sub_id: uuid.UUID) -> NraSubmission:
    sub = db.get(NraSubmission, sub_id)
    if sub is None or sub.company_id != company_id:
        raise _err("Подаването не е намерено", status.HTTP_404_NOT_FOUND)
    return sub


def list_submissions(
    db: Session, company_id: uuid.UUID, period_id: uuid.UUID | None = None
) -> list[NraSubmission]:
    stmt = select(NraSubmission).where(NraSubmission.company_id == company_id)
    if period_id is not None:
        stmt = stmt.where(NraSubmission.period_id == period_id)
    return list(db.scalars(stmt.order_by(NraSubmission.created_at.desc())))


def download_package(
    db: Session, company_id: uuid.UUID, sub_id: uuid.UUID
) -> tuple[NraSubmission, bytes]:
    """Изтегляне на пакета (отбелязва се, че е свален)."""
    sub = get_submission(db, company_id, sub_id)
    if sub.package_document_id is None:
        raise _err("Пакетът не е намерен", status.HTTP_404_NOT_FOUND)
    _doc, data = documents_service.get_file(db, company_id, sub.package_document_id)
    if sub.status == SubmissionStatus.PREPARED:
        sub.status = SubmissionStatus.DOWNLOADED
        db.commit()
        db.refresh(sub)
    return sub, data


def mark_submitted(
    db: Session, company_id: uuid.UUID, sub_id: uuid.UUID, data: SubmissionMarkSubmittedIn
) -> NraSubmission:
    """Стъпка 6: потребителят е подал в портала с КЕП (извън системата)."""
    sub = get_submission(db, company_id, sub_id)
    _transition(sub, SubmissionStatus.SUBMITTED_EXTERNALLY)
    sub.submitted_at = data.submitted_at or dt.date.today()
    if data.notes:
        sub.notes = data.notes
    db.commit()
    db.refresh(sub)
    return sub


def import_receipt(
    db: Session,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    sub_id: uuid.UUID,
    filename: str,
    content_type: str,
    content: bytes,
    data: SubmissionReceiptIn,
) -> NraSubmission:
    """Стъпка 7: импортира и съхранява разписката/протокола от НАП."""
    sub = get_submission(db, company_id, sub_id)
    if sub.status in (SubmissionStatus.PREPARED, SubmissionStatus.DOWNLOADED):
        # Разписка има само след реално подаване — отбелязваме го автоматично.
        sub.status = SubmissionStatus.SUBMITTED_EXTERNALLY
        sub.submitted_at = sub.submitted_at or dt.date.today()

    doc = documents_service.create_document(
        db, company_id, user_id,
        original_filename=filename,
        content_type=content_type,
        content=content,
        source=DocumentSource.UPLOAD,
    )
    doc.doc_type = DocumentType.OTHER
    doc.notes = f"Разписка от НАП · {sub.period_code}"

    sub.receipt_document_id = doc.id
    sub.receipt_number = data.receipt_number
    sub.receipt_date = data.receipt_date or dt.date.today()
    sub.receipt_imported_at = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    if data.notes:
        sub.notes = data.notes
    _transition(sub, SubmissionStatus.RECEIPT_IMPORTED)
    _transition(sub, SubmissionStatus.ACCEPTED if data.accepted else SubmissionStatus.REJECTED)
    db.commit()
    db.refresh(sub)
    return sub
