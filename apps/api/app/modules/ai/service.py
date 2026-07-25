"""Бизнес логика на AI модула: OCR извличане, ръчна корекция, AI CFO, Command Center.

Принцип: AI само предлага. Извличането записва разпознати данни и маркира документа
за човешка проверка — не го осчетоводява. Анализите са четими и не променят данни.
"""
import datetime as dt
import uuid
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.accounting.models import AccountType, EntryStatus, JournalEntry
from app.modules.ai.llm import get_llm_client
from app.modules.ai.models import DocumentExtraction
from app.modules.ai.schemas import CfoAnswer, CommandCenterOut, PostingProposalOut
from app.modules.companies.models import Company
from app.modules.documents import service as documents_service
from app.modules.documents import storage as documents_storage
from app.modules.documents.models import Document, DocumentStatus
from app.modules.reports import service as reports_service

ZERO = Decimal("0.00")
_REVIEW_THRESHOLD = 0.75  # под тази обща увереност документът отива за ръчна проверка

# Увереност на поле, което човек е коригирал ръчно — то вече не е AI предположение.
HUMAN_CONFIDENCE = 1.0
_MAX_CORRECTION_HISTORY = 20  # пазим последните корекции като одитна следа


def _err(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


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


# ============================ Ръчна корекция на разпознатите данни ============================
def _validate_amount(name: str, value) -> float:
    """Сумите трябва да са числа ≥ 0; приема се и текст („1 234,56")."""
    if isinstance(value, bool):
        raise _err(f"Полето „{name}“ трябва да е число ≥ 0, а не да/не стойност.")
    if isinstance(value, (int, float, Decimal)):
        amount = Decimal(str(value))
    elif isinstance(value, str):
        try:
            amount = Decimal(value.strip().replace(" ", "").replace(" ", "").replace(",", "."))
        except (InvalidOperation, ValueError):
            raise _err(f"Полето „{name}“ трябва да е число ≥ 0 (получено „{value}“).")
    else:
        raise _err(f"Полето „{name}“ трябва да е число ≥ 0.")
    if not amount.is_finite():
        raise _err(f"Полето „{name}“ трябва да е крайно число ≥ 0 (получено „{value}“).")
    if amount < 0:
        raise _err(f"Полето „{name}“ не може да е отрицателно (получено „{value}“).")
    return float(amount)


def _validate_date(name: str, value) -> str:
    """Датите се приемат само в ISO формат ГГГГ-ММ-ДД и се нормализират."""
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        for candidate in (text, text[:10]):
            try:
                return dt.date.fromisoformat(candidate).isoformat()
            except ValueError:
                continue
    raise _err(
        f"Полето „{name}“ трябва да е дата във формат ГГГГ-ММ-ДД (получено „{value}“)."
    )


def _validate_correction(raw: dict) -> dict:
    """Проверява и нормализира подадените за корекция полета.

    При невалидна стойност съобщението казва точно кое поле е сгрешено — коригиращият
    е човек с телефон в ръка, не програмист.
    """
    from app.modules.ai import posting  # локален импорт: без цикъл между AI под-модулите

    if not isinstance(raw, dict) or not raw:
        raise _err("Няма подадени полета за корекция.")

    cleaned: dict = {}
    for key, value in raw.items():
        name = str(key).strip()
        if not name:
            raise _err("Празно име на поле в корекцията.")
        if len(name) > 100:
            raise _err(f"Непознато поле с твърде дълго име: „{name[:50]}…“.")
        if value is None:
            cleaned[name] = None            # изрично изчистване на поле
        elif name in posting.AMOUNT_FIELDS:
            cleaned[name] = _validate_amount(name, value)
        elif name in posting.DATE_FIELDS:
            cleaned[name] = _validate_date(name, value)
        elif isinstance(value, str):
            cleaned[name] = value.strip()
        elif isinstance(value, (int, float, bool)):
            cleaned[name] = value
        else:
            raise _err(f"Полето „{name}“ трябва да е текст, число или дата.")
    return cleaned


def _recompute_overall(data: dict) -> float:
    """Обща увереност, в която ръчно потвърдените полета тежат с 1.0.

    Средно аритметично на увереността по попълнените полета; за поле без собствена
    оценка се ползва първоначалната обща увереност на модела. Резултатът никога не е
    по-нисък от изходния — човешка корекция не бива да сваля доверието.
    """
    fields = data.get("fields") or {}
    per_field = data.get("field_confidence") or {}
    corrected = set(data.get("corrected_fields") or [])
    base = _as_float(data.get("ai_overall_confidence"), _as_float(data.get("overall_confidence"), 0.0))

    scores: list[float] = []
    for key, value in fields.items():
        if key in corrected:
            scores.append(HUMAN_CONFIDENCE)
        elif value not in (None, ""):
            scores.append(min(max(_as_float(per_field.get(key), base), 0.0), 1.0))
    if not scores:
        return round(base, 4)
    return round(min(max(base, sum(scores) / len(scores)), 1.0), 4)


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _guard_not_posted(db: Session, doc: Document) -> None:
    """Осчетоводен документ не се коригира — корекцията му е сторно."""
    message = "Документът вече е осчетоводен — корекция става само със сторно."
    if doc.status in (DocumentStatus.POSTED, DocumentStatus.ARCHIVED):
        raise _err(message, status.HTTP_409_CONFLICT)
    if doc.journal_entry_id is None:
        return
    entry = db.get(JournalEntry, doc.journal_entry_id)
    if entry is not None and entry.status != EntryStatus.DRAFT:
        raise _err(message, status.HTTP_409_CONFLICT)


# Ранни статуси, от които PROPOSED е недостижим по `ALLOWED_TRANSITIONS`, но
# NEEDS_REVIEW е — след ръчна корекция документът именно чака преглед/предложение.
_UNBLOCK_FROM = (
    DocumentStatus.RECEIVED,
    DocumentStatus.OCR_PROCESSING,
    DocumentStatus.MISSING_DATA,
    DocumentStatus.POTENTIAL_DUPLICATE,
)


def _unblock_lifecycle(db: Session, doc: Document) -> None:
    """Отпушва жизнения цикъл след корекция, без да нарушава `ALLOWED_TRANSITIONS`.

    Излизането от NEEDS_REVIEW не е ръчно решение: то става, когато корекцията е
    добавила достатъчно данни и предложението успее — тогава `propose_posting`
    премества документа в PROPOSED. Тук само вдигаме ранните статуси до
    NEEDS_REVIEW, за да е този преход изобщо възможен.
    """
    target = DocumentStatus.NEEDS_REVIEW
    if doc.status in _UNBLOCK_FROM and target in documents_service.ALLOWED_TRANSITIONS.get(
        doc.status, set()
    ):
        doc.status = target
        db.commit()


def correct_extraction(
    db: Session,
    company: Company,
    user_id: uuid.UUID,
    doc_id: uuid.UUID,
    fields: dict,
    recalculate: bool = True,
) -> tuple[Document, DocumentExtraction, PostingProposalOut | None]:
    """Ръчна корекция на разпознатите данни + (по избор) ново предложение за статия.

    Подадените полета се СЛИВАТ върху `data["fields"]` — неподадените се пазят. Всяко
    коригирано поле се маркира като човешко (`field_confidence = 1.0` и запис в
    `corrected_fields`), за да не сваля повече общата увереност. Ако вече има чернова,
    тя се изтрива и се предлага наново по коригираните данни; осчетоводена статия не се
    пипа — тогава се връща 409.
    """
    from app.modules.ai import posting  # локален импорт: без цикъл между AI под-модулите

    doc = documents_service.get_document(db, company.id, doc_id)
    _guard_not_posted(db, doc)
    cleaned = _validate_correction(fields)

    extraction = posting.latest_extraction(db, doc)
    if extraction is None:
        # Няма AI разпознаване (или е било невъзможно) — корекцията става първи запис.
        extraction = DocumentExtraction(
            company_id=company.id,
            document_id=doc.id,
            model="human",
            data={
                "fields": {},
                "field_confidence": {},
                "overall_confidence": 0.0,
                "notes": "Данните са въведени ръчно, без AI разпознаване.",
            },
            created_by_id=user_id,
        )
        db.add(extraction)

    data = dict(extraction.data or {})
    # Пази се какво е казал моделът, преди човекът да се намеси.
    data.setdefault("ai_overall_confidence", _as_float(data.get("overall_confidence"), 0.0))

    merged = dict(data.get("fields") or {})
    merged.update(cleaned)
    data["fields"] = merged

    per_field = dict(data.get("field_confidence") or {})
    corrected = list(data.get("corrected_fields") or [])
    for key in cleaned:
        per_field[key] = HUMAN_CONFIDENCE
        if key not in corrected:
            corrected.append(key)
    data["field_confidence"] = per_field
    data["corrected_fields"] = sorted(corrected)

    history = list(data.get("corrections") or [])
    history.append(
        {
            "at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "by": str(user_id),
            "fields": sorted(cleaned),
        }
    )
    data["corrections"] = history[-_MAX_CORRECTION_HISTORY:]
    data["overall_confidence"] = _recompute_overall(data)

    extraction.data = data   # нов dict → SQLAlchemy вижда промяната в JSON колоната
    db.commit()
    db.refresh(extraction)
    db.refresh(doc)

    _unblock_lifecycle(db, doc)

    if recalculate:
        posting.discard_draft_proposal(db, doc)
        proposal = posting.safe_propose_posting(db, company, user_id, doc.id)
    else:
        proposal = posting.current_proposal(
            db, doc, _as_float(data.get("overall_confidence"), 0.0)
        )

    db.refresh(doc)
    db.refresh(extraction)
    return doc, extraction, proposal


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
