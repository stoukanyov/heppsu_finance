"""Авто-предложение за осчетоводяване на разпознат документ.

Принцип на продукта: AI само предлага, човек потвърждава. Тук се съставя
ЧЕРНОВА (DRAFT) счетоводна статия по данните от `DocumentExtraction`; тя става
реален запис едва след ръчно потвърждение чрез
`POST /accounting/journal-entries/{id}/post`.

Модулът е умишлено консервативен: при липсващи или противоречиви данни връща
`entry=None` и ясни предупреждения, вместо да съчинява статия. Никога не се
създава небалансирана статия.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.accounting import service as accounting_service
from app.modules.accounting.models import (
    Account,
    AccountType,
    EntryStatus,
    JournalEntry,
    JournalType,
    PeriodStatus,
)
from app.modules.accounting.schemas import (
    JournalEntryCreate,
    JournalEntryOut,
    JournalLineIn,
)
from app.modules.ai.llm import get_llm_client
from app.modules.ai.models import DocumentExtraction, ExpenseClassification
from app.modules.ai.schemas import ExpenseClassificationOut, PostingProposalOut
from app.modules.companies.models import Company
from app.modules.counterparties import service as counterparties_service
from app.modules.counterparties.models import Counterparty, CounterpartyType
from app.modules.counterparties.schemas import CounterpartyCreate
from app.modules.counterparties.service import normalize_name
from app.modules.documents import service as documents_service
from app.modules.documents.models import Document, DocumentStatus, DocumentType

ZERO = Decimal("0.00")
_CENT = Decimal("0.01")

# ---- Кодове от стандартния български сметкоплан (accounting.service.STANDARD_BG_CHART) ----
ACC_SUPPLIER = "401"           # Доставчици
ACC_CUSTOMER = "411"           # Клиенти
ACC_VAT_INPUT = "4531"         # Начислен ДДС на покупките (данъчен кредит)
ACC_VAT_OUTPUT = "4532"        # Начислен ДДС на продажбите
ACC_EXPENSE_DEFAULT = "602"    # Разходи за външни услуги
ACC_REVENUE_DEFAULT = "703"    # Приходи от услуги

# Документи, които се третират като покупка (входящи).
_PURCHASE_TYPES = (DocumentType.INVOICE_PURCHASE, DocumentType.RECEIPT)

# Синоними на полетата в extraction.data — моделът/промптът може да ги именува различно.
_ALIASES: dict[str, tuple[str, ...]] = {
    "total": ("total", "total_amount", "amount_total", "grand_total"),
    "net": ("tax_base", "net_amount", "net", "subtotal", "amount_net"),
    "vat": ("vat_amount", "vat", "tax_amount", "amount_vat"),
    "currency": ("currency", "currency_code"),
    "doc_date": ("document_date", "invoice_date", "date", "issue_date"),
    "doc_number": ("document_number", "invoice_number", "number"),
    # Издател на документа — контрагентът при покупка.
    "issuer_name": ("issuer", "supplier_name", "supplier", "counterparty_name", "vendor"),
    "issuer_vat": ("issuer_vat_number", "supplier_vat", "supplier_vat_number", "vat_number"),
    "issuer_eik": ("issuer_eik", "supplier_eik", "eik"),
    # Получател на документа — контрагентът при продажба.
    "recipient_name": ("recipient", "recipient_name", "customer_name", "customer", "buyer", "client_name"),
    "recipient_vat": ("recipient_vat_number", "customer_vat", "customer_vat_number", "buyer_vat"),
    "recipient_eik": ("recipient_eik", "customer_eik", "buyer_eik"),
    "doc_kind": ("document_type", "doc_type", "kind"),
}

# Полета, чиято стойност трябва да е число ≥ 0 при ръчна корекция.
AMOUNT_FIELDS: frozenset[str] = frozenset(
    _ALIASES["total"] + _ALIASES["net"] + _ALIASES["vat"]
) | {"vat_rate", "amount", "unit_price", "quantity", "discount"}

# Полета, чиято стойност трябва да е ISO дата (ГГГГ-ММ-ДД) при ръчна корекция.
DATE_FIELDS: frozenset[str] = frozenset(_ALIASES["doc_date"]) | {
    "due_date",
    "tax_event_date",
    "payment_date",
    "delivery_date",
}


def _q(amount: Decimal) -> Decimal:
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


# ============================ Четене на разпознатите данни ============================
def _flatten(data: dict) -> dict:
    """Обединява `data["fields"]` с горното ниво — толерантно към формата на модела."""
    fields = data.get("fields")
    merged: dict = {k: v for k, v in data.items() if k != "fields"}
    if isinstance(fields, dict):
        merged.update(fields)
    return merged


def _pick(flat: dict, key: str):
    for alias in _ALIASES[key]:
        value = flat.get(alias)
        if value not in (None, ""):
            return value
    return None


def _as_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value).replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return _q(amount)


def _as_date(value) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def latest_extraction(db: Session, doc: Document) -> DocumentExtraction | None:
    """Последното разпознаване за документа (AI или ръчно коригирано)."""
    return db.scalar(
        select(DocumentExtraction)
        .where(DocumentExtraction.document_id == doc.id)
        .order_by(DocumentExtraction.created_at.desc())
    )


# ============================ Помощни справки ============================
def _account_by_code(db: Session, company_id: uuid.UUID, code: str) -> Account | None:
    return db.scalar(
        select(Account).where(
            Account.company_id == company_id,
            Account.code == code,
            Account.is_active.is_(True),
        )
    )


def _find_counterparty(
    db: Session, company_id: uuid.UUID, name: str | None, vat: str | None, eik: str | None
) -> Counterparty | None:
    """Търси контрагент по ДДС номер, ЕИК и накрая по нормализирано наименование."""
    candidates = list(db.scalars(select(Counterparty).where(Counterparty.company_id == company_id)))
    if vat:
        for cp in candidates:
            if cp.vat_number and cp.vat_number.upper() == vat.upper():
                return cp
    if eik:
        for cp in candidates:
            if cp.eik and cp.eik == eik:
                return cp
    if name:
        target = normalize_name(name)
        for cp in candidates:
            if target and normalize_name(cp.name) == target:
                return cp
    return None


def _country_from_vat(vat: str | None, fallback: str) -> str:
    """Държавата се извежда от префикса на ДДС номера (BG203000000 → BG)."""
    if vat:
        prefix = vat.strip()[:2]
        if prefix.isalpha():
            return prefix.upper()
    return (fallback or "BG").upper()[:2]


def _party_data(flat: dict, is_purchase: bool) -> tuple[str | None, str | None, str | None]:
    """Данни за контрагента: при покупка това е издателят, при продажба — получателят."""
    prefix = "issuer" if is_purchase else "recipient"
    name = _pick(flat, f"{prefix}_name")
    vat = _pick(flat, f"{prefix}_vat")
    eik = _pick(flat, f"{prefix}_eik")
    return (
        str(name).strip()[:255] if name else None,
        str(vat).strip()[:20] if vat else None,
        str(eik).strip()[:20] if eik else None,
    )


def _resolve_counterparty(
    db: Session,
    company: Company,
    flat: dict,
    is_purchase: bool,
) -> tuple[Counterparty | None, bool, str | None]:
    """Намира контрагента, а ако липсва — създава го през сервизния слой.

    Връща (контрагент, създаден ли е, име за съобщението).
    """
    name, vat, eik = _party_data(flat, is_purchase)
    cp = _find_counterparty(db, company.id, name, vat, eik)
    if cp is not None:
        return cp, False, cp.name
    if not name and not vat and not eik:
        return None, False, None

    # Име по подразбиране, когато е разпознат само идентификатор.
    display_name = name or f"Контрагент {vat or eik}"
    data = CounterpartyCreate(
        type=CounterpartyType.SUPPLIER if is_purchase else CounterpartyType.CUSTOMER,
        name=display_name,
        eik=eik,
        vat_number=vat,
        country=_country_from_vat(vat, company.country),
        notes="Създаден автоматично от разпознат документ — подлежи на проверка.",
    )
    try:
        cp = counterparties_service.create_counterparty(db, company.id, data)
    except HTTPException:
        # Сервизният слой откри дубликат — ползваме съществуващия запис.
        db.rollback()
        cp = _find_counterparty(db, company.id, name, vat, eik)
        return cp, False, cp.name if cp else display_name
    return cp, True, cp.name


def file_document_to_counterparty(
    db: Session, company: Company, doc: Document
) -> Counterparty | None:
    """Класира документа при неговия контрагент, като го създава при нужда.

    Изпълнява се независимо от осчетоводяването: дори когато статия не може да се
    предложи (липсва сума или дата), сканът трябва да е намираем в досието на
    контрагента. Никога не хвърля — файлирането не бива да проваля сканирането.
    """
    if doc.counterparty_id is not None:
        return db.get(Counterparty, doc.counterparty_id)

    extraction = latest_extraction(db, doc)
    if extraction is None:
        return None

    flat = _flatten(extraction.data or {})
    is_purchase, _guessed = _guess_direction(doc, flat)
    try:
        cp, _created, _display = _resolve_counterparty(db, company, flat, is_purchase)
    except Exception:  # noqa: BLE001 — файлирането е подпомагащо, не блокиращо
        db.rollback()
        return None
    if cp is None:
        return None

    doc.counterparty_id = cp.id
    if doc.doc_type == DocumentType.UNKNOWN:
        doc.doc_type = (
            DocumentType.INVOICE_PURCHASE if is_purchase else DocumentType.INVOICE_SALE
        )
    db.commit()
    db.refresh(doc)
    return cp


def _counterparty_default_account(
    db: Session, company_id: uuid.UUID, cp: Counterparty | None, expected: AccountType
) -> Account | None:
    """Стандартната сметка на контрагента — само ако е аналитична и от очаквания вид."""
    if cp is None or cp.default_account_id is None:
        return None
    account = db.get(Account, cp.default_account_id)
    if account is None or account.company_id != company_id:
        return None
    if account.is_group or not account.is_active or account.type != expected:
        return None
    return account


def _guess_direction(doc: Document, flat: dict) -> tuple[bool, bool]:
    """Връща (покупка?, предположено?) — посоката на документа."""
    if doc.doc_type in _PURCHASE_TYPES:
        return True, False
    if doc.doc_type == DocumentType.INVOICE_SALE:
        return False, False
    kind = str(_pick(flat, "doc_kind") or "").lower()
    if any(word in kind for word in ("продажб", "sale", "издаден", "outgoing")):
        return False, True
    # По подразбиране сканираните документи са входящи (покупка).
    return True, True


# ============================ AI класификация на разход ============================
def _expense_accounts(db: Session, company_id: uuid.UUID) -> list[Account]:
    """Разходните сметки, между които AI може да избира (без обобщаващите)."""
    return list(
        db.scalars(
            select(Account).where(
                Account.company_id == company_id,
                Account.type == AccountType.EXPENSE,
                Account.is_group.is_(False),
            ).order_by(Account.code)
        )
    )


def classify_expense(
    db: Session,
    company: Company,
    user_id: uuid.UUID,
    doc: Document,
    flat: dict,
    party_name: str | None,
) -> tuple[ExpenseClassificationOut | None, Account | None, list[str]]:
    """Пита AI за сметка + данъчно третиране. Връща (класификация, сметка, предупреждения).

    Никога не хвърля: при проблем връща (None, None, [причина]), а осчетоводяването
    продължава с подразбиращата се сметка.
    """
    warnings: list[str] = []
    accounts = _expense_accounts(db, company.id)
    if not accounts:
        return None, None, ["Няма разходни сметки в сметкоплана за AI класификация."]

    context = {
        # Реалната дейност на дружеството е ключова за преценката „свързан с дейността".
        "company_activity": company.activity or "обща стопанска дейност",
        "company_name": company.name,
        "supplier_name": party_name,
        "document_type": str(_pick(flat, "doc_kind") or doc.doc_type.value),
        "document_number": _pick(flat, "doc_number"),
        "total": str(_pick(flat, "total") or ""),
        "vat_amount": str(_pick(flat, "vat") or ""),
        "supplier_vat_number": _pick(flat, "issuer_vat"),
        "currency": _pick(flat, "currency"),
        "notes": doc.notes,
        "is_receipt": doc.doc_type == DocumentType.RECEIPT,
        "available_accounts": [{"code": a.code, "name": a.name} for a in accounts],
    }
    try:
        raw = get_llm_client().classify_expense(context)
    except Exception as exc:  # noqa: BLE001 — класификацията е подпомагаща, не блокираща
        return None, None, [f"AI класификацията не бе достъпна: {type(exc).__name__}."]

    code = str(raw.get("account_code") or "").strip()
    account = next((a for a in accounts if a.code == code), None)
    if account is None:
        warnings.append(
            f"AI предложи сметка „{code}“, която липсва в сметкоплана — ползвана е подразбиращата се."
        )

    try:
        classification = ExpenseClassificationOut(
            account_code=code or ACC_EXPENSE_DEFAULT,
            account_rationale=raw.get("account_rationale"),
            is_deductible=bool(raw.get("is_deductible", True)),
            deductible_ratio=raw.get("deductible_ratio"),
            tax_rationale=str(raw.get("tax_rationale") or "Няма обосновка."),
            vat_credit=str(raw.get("vat_credit") or "UNKNOWN").upper(),
            vat_rationale=raw.get("vat_rationale"),
            expense_category=raw.get("expense_category"),
            confidence=float(raw.get("confidence") or 0),
            warnings=list(raw.get("warnings") or []),
        )
    except Exception:  # noqa: BLE001 — непълен отговор от модела
        return None, account, ["AI класификацията върна непълен резултат."]

    warnings.extend(classification.warnings)
    if not classification.is_deductible:
        warnings.append("AI преценява разхода като ДАНЪЧНО НЕПРИЗНАТ — изисква преглед.")

    db.add(
        ExpenseClassification(
            company_id=company.id,
            document_id=doc.id,
            model=settings.AI_MODEL if settings.resolved_ai_provider == "anthropic" else "stub",
            account_code=classification.account_code[:20],
            account_rationale=(classification.account_rationale or None),
            is_deductible=classification.is_deductible,
            deductible_ratio=(
                Decimal(str(classification.deductible_ratio))
                if classification.deductible_ratio is not None else None
            ),
            tax_rationale=classification.tax_rationale[:1000],
            vat_credit=classification.vat_credit[:10],
            vat_rationale=(classification.vat_rationale or None),
            expense_category=(classification.expense_category or None),
            confidence=Decimal(str(round(classification.confidence, 3))),
            warnings=classification.warnings or None,
            created_by_id=user_id,
        )
    )
    return classification, account, warnings


# ============================ Основна логика ============================
def _existing_proposal(
    db: Session, doc: Document, confidence: float
) -> PostingProposalOut | None:
    """Идемпотентност: вече свързана статия се връща вместо да се създава втора."""
    if doc.journal_entry_id is None:
        return None
    entry = db.get(JournalEntry, doc.journal_entry_id)
    if entry is None or entry.company_id != doc.company_id:
        return None

    warnings: list[str] = []
    if entry.status == EntryStatus.DRAFT:
        rationale = "Документът вече има предложена чернова — връща се съществуващата статия."
    else:
        rationale = "Документът вече е свързан със счетоводна статия — нова не се създава."
        warnings.append(f"Статията вече не е чернова (статус {entry.status.value}).")
    return PostingProposalOut(
        entry=JournalEntryOut.model_validate(entry),
        confidence=confidence,
        rationale=rationale,
        warnings=warnings,
    )


def current_proposal(
    db: Session, doc: Document, confidence: float = 0.0
) -> PostingProposalOut | None:
    """Вече свързаната статия като предложение — без да се създава нова.

    Ползва се при корекция без преизчисление: мобилното пак получава какво стои
    в момента зад документа.
    """
    return _existing_proposal(db, doc, confidence)


def discard_draft_proposal(db: Session, doc: Document) -> bool:
    """Изтрива черновата, предложена по старите данни, и я откача от документа.

    Връща True, ако е имало какво да се изтрие. Осчетоводена статия НИКОГА не се
    пипа — тя се коригира само със сторно. Редовете падат заедно със статията
    (delete-orphan), така че сираци не остават; `doc.journal_entry_id` се нулира,
    за да може `propose_posting` да предложи наново, без да се самоблокира от
    идемпотентността.
    """
    if doc.journal_entry_id is None:
        return False
    entry = db.get(JournalEntry, doc.journal_entry_id)
    doc.journal_entry_id = None
    if entry is None or entry.company_id != doc.company_id:
        db.commit()
        return False
    if entry.status != EntryStatus.DRAFT:
        # Защитна мрежа: извикващият вече е проверил статуса.
        doc.journal_entry_id = entry.id
        return False
    db.delete(entry)
    db.commit()
    return True


def _fail(rationale: str, warnings: list[str], confidence: float) -> PostingProposalOut:
    return PostingProposalOut(
        entry=None, confidence=confidence, rationale=rationale, warnings=warnings
    )


def _score(base: float, warnings: list[str]) -> float:
    """Увереността пада с всяко направено предположение."""
    value = base * (1 - 0.1 * len(warnings))
    return round(max(0.0, min(1.0, value)), 4)


def propose_posting(
    db: Session, company: Company, user_id: uuid.UUID, doc_id: uuid.UUID
) -> PostingProposalOut:
    """Съставя предложение за счетоводна статия (DRAFT) по разпознатите данни."""
    doc = documents_service.get_document(db, company.id, doc_id)
    extraction = latest_extraction(db, doc)

    if extraction is None:
        return _fail(
            "Няма разпознати данни за този документ.",
            ["Липсва AI извличане — стартирай POST /ai/documents/{id}/extract."],
            0.0,
        )

    data = extraction.data or {}
    flat = _flatten(data)
    base_confidence = float(data.get("overall_confidence") or 0)
    warnings: list[str] = []

    existing = _existing_proposal(db, doc, _score(base_confidence, warnings))
    if existing is not None:
        return existing

    # ---- Посока на операцията ----
    is_purchase, guessed = _guess_direction(doc, flat)
    if guessed:
        warnings.append(
            "Видът на документа е предположен ({}).".format("покупка" if is_purchase else "продажба")
        )

    # ---- Суми ----
    total = _as_decimal(_pick(flat, "total"))
    net = _as_decimal(_pick(flat, "net"))
    vat = _as_decimal(_pick(flat, "vat"))
    if total is None and net is not None:
        total = _q(net + (vat or ZERO))
        warnings.append("Общата сума е изчислена от данъчната основа и ДДС.")
    if net is None and total is not None:
        net = _q(total - (vat or ZERO))
        if vat is not None:
            warnings.append("Данъчната основа е изчислена като обща сума минус ДДС.")
    if vat is None:
        vat = ZERO
        warnings.append("Липсва разпознат ДДС — предположено е 0.00.")

    if total is None or total <= ZERO:
        warnings.append("Липсва обща сума на документа.")
        return _fail(
            "Не може да се предложи статия без разпозната сума.",
            warnings,
            _score(base_confidence, warnings),
        )

    # ---- ДДС третиране ----
    with_vat = vat > ZERO and company.is_vat_registered
    if vat > ZERO and not company.is_vat_registered:
        warnings.append(
            "Компанията не е ДДС регистрирана — ДДС не се отделя и влиза в стойността."
        )
        vat = ZERO
    if with_vat and net is not None and _q(net + vat) != total:
        warnings.append("Основа + ДДС не съвпадат с общата сума — основата е изчислена наново.")
    if with_vat:
        net = _q(total - vat)
    else:
        net = total

    # ---- Дата и период ----
    doc_date = _as_date(_pick(flat, "doc_date"))
    if doc_date is None:
        warnings.append("Липсва дата на документа.")
        return _fail(
            "Не може да се определи счетоводен период без дата на документа.",
            warnings,
            _score(base_confidence, warnings),
        )
    period = accounting_service.find_period_for_date(db, company.id, doc_date)
    if period is None:
        warnings.append(f"Няма счетоводен период за {doc_date.isoformat()}.")
        return _fail(
            "Липсва счетоводен период — създай фискална година за годината на документа.",
            warnings,
            _score(base_confidence, warnings),
        )
    if period.status not in (PeriodStatus.OPEN, PeriodStatus.RESTRICTED):
        warnings.append(f"Периодът {period.code} е със статус {period.status.value}.")
        return _fail(
            "Периодът не е отворен за осчетоводяване.",
            warnings,
            _score(base_confidence, warnings),
        )

    # ---- Валута и курс ----
    raw_currency = str(_pick(flat, "currency") or "").strip().upper()
    currency = raw_currency if len(raw_currency) == 3 else company.base_currency
    if raw_currency and len(raw_currency) != 3:
        warnings.append(f"Неразпозната валута „{raw_currency}“ — ползвана е базовата.")
    exchange_rate = Decimal("1.000000")
    if currency != company.base_currency:
        warnings.append(
            f"Няма валутен курс {currency}/{company.base_currency} — ползван е курс 1.000000."
        )

    # ---- Контрагент (търси се; ако липсва — създава се автоматично) ----
    party_name, _party_vat, _party_eik = _party_data(flat, is_purchase)
    cp, cp_created, cp_display = _resolve_counterparty(db, company, flat, is_purchase)
    if cp_created:
        warnings.append(
            f"Контрагентът «{cp_display}» е създаден автоматично от документа — провери данните му."
        )
    elif cp is None:
        warnings.append(
            "Контрагентът не е намерен в регистъра и няма достатъчно данни за създаване — "
            "статията е по обща разчетна сметка."
        )
    party_name = party_name or (cp.name if cp is not None else None)

    # ---- Сметки ----
    doc_number = str(_pick(flat, "doc_number") or "")[:50] or None
    if is_purchase:
        result_type = AccountType.EXPENSE
        default_code = ACC_EXPENSE_DEFAULT
        settlement_code = ACC_SUPPLIER
        vat_code = ACC_VAT_INPUT
    else:
        result_type = AccountType.REVENUE
        default_code = ACC_REVENUE_DEFAULT
        settlement_code = ACC_CUSTOMER
        vat_code = ACC_VAT_OUTPUT

    # ---- AI класификация (само за разходи): сметка + данъчно третиране ----
    classification: ExpenseClassificationOut | None = None
    ai_account: Account | None = None
    if is_purchase:
        classification, ai_account, cls_warnings = classify_expense(
            db, company, user_id, doc, flat, party_name
        )
        warnings.extend(cls_warnings)
        # Без право на данъчен кредит → ДДС не се отделя, а влиза в стойността на разхода.
        if with_vat and classification is not None and classification.vat_credit == "NONE":
            warnings.append(
                "Няма право на данъчен кредит — ДДС влиза в стойността на разхода."
            )
            with_vat = False
            net = total
            vat = ZERO

    # Приоритет: изрично зададената сметка на контрагента > AI предложение > подразбиране.
    result_account = _counterparty_default_account(db, company.id, cp, result_type) or ai_account
    if result_account is None:
        result_account = _account_by_code(db, company.id, default_code)
        warnings.append(
            "{} сметка е предположена ({}).".format(
                "Разходната" if is_purchase else "Приходната", default_code
            )
        )
    settlement_account = _account_by_code(db, company.id, settlement_code)
    vat_account = _account_by_code(db, company.id, vat_code) if with_vat else None

    missing = [
        code
        for code, account in ((default_code, result_account), (settlement_code, settlement_account))
        if account is None
    ]
    if with_vat and vat_account is None:
        missing.append(vat_code)
    if missing:
        warnings.append(f"Липсват сметки в сметкоплана: {', '.join(sorted(set(missing)))}.")
        return _fail(
            "Сметкопланът не е инициализиран — стартирай POST /accounting/chart/seed.",
            warnings,
            _score(base_confidence, warnings),
        )

    # ---- Редове на статията ----
    if is_purchase:
        lines = [JournalLineIn(account_id=result_account.id, debit=net, credit=ZERO,
                               description=party_name or None)]
        if with_vat:
            lines.append(JournalLineIn(account_id=vat_account.id, debit=vat, credit=ZERO,
                                       description="ДДС покупки"))
        lines.append(JournalLineIn(account_id=settlement_account.id, debit=ZERO, credit=total,
                                   description=party_name or None))
        journal = JournalType.PURCHASES
        doc_label = "Фактура (покупка)" if doc.doc_type != DocumentType.RECEIPT else "Касова бележка"
        description = f"Покупка по документ {doc_number or '—'}"
    else:
        lines = [JournalLineIn(account_id=settlement_account.id, debit=total, credit=ZERO,
                               description=party_name or None)]
        lines.append(JournalLineIn(account_id=result_account.id, debit=ZERO, credit=net,
                                   description=party_name or None))
        if with_vat:
            lines.append(JournalLineIn(account_id=vat_account.id, debit=ZERO, credit=vat,
                                       description="ДДС продажби"))
        journal = JournalType.SALES
        doc_label = "Фактура (продажба)"
        description = f"Продажба по документ {doc_number or '—'}"

    # ---- Проверка на баланса ПРЕДИ запис ----
    total_debit = _q(sum((line.debit for line in lines), ZERO))
    total_credit = _q(sum((line.credit for line in lines), ZERO))
    if total_debit != total_credit:
        warnings.append(
            f"Небалансирано предложение: дебит {total_debit} ≠ кредит {total_credit}."
        )
        return _fail(
            "Разпознатите суми не дават балансирана статия — нужна е ръчна корекция.",
            warnings,
            _score(base_confidence, warnings),
        )

    try:
        entry = accounting_service.create_entry(
            db,
            company,
            user_id,
            JournalEntryCreate(
                document_date=doc_date,
                journal=journal,
                document_type=doc_label,
                document_number=doc_number,
                tax_event_date=doc_date,
                currency=currency,
                exchange_rate=exchange_rate,
                description=description[:500],
                lines=lines,
            ),
        )
    except HTTPException as exc:
        db.rollback()
        warnings.append(str(exc.detail))
        return _fail(
            "Счетоводното ядро отказа предложената статия.",
            warnings,
            _score(base_confidence, warnings),
        )

    # ---- Връзки към документа ----
    doc.journal_entry_id = entry.id
    if cp is not None and doc.counterparty_id is None:
        doc.counterparty_id = cp.id
    if doc.doc_type == DocumentType.UNKNOWN:
        doc.doc_type = DocumentType.INVOICE_PURCHASE if is_purchase else DocumentType.INVOICE_SALE
    if DocumentStatus.PROPOSED in documents_service.ALLOWED_TRANSITIONS.get(doc.status, set()):
        doc.status = DocumentStatus.PROPOSED
    else:
        warnings.append(
            f"Статусът на документа остава {doc.status.value} — преход към PROPOSED не е допустим."
        )
    db.commit()
    db.refresh(entry)

    # ---- Авто-осчетоводяване (по политика, при достатъчна увереност) ----
    confidence = _score(base_confidence, warnings)
    auto_posted = False
    if settings.AUTO_POST_DOCUMENTS and confidence >= settings.AUTO_POST_MIN_CONFIDENCE:
        try:
            accounting_service.post_entry(db, company.id, entry.id, user_id)
            auto_posted = True
            # Жизненият цикъл на документа: PROPOSED → APPROVED → POSTED.
            for target in (DocumentStatus.APPROVED, DocumentStatus.POSTED):
                if target in documents_service.ALLOWED_TRANSITIONS.get(doc.status, set()):
                    doc.status = target
            db.commit()
            db.refresh(entry)
        except HTTPException as exc:
            db.rollback()
            warnings.append(f"Авто-осчетоводяването не бе възможно: {exc.detail}")
    elif settings.AUTO_POST_DOCUMENTS:
        warnings.append(
            f"Увереност {confidence:.2f} под прага {settings.AUTO_POST_MIN_CONFIDENCE:.2f} — "
            "статията остава чернова за потвърждение."
        )

    return PostingProposalOut(
        entry=JournalEntryOut.model_validate(entry),
        confidence=confidence,
        rationale=_rationale(
            is_purchase=is_purchase,
            doc_number=doc_number,
            party_name=party_name,
            result_account=result_account,
            settlement_account=settlement_account,
            vat_account=vat_account,
            net=net,
            vat=vat,
            total=total,
            currency=currency,
            classification=classification,
            auto_posted=auto_posted,
        ),
        warnings=warnings,
        classification=classification,
        auto_posted=auto_posted,
    )


def _rationale(
    *,
    is_purchase: bool,
    doc_number: str | None,
    party_name: str | None,
    result_account: Account,
    settlement_account: Account,
    vat_account: Account | None,
    net: Decimal,
    vat: Decimal,
    total: Decimal,
    currency: str,
    classification: ExpenseClassificationOut | None = None,
    auto_posted: bool = False,
) -> str:
    """Кратко обяснение на български защо са избрани точно тези сметки."""
    who = f" от {party_name}" if party_name else ""
    head = "Покупка" if is_purchase else "Продажба"
    doc = f" по документ {doc_number}" if doc_number else ""
    if is_purchase:
        debit = f"Дт {result_account.code} ({result_account.name}) {net}"
        if vat_account is not None:
            debit += f" и Дт {vat_account.code} ({vat_account.name}) {vat}"
        credit = f"Кт {settlement_account.code} ({settlement_account.name}) {total}"
    else:
        debit = f"Дт {settlement_account.code} ({settlement_account.name}) {total}"
        credit = f"Кт {result_account.code} ({result_account.name}) {net}"
        if vat_account is not None:
            credit += f" и Кт {vat_account.code} ({vat_account.name}) {vat}"
    parts = [f"{head}{doc}{who}: {debit} / {credit} {currency}."]
    if classification is not None:
        status = "признат" if classification.is_deductible else "НЕПРИЗНАТ"
        parts.append(f"Данъчно третиране: {status} разход — {classification.tax_rationale}")
        if classification.vat_rationale:
            parts.append(f"ДДС: {classification.vat_rationale}")
    parts.append(
        "Статията е осчетоводена автоматично." if auto_posted
        else "Статията е чернова за потвърждение."
    )
    return " ".join(parts)


def safe_propose_posting(
    db: Session, company: Company, user_id: uuid.UUID, doc_id: uuid.UUID
) -> PostingProposalOut | None:
    """Вариант „най-добро усилие" за сканиране: провал на предложението не проваля скана."""
    try:
        return propose_posting(db, company, user_id, doc_id)
    except Exception:  # noqa: BLE001 — предложението е опционално, сканът има приоритет
        db.rollback()
        return None
