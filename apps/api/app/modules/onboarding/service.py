"""Въвеждане на реален клиент: настройка, начални салда, миграция, проверка на данните.

Това е модулът, който стои между „системата работи“ и „в системата има истинска фирма“.
Три отделни неща:

1. **Състояние на настройката** — какво още липсва, за да може да се работи (реквизити,
   сметкоплан, фискална година, ДДС кодове, банкова сметка, начални салда).
2. **Начални салда** — импорт по код на сметка с проверка, че балансът излиза. Небалансирано
   начално салдо е най-скъпата грешка при миграция: открива се месеци по-късно.
3. **Проверка на здравето** — какво в базата не е наред *преди* да се твърди, че месецът е
   приключен.

Няма нищо специфично за конкретен доставчик на софтуер: миграцията е през CSV със съпоставяне
на колони — същият подход като при банковите извлечения, защото всеки износ е различен.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import uuid
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounting.models import (
    Account,
    AccountingPeriod,
    EntryStatus,
    FiscalYear,
    JournalEntry,
    JournalLine,
    JournalType,
)
from app.modules.accounting.schemas import JournalEntryCreate, JournalLineIn
from app.modules.accounting.service import create_entry, post_entry
from app.modules.banking.models import BankAccount, BankTransaction, BankTxStatus
from app.modules.companies.models import Company
from app.modules.counterparties.models import Counterparty, CounterpartyType
from app.modules.documents.models import Document, DocumentStatus
from app.modules.vat.models import VatCode

ZERO = Decimal("0.00")


def _err(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


def _decode(content: bytes) -> str:
    """БГ износите са ту UTF-8, ту Windows-1251 — пробваме и двете, без да се чупим."""
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1251", errors="replace")


# ==================================================================== настройка
def setup_status(db: Session, company: Company) -> dict:
    """Стъпките за пускане на клиента и кои са свършени."""
    accounts = db.scalar(
        select(func.count()).select_from(Account).where(Account.company_id == company.id)
    )
    years = db.scalar(
        select(func.count()).select_from(FiscalYear).where(FiscalYear.company_id == company.id)
    )
    vat_codes = db.scalar(
        select(func.count()).select_from(VatCode).where(VatCode.company_id == company.id)
    )
    banks = db.scalar(
        select(func.count()).select_from(BankAccount).where(BankAccount.company_id == company.id)
    )
    parties = db.scalar(
        select(func.count()).select_from(Counterparty).where(Counterparty.company_id == company.id)
    )
    opening = db.scalar(
        select(func.count())
        .select_from(JournalEntry)
        .where(
            JournalEntry.company_id == company.id,
            JournalEntry.journal == JournalType.OPENING,
            JournalEntry.status.in_((EntryStatus.POSTED, EntryStatus.REVERSED)),
        )
    )

    missing_details = [
        label
        for label, value in (
            ("ЕИК", company.eik),
            ("адрес", company.address_line),
            ("град", company.address_city),
        )
        if not value
    ]
    if company.is_vat_registered and not company.vat_number:
        missing_details.append("ДДС номер")

    steps = [
        {
            "key": "company_details",
            "title": "Реквизити на дружеството",
            "done": not missing_details,
            "detail": "Попълнени" if not missing_details else "Липсва: " + ", ".join(missing_details),
            "required": True,
            "action": "Компания → Реквизити",
        },
        {
            "key": "chart_of_accounts",
            "title": "Сметкоплан",
            "done": bool(accounts),
            "detail": f"{accounts} сметки" if accounts else "Няма зареден сметкоплан",
            "required": True,
            "action": "Счетоводство → Зареди сметкоплан",
        },
        {
            "key": "fiscal_year",
            "title": "Фискална година и периоди",
            "done": bool(years),
            "detail": f"{years} години" if years else "Няма открита фискална година",
            "required": True,
            "action": "Счетоводство → Фискални години",
        },
        {
            "key": "vat_codes",
            "title": "ДДС кодове",
            "done": bool(vat_codes) or not company.is_vat_registered,
            "detail": (
                f"{vat_codes} кода" if vat_codes
                else ("Не е приложимо — няма ДДС регистрация" if not company.is_vat_registered
                      else "Няма заредени ДДС кодове")
            ),
            "required": company.is_vat_registered,
            "action": "ДДС → Зареди кодове",
        },
        {
            "key": "opening_balances",
            "title": "Начални салда",
            "done": bool(opening),
            "detail": "Въведени" if opening else "Не са въвеждани (нова фирма — не е задължително)",
            "required": False,
            "action": "Въвеждане → Начални салда",
        },
        {
            "key": "counterparties",
            "title": "Контрагенти",
            "done": bool(parties),
            "detail": f"{parties} контрагента" if parties else "Няма въведени контрагенти",
            "required": False,
            "action": "Въвеждане → Импорт от CSV",
        },
        {
            "key": "bank_accounts",
            "title": "Банкови сметки",
            "done": bool(banks),
            "detail": f"{banks} сметки" if banks else "Няма банкови сметки",
            "required": False,
            "action": "Банки → Нова сметка",
        },
    ]
    required_done = all(s["done"] for s in steps if s["required"])
    return {
        "company": company.name,
        "ready": required_done,
        "completed": sum(1 for s in steps if s["done"]),
        "total": len(steps),
        "steps": steps,
    }


# ==================================================================== начални салда
def preview_opening_balances(
    db: Session, company: Company, rows: list[dict]
) -> dict:
    """Проверява началните салда, без да записва: съществуват ли сметките и излиза ли балансът."""
    codes = {
        a.code: a
        for a in db.scalars(select(Account).where(Account.company_id == company.id))
    }
    problems: list[str] = []
    total_debit = total_credit = ZERO
    resolved: list[dict] = []

    for i, row in enumerate(rows, start=1):
        code = str(row.get("account_code", "")).strip()
        account = codes.get(code)
        debit = Decimal(str(row.get("debit") or "0"))
        credit = Decimal(str(row.get("credit") or "0"))

        if not code:
            problems.append(f"Ред {i}: липсва код на сметка")
            continue
        if account is None:
            problems.append(f"Ред {i}: сметка {code} не съществува в сметкоплана")
            continue
        if account.is_group:
            problems.append(f"Ред {i}: сметка {code} е обобщаваща — салдата се водят по аналитични")
            continue
        if debit < ZERO or credit < ZERO:
            problems.append(f"Ред {i}: отрицателна стойност — ползвай другата колона")
            continue
        if debit > ZERO and credit > ZERO:
            problems.append(f"Ред {i}: сметка {code} има едновременно дебитно и кредитно салдо")
            continue
        if debit == ZERO and credit == ZERO:
            continue

        total_debit += debit
        total_credit += credit
        resolved.append(
            {"account_id": account.id, "code": code, "name": account.name,
             "debit": debit, "credit": credit}
        )

    difference = total_debit - total_credit
    if resolved and difference != ZERO:
        problems.append(
            f"Началните салда не балансират: дебит {total_debit} срещу кредит {total_credit} "
            f"(разлика {difference}). Небалансирано начално салдо се открива месеци по-късно — "
            f"оправи го сега."
        )
    return {
        "rows": resolved,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "difference": difference,
        "balanced": difference == ZERO,
        "problems": problems,
        "can_post": not problems and bool(resolved),
    }


def post_opening_balances(
    db: Session, company: Company, user_id: uuid.UUID, on_date: dt.date, rows: list[dict]
) -> JournalEntry:
    """Осчетоводява началните салда като операция в дневник „Начални салда“."""
    existing = db.scalar(
        select(JournalEntry.id).where(
            JournalEntry.company_id == company.id,
            JournalEntry.journal == JournalType.OPENING,
            JournalEntry.status.in_((EntryStatus.POSTED, EntryStatus.REVERSED)),
        )
    )
    if existing is not None:
        raise _err(
            "Вече има осчетоводени начални салда. Сторнирай операцията, ако трябва да се променят.",
            status.HTTP_409_CONFLICT,
        )

    preview = preview_opening_balances(db, company, rows)
    if not preview["can_post"]:
        raise _err("; ".join(preview["problems"]) or "Няма редове за осчетоводяване")

    entry = create_entry(
        db,
        company,
        user_id,
        JournalEntryCreate(
            document_date=on_date,
            journal=JournalType.OPENING,
            document_type="Начални салда",
            document_number=f"OPEN-{on_date:%Y%m%d}",
            description="Начални салда при въвеждане в системата",
            lines=[
                JournalLineIn(
                    account_id=r["account_id"], debit=r["debit"], credit=r["credit"],
                    description=f"Начално салдо {r['code']}",
                )
                for r in preview["rows"]
            ],
        ),
    )
    post_entry(db, company.id, entry.id, user_id)
    return entry


def parse_opening_csv(content: bytes, delimiter: str, decimal_comma: bool) -> list[dict]:
    """CSV с колони: код на сметка, дебит, кредит. Имената им се разпознават гъвкаво."""
    reader = csv.DictReader(io.StringIO(_decode(content)), delimiter=delimiter)
    if not reader.fieldnames:
        raise _err("Празен CSV файл")

    def pick(*candidates: str) -> str | None:
        for name in reader.fieldnames:
            if name and name.strip().lower() in candidates:
                return name
        return None

    col_code = pick("сметка", "код", "account", "account_code", "код на сметка")
    col_debit = pick("дебит", "debit", "дт", "дебитно салдо")
    col_credit = pick("кредит", "credit", "кт", "кредитно салдо")
    if not col_code or not (col_debit or col_credit):
        raise _err(
            "CSV трябва да има колона за сметка и поне една за дебит/кредит. "
            f"Намерени колони: {', '.join(reader.fieldnames)}"
        )

    def amount(value: str | None) -> str:
        raw = (value or "").strip()
        if not raw:
            return "0"
        if decimal_comma:
            raw = raw.replace(" ", "").replace(".", "").replace(",", ".")
        try:
            Decimal(raw)
        except InvalidOperation:
            raise _err(f"Невалидна сума: {value!r}")
        return raw

    return [
        {
            "account_code": (row.get(col_code) or "").strip(),
            "debit": amount(row.get(col_debit) if col_debit else None),
            "credit": amount(row.get(col_credit) if col_credit else None),
        }
        for row in reader
    ]


# ==================================================================== миграция
def import_counterparties_csv(
    db: Session,
    company: Company,
    content: bytes,
    *,
    name_column: str,
    eik_column: str | None,
    vat_column: str | None,
    address_column: str | None,
    type_value: CounterpartyType,
    delimiter: str,
) -> dict:
    """Импорт на контрагенти от износ на друга система.

    Дубликатите по ЕИК/ДДС номер се **пропускат**, не се презаписват: миграцията не бива
    да променя вече въведени данни.
    """
    reader = csv.DictReader(io.StringIO(_decode(content)), delimiter=delimiter)
    if not reader.fieldnames or name_column not in reader.fieldnames:
        raise _err(f"CSV трябва да съдържа колона {name_column!r}")

    existing_eik = {
        e for e in db.scalars(
            select(Counterparty.eik).where(
                Counterparty.company_id == company.id, Counterparty.eik.is_not(None)
            )
        )
    }
    existing_vat = {
        v for v in db.scalars(
            select(Counterparty.vat_number).where(
                Counterparty.company_id == company.id, Counterparty.vat_number.is_not(None)
            )
        )
    }

    created = skipped = 0
    problems: list[str] = []
    seen_eik: set[str] = set()

    for i, row in enumerate(reader, start=2):
        name = (row.get(name_column) or "").strip()
        if not name:
            continue
        eik = (row.get(eik_column) or "").strip() if eik_column else None
        vat = (row.get(vat_column) or "").strip() if vat_column else None
        address = (row.get(address_column) or "").strip() if address_column else None

        if eik and (eik in existing_eik or eik in seen_eik):
            skipped += 1
            problems.append(f"Ред {i}: {name} — вече съществува контрагент с ЕИК {eik}")
            continue
        if vat and vat in existing_vat:
            skipped += 1
            problems.append(f"Ред {i}: {name} — вече съществува контрагент с ДДС номер {vat}")
            continue

        db.add(
            Counterparty(
                company_id=company.id, name=name, type=type_value,
                eik=eik or None, vat_number=vat or None, address=address or None,
            )
        )
        if eik:
            seen_eik.add(eik)
        created += 1

    db.commit()
    return {
        "created": created,
        "skipped": skipped,
        "problems": problems[:50],   # дълъг списък не помага на никого
        "note": "Съществуващите контрагенти не се променят — дубликатите се пропускат.",
    }


# ==================================================================== здраве на данните
def health_check(db: Session, company: Company) -> dict:
    """Какво в данните не е наред. Прегледът е преди твърдението „месецът е приключен“."""
    issues: list[dict] = []

    def add(level: str, code: str, title: str, count: int, hint: str) -> None:
        if count:
            issues.append(
                {"level": level, "code": code, "title": title, "count": count, "hint": hint}
            )

    # Небалансирана осчетоводена операция е тежка грешка — не бива да съществува изобщо.
    unbalanced = db.execute(
        select(JournalLine.entry_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(
            JournalEntry.company_id == company.id,
            JournalEntry.status.in_((EntryStatus.POSTED, EntryStatus.REVERSED, EntryStatus.REVERSAL)),
        )
        .group_by(JournalLine.entry_id)
        .having(func.sum(JournalLine.debit_base) != func.sum(JournalLine.credit_base))
    ).all()
    add("ERROR", "UNBALANCED_ENTRIES", "Небалансирани осчетоводени операции",
        len(unbalanced), "Всяка операция трябва да има равни дебит и кредит.")

    drafts = db.scalar(
        select(func.count()).select_from(JournalEntry).where(
            JournalEntry.company_id == company.id, JournalEntry.status == EntryStatus.DRAFT
        )
    )
    add("WARNING", "DRAFT_ENTRIES", "Неосчетоводени чернови", drafts,
        "Черновите не влизат в отчетите и в ДДС дневниците.")

    stuck_docs = db.scalar(
        select(func.count()).select_from(Document).where(
            Document.company_id == company.id,
            Document.status.in_((
                DocumentStatus.NEEDS_REVIEW, DocumentStatus.MISSING_DATA,
                DocumentStatus.POTENTIAL_DUPLICATE, DocumentStatus.RETURNED,
            )),
        )
    )
    add("WARNING", "DOCS_NEED_REVIEW", "Документи, чакащи човек", stuck_docs,
        "Проверете разпознатите данни и ги одобрете или отхвърлете.")

    unmatched = db.scalar(
        select(func.count()).select_from(BankTransaction).where(
            BankTransaction.company_id == company.id,
            BankTransaction.status.in_((BankTxStatus.UNMATCHED, BankTxStatus.PARTIALLY_MATCHED)),
        )
    )
    add("WARNING", "UNRECONCILED_BANK", "Несъгласувани банкови движения", unmatched,
        "Несъгласуваните движения изкривяват паричния поток.")

    no_id = db.scalar(
        select(func.count()).select_from(Counterparty).where(
            Counterparty.company_id == company.id,
            Counterparty.eik.is_(None),
            Counterparty.vat_number.is_(None),
        )
    )
    add("WARNING", "COUNTERPARTIES_NO_ID", "Контрагенти без ЕИК и ДДС номер", no_id,
        "В дневниците на НАП идентификаторът на контрагента е задължителен.")

    # Липсващи реквизити на самото дружество.
    missing = [
        label for label, value in (
            ("ЕИК", company.eik), ("адрес", company.address_line), ("град", company.address_city)
        ) if not value
    ]
    if company.is_vat_registered and not company.vat_number:
        missing.append("ДДС номер")
    if missing:
        issues.append({
            "level": "ERROR", "code": "COMPANY_DETAILS", "title": "Липсващи реквизити на дружеството",
            "count": len(missing),
            "hint": "Без тях НАП отхвърля подаването. Липсва: " + ", ".join(missing),
        })

    open_periods = db.scalar(
        select(func.count()).select_from(AccountingPeriod).where(
            AccountingPeriod.company_id == company.id,
            AccountingPeriod.end_date < dt.date.today(),
            AccountingPeriod.status == "OPEN",
        )
    )
    add("INFO", "OLD_OPEN_PERIODS", "Отминали, но неприключени периоди", open_periods,
        "Приключването пази миналите месеци от случайна промяна.")

    errors = [i for i in issues if i["level"] == "ERROR"]
    return {
        "company": company.name,
        "healthy": not errors,
        "errors": len(errors),
        "warnings": sum(1 for i in issues if i["level"] == "WARNING"),
        "issues": issues,
    }
