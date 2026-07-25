"""Бизнес логика на банковия модул: импорт, дедупликация, съгласуване."""
import hashlib
import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounting.models import Account, EntryStatus, JournalEntry
from app.modules.banking.models import (
    ZERO,
    BankAccount,
    BankTransaction,
    BankTransactionMatch,
    BankTxStatus,
)
from app.modules.banking.schemas import (
    BankAccountCreate,
    BankTransactionIn,
    ImportResult,
    MatchSuggestion,
)
from app.modules.companies.models import Company

_CENT = Decimal("0.01")


def _err(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


# ============================ Банкови сметки ============================
def create_bank_account(db: Session, company_id: uuid.UUID, data: BankAccountCreate) -> BankAccount:
    if data.gl_account_id is not None:
        account = db.get(Account, data.gl_account_id)
        if account is None or account.company_id != company_id:
            raise _err("Счетоводната сметка не съществува в тази компания")
    acc = BankAccount(
        company_id=company_id,
        name=data.name,
        iban=data.iban.replace(" ", "").upper() if data.iban else None,
        bank_name=data.bank_name,
        currency=data.currency.upper(),
        gl_account_id=data.gl_account_id,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


def list_bank_accounts(db: Session, company_id: uuid.UUID) -> list[BankAccount]:
    return list(
        db.scalars(
            select(BankAccount).where(BankAccount.company_id == company_id).order_by(BankAccount.name)
        )
    )


def _get_account(db: Session, company_id: uuid.UUID, account_id: uuid.UUID) -> BankAccount:
    acc = db.get(BankAccount, account_id)
    if acc is None or acc.company_id != company_id:
        raise _err("Банковата сметка не е намерена", status.HTTP_404_NOT_FOUND)
    return acc


# ============================ Импорт ============================
def _dedup_key(account_id: uuid.UUID, item: BankTransactionIn) -> str:
    if item.external_id:
        return item.external_id[:64]
    raw = f"{account_id}|{item.booking_date}|{item.amount}|{item.reference or ''}|{item.description or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def import_transactions(
    db: Session, company: Company, account_id: uuid.UUID, items: list[BankTransactionIn]
) -> ImportResult:
    account = _get_account(db, company.id, account_id)
    existing = set(
        db.scalars(
            select(BankTransaction.dedup_key).where(BankTransaction.bank_account_id == account.id)
        )
    )
    imported = 0
    duplicates = 0
    for item in items:
        key = _dedup_key(account.id, item)
        if key in existing:
            duplicates += 1
            continue
        existing.add(key)
        db.add(
            BankTransaction(
                company_id=company.id,
                bank_account_id=account.id,
                booking_date=item.booking_date,
                value_date=item.value_date,
                amount=item.amount,
                currency=(item.currency or account.currency).upper(),
                counterparty_name=item.counterparty_name,
                counterparty_iban=item.counterparty_iban,
                reference=item.reference,
                description=item.description,
                dedup_key=key,
                status=BankTxStatus.UNMATCHED,
            )
        )
        imported += 1
    db.commit()
    return ImportResult(imported=imported, duplicates=duplicates)


def _parse_amount(raw: str, decimal_comma: bool) -> Decimal:
    s = raw.strip().replace(" ", "").replace(" ", "")
    if decimal_comma:  # европейски формат "1.234,56"
        s = s.replace(".", "").replace(",", ".")
    else:  # "1,234.56"
        s = s.replace(",", "")
    return Decimal(s)


def import_csv(
    db: Session,
    company: Company,
    account_id: uuid.UUID,
    content: bytes,
    date_column: str,
    amount_column: str,
    reference_column: str | None,
    description_column: str | None,
    delimiter: str,
    date_format: str,
    decimal_comma: bool,
) -> ImportResult:
    """Парсва CSV банково извлечение чрез съпоставяне на колони и импортира движенията."""
    import csv
    import datetime as dt
    import io

    _get_account(db, company.id, account_id)  # валидира достъпа
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1251", errors="replace")  # някои БГ банки ползват Windows-1251

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if reader.fieldnames is None or date_column not in reader.fieldnames or amount_column not in reader.fieldnames:
        raise _err(f"CSV трябва да съдържа колони: {date_column}, {amount_column}")

    items: list[BankTransactionIn] = []
    for i, row in enumerate(reader, start=2):  # ред 1 е заглавен
        raw_date = (row.get(date_column) or "").strip()
        raw_amount = (row.get(amount_column) or "").strip()
        if not raw_date or not raw_amount:
            continue
        try:
            booking = dt.datetime.strptime(raw_date, date_format).date()
            amount = _parse_amount(raw_amount, decimal_comma)
        except (ValueError, ArithmeticError):
            raise _err(f"Невалидни данни на ред {i} (дата/сума)")
        items.append(
            BankTransactionIn(
                booking_date=booking,
                amount=amount,
                reference=(row.get(reference_column) or "").strip() or None if reference_column else None,
                description=(row.get(description_column) or "").strip() or None if description_column else None,
            )
        )
    if not items:
        raise _err("CSV файлът не съдържа валидни движения")
    return import_transactions(db, company, account_id, items)


def _decode(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1251", errors="replace")


def _parse_mt940(text: str) -> list[BankTransactionIn]:
    import datetime as dt
    import re

    # Обединяваме продълженията (редове без ':NN:' тагове).
    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    fields: list[str] = []
    for line in raw_lines:
        if line.startswith(":"):
            fields.append(line)
        elif fields and line.strip():
            fields[-1] += " " + line.strip()

    rx = re.compile(r"^(\d{2})(\d{2})(\d{2})(?:\d{4})?(RC|RD|C|D)([A-Z])?([\d,]+)")
    items: list[dict] = []
    current: dict | None = None
    for field in fields:
        tag, _, val = field[1:].partition(":")
        if tag == "61":
            if current is not None:
                items.append(current)
            m = rx.match(val)
            if not m:
                current = None
                continue
            yy, mm, dd, mark, _funds, amt = m.groups()
            amount = Decimal(amt.replace(",", "."))
            sign = -1 if "D" in mark else 1
            if mark.startswith("R"):
                sign = -sign
            try:
                booking = dt.date(2000 + int(yy), int(mm), int(dd))
            except ValueError:
                current = None
                continue
            current = {"date": booking, "amount": sign * amount, "desc": None}
        elif tag == "86" and current is not None:
            current["desc"] = val.strip()[:500] or None
    if current is not None:
        items.append(current)
    return [BankTransactionIn(booking_date=x["date"], amount=x["amount"], description=x["desc"]) for x in items]


def import_mt940(db: Session, company: Company, account_id: uuid.UUID, content: bytes) -> ImportResult:
    _get_account(db, company.id, account_id)
    items = _parse_mt940(_decode(content))
    if not items:
        raise _err("Файлът не съдържа разпознати MT940 движения (:61:)")
    return import_transactions(db, company, account_id, items)


def _parse_camt(content: bytes) -> list[BankTransactionIn]:
    """Разчита CAMT.053 извлечение.

    Файлът идва от потребител, затова се парсва с `defusedxml`: стандартният
    `xml.etree.ElementTree` е уязвим на entity expansion („billion laughs") и един
    малък файл може да изяде паметта на процеса.
    """
    import datetime as dt
    import xml.etree.ElementTree as ET

    from defusedxml.ElementTree import fromstring as safe_fromstring

    def local(elem) -> str:
        return elem.tag.split("}")[-1]

    try:
        root = safe_fromstring(content)
    except ET.ParseError as exc:
        raise _err(f"Невалиден CAMT XML: {exc}")
    except Exception as exc:                       # DTD/entity — отказваме файла
        raise _err(f"Отказан CAMT XML: {exc}")

    items: list[BankTransactionIn] = []
    for ntry in (e for e in root.iter() if local(e) == "Ntry"):
        amt = ccy = ind = date = desc = None
        for child in ntry.iter():
            name = local(child)
            if name == "Amt" and amt is None:
                amt, ccy = child.text, child.get("Ccy")
            elif name == "CdtDbtInd" and ind is None:
                ind = child.text
            elif name == "BookgDt" and date is None:
                for d in child.iter():
                    if local(d) in ("Dt", "DtTm") and d.text:
                        date = d.text[:10]
                        break
            elif name == "Ustrd" and desc is None:
                desc = child.text
        if amt is None or date is None:
            continue
        amount = Decimal(amt)
        if ind == "DBIT":
            amount = -amount
        items.append(
            BankTransactionIn(
                booking_date=dt.date.fromisoformat(date),
                amount=amount,
                currency=ccy,
                description=(desc or "").strip()[:500] or None,
            )
        )
    return items


def import_camt(db: Session, company: Company, account_id: uuid.UUID, content: bytes) -> ImportResult:
    _get_account(db, company.id, account_id)
    items = _parse_camt(content)
    if not items:
        raise _err("Файлът не съдържа разпознати CAMT движения (Ntry)")
    return import_transactions(db, company, account_id, items)


def list_transactions(
    db: Session,
    company_id: uuid.UUID,
    bank_account_id: uuid.UUID | None = None,
    status_filter: BankTxStatus | None = None,
) -> list[BankTransaction]:
    stmt = select(BankTransaction).where(BankTransaction.company_id == company_id)
    if bank_account_id is not None:
        stmt = stmt.where(BankTransaction.bank_account_id == bank_account_id)
    if status_filter is not None:
        stmt = stmt.where(BankTransaction.status == status_filter)
    return list(db.scalars(stmt.order_by(BankTransaction.booking_date.desc())))


def get_transaction(db: Session, company_id: uuid.UUID, tx_id: uuid.UUID) -> BankTransaction:
    tx = db.get(BankTransaction, tx_id)
    if tx is None or tx.company_id != company_id:
        raise _err("Движението не е намерено", status.HTTP_404_NOT_FOUND)
    return tx


# ============================ Съгласуване ============================
def _score(tx: BankTransaction, entry: JournalEntry) -> tuple[float, list[str]]:
    """Оценка на съответствие между движение и осчетоводена операция."""
    amount = abs(tx.amount)
    entry_amount = entry.total_debit
    reasons: list[str] = []

    if entry_amount == amount:
        score = 0.5
        reasons.append("точна сума")
    elif abs(entry_amount - amount) <= _CENT:
        score = 0.45
        reasons.append("сума ±0.01")
    else:
        return 0.0, []  # без съвпадение по сума не е кандидат

    tx_date = tx.value_date or tx.booking_date
    days = abs((entry.document_date - tx_date).days)
    if days == 0:
        score += 0.25
        reasons.append("същата дата")
    elif days <= 3:
        score += 0.15
        reasons.append(f"дата ±{days} дни")
    elif days <= 7:
        score += 0.08
        reasons.append(f"дата ±{days} дни")

    haystack = f"{tx.reference or ''} {tx.description or ''}".lower()
    if entry.document_number and entry.document_number.lower() in haystack:
        score += 0.3
        reasons.append("номер на документ в основанието")

    return min(score, 1.0), reasons


def suggest_matches(
    db: Session, company_id: uuid.UUID, tx_id: uuid.UUID, limit: int = 5
) -> list[MatchSuggestion]:
    tx = get_transaction(db, company_id, tx_id)
    entries = db.scalars(
        select(JournalEntry).where(
            JournalEntry.company_id == company_id, JournalEntry.status == EntryStatus.POSTED
        )
    )
    suggestions: list[MatchSuggestion] = []
    for entry in entries:
        score, reasons = _score(tx, entry)
        if score <= 0:
            continue
        suggestions.append(
            MatchSuggestion(
                journal_entry_id=entry.id,
                entry_number=entry.entry_number,
                document_number=entry.document_number,
                document_date=entry.document_date,
                amount=entry.total_debit,
                confidence=round(score, 2),
                reasons=reasons,
            )
        )
    suggestions.sort(key=lambda s: s.confidence, reverse=True)
    return suggestions[:limit]


def _recompute_status(tx: BankTransaction) -> None:
    if tx.status == BankTxStatus.IGNORED:
        return
    matched = tx.matched_amount
    target = abs(tx.amount)
    if matched == ZERO:
        tx.status = BankTxStatus.UNMATCHED
    elif matched >= target - _CENT:
        tx.status = BankTxStatus.MATCHED
    else:
        tx.status = BankTxStatus.PARTIALLY_MATCHED


def create_match(
    db: Session,
    company_id: uuid.UUID,
    tx_id: uuid.UUID,
    journal_entry_id: uuid.UUID,
    amount: Decimal | None,
    user_id: uuid.UUID,
    auto: bool = False,
    confidence: Decimal = Decimal("0"),
) -> BankTransactionMatch:
    tx = get_transaction(db, company_id, tx_id)
    if tx.status == BankTxStatus.IGNORED:
        raise _err("Игнорирано движение не може да се съпоставя", status.HTTP_409_CONFLICT)

    entry = db.get(JournalEntry, journal_entry_id)
    if entry is None or entry.company_id != company_id:
        raise _err("Счетоводната операция не съществува в тази компания")
    if entry.status != EntryStatus.POSTED:
        raise _err("Може да се съпоставя само осчетоводена операция")

    target = abs(tx.amount)
    match_amount = amount if amount is not None else (target - tx.matched_amount)
    if match_amount <= ZERO:
        raise _err("Сумата за съпоставяне трябва да е положителна")
    if tx.matched_amount + match_amount > target + _CENT:
        raise _err(
            f"Съпоставената сума ({tx.matched_amount + match_amount}) надвишава движението ({target})"
        )

    match = BankTransactionMatch(
        bank_transaction_id=tx.id,
        journal_entry_id=entry.id,
        amount=match_amount,
        confidence=confidence,
        auto=auto,
        created_by_id=user_id,
    )
    db.add(match)
    tx.matches.append(match)
    _recompute_status(tx)
    db.commit()
    db.refresh(match)
    return match


def delete_match(db: Session, company_id: uuid.UUID, tx_id: uuid.UUID, match_id: uuid.UUID) -> None:
    tx = get_transaction(db, company_id, tx_id)
    match = db.get(BankTransactionMatch, match_id)
    if match is None or match.bank_transaction_id != tx.id:
        raise _err("Съпоставянето не е намерено", status.HTTP_404_NOT_FOUND)
    db.delete(match)
    db.flush()
    db.refresh(tx)
    _recompute_status(tx)
    db.commit()


def ignore_transaction(db: Session, company_id: uuid.UUID, tx_id: uuid.UUID) -> BankTransaction:
    tx = get_transaction(db, company_id, tx_id)
    if tx.matches:
        raise _err("Премахни съпоставянията, преди да игнорираш движението", status.HTTP_409_CONFLICT)
    tx.status = BankTxStatus.IGNORED
    db.commit()
    db.refresh(tx)
    return tx
