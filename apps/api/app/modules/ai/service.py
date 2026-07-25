"""Бизнес логика на AI модула: OCR извличане, AI CFO анализ, Command Center.

Принцип: AI само предлага. Извличането записва разпознати данни и маркира документа
за човешка проверка — не го осчетоводява. Анализите са четими и не променят данни.
"""
import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.accounting.models import AccountType
from app.modules.ai.llm import get_llm_client
from app.modules.ai.models import DocumentExtraction
from app.modules.ai.schemas import CfoAnswer, CommandCenterOut
from app.modules.companies.models import Company
from app.modules.documents import service as documents_service
from app.modules.documents import storage as documents_storage
from app.modules.documents.models import Document, DocumentStatus
from app.modules.reports import service as reports_service

ZERO = Decimal("0.00")
_REVIEW_THRESHOLD = 0.75  # под тази обща увереност документът отива за ръчна проверка

# Статуси на документи, които все още чакат обработка.
_PENDING_STATUSES = (
    DocumentStatus.RECEIVED,
    DocumentStatus.OCR_PROCESSING,
    DocumentStatus.RECOGNIZED,
    DocumentStatus.NEEDS_REVIEW,
    DocumentStatus.MISSING_DATA,
    DocumentStatus.POTENTIAL_DUPLICATE,
)


def financial_snapshot(
    db: Session,
    company: Company,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> dict:
    """Ключови финансови показатели, агрегирани от оборотната ведомост."""
    tb = reports_service.trial_balance(db, company.id, date_from, date_to)
    cash = revenue = expenses = receivables = payables = ZERO
    for row in tb.rows:
        bal = row.closing_balance
        if row.code.startswith("50"):
            cash += bal
        if row.type == AccountType.REVENUE:
            revenue += -bal  # приходите имат кредитно (отрицателно) салдо
        elif row.type == AccountType.EXPENSE:
            expenses += bal
        if row.code == "411":
            receivables += bal
        elif row.code == "401":
            payables += -bal  # задълженията имат кредитно салдо
    return {
        "currency": company.base_currency,
        "cash": cash,
        "revenue": revenue,
        "expenses": expenses,
        "profit": revenue - expenses,
        "receivables": receivables,
        "payables": payables,
    }


def extract_document(
    db: Session, company: Company, user_id: uuid.UUID, doc_id: uuid.UUID
) -> DocumentExtraction:
    doc = documents_service.get_document(db, company.id, doc_id)
    content = documents_storage.read_file(doc.storage_path)

    llm = get_llm_client()
    data = llm.extract_document(content, doc.content_type, doc.original_filename)

    extraction = DocumentExtraction(
        company_id=company.id,
        document_id=doc.id,
        model=settings.AI_MODEL if settings.resolved_ai_provider == "anthropic" else "stub",
        data=data,
        created_by_id=user_id,
    )
    db.add(extraction)

    # Маркираме документа според увереността — но НЕ го осчетоводяваме.
    confidence = float(data.get("overall_confidence") or 0)
    doc.status = (
        DocumentStatus.RECOGNIZED if confidence >= _REVIEW_THRESHOLD else DocumentStatus.NEEDS_REVIEW
    )
    db.commit()
    db.refresh(extraction)
    return extraction


def _resolve_period_range(
    db: Session, company_id: uuid.UUID, period_id: uuid.UUID | None
) -> tuple[dt.date | None, dt.date | None]:
    if period_id is None:
        return None, None
    from app.modules.accounting.models import AccountingPeriod

    period = db.get(AccountingPeriod, period_id)
    if period is None or period.company_id != company_id:
        return None, None
    return period.start_date, period.end_date


def cfo_analysis(
    db: Session, company: Company, question: str | None, period_id: uuid.UUID | None
) -> CfoAnswer:
    date_from, date_to = _resolve_period_range(db, company.id, period_id)
    snapshot = financial_snapshot(db, company, date_from, date_to)

    llm = get_llm_client()
    result = llm.financial_analysis(snapshot, question)

    return CfoAnswer(
        summary=result.get("summary", ""),
        explanation=result.get("explanation", ""),
        recommendations=result.get("recommendations", []),
        risks=result.get("risks", []),
        assumptions=result.get("assumptions", []),
        confidence=result.get("confidence", "low"),
        context=snapshot,
    )


def command_center(db: Session, company: Company) -> CommandCenterOut:
    snapshot = financial_snapshot(db, company)
    pending = db.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.company_id == company.id, Document.status.in_(_PENDING_STATUSES))
    ) or 0

    llm = get_llm_client()
    analysis = llm.financial_analysis(
        {**snapshot, "pending_documents": pending},
        "Направи кратък преглед на финансовото състояние и посочи приоритетни действия и рискове.",
    )

    return CommandCenterOut(
        company_name=company.name,
        currency=snapshot["currency"],
        cash=snapshot["cash"],
        revenue=snapshot["revenue"],
        expenses=snapshot["expenses"],
        profit=snapshot["profit"],
        receivables=snapshot["receivables"],
        payables=snapshot["payables"],
        pending_documents=pending,
        summary=analysis.get("summary", ""),
        recommendations=analysis.get("recommendations", []),
        risks=analysis.get("risks", []),
    )
