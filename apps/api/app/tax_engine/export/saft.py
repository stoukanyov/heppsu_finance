"""SAF-T (Standard Audit File for Tax) експорт — OECD стандарт, българска версия.

SAF-T е XML файл с одитна извадка от счетоводството: сметкоплан, контрагенти, данъчни
таблици, дневник на операциите и салда. НАП въвежда SAF-T поетапно; форматът е
проектиран отсега като ОТДЕЛЕН export provider, за да не се пипа ядрото при промяна на
схемата.

ВАЖНО (Q-011): структурата следва OECD SAF-T v2.0 и публикуваните български изисквания
към момента на писане. Преди реално подаване файлът трябва да се валидира спрямо
актуалната XSD схема на НАП. Затова провайдърът носи ВЕРСИЯ — при нова схема се добавя
нов клас (`SaftBgV2Provider` и т.н.), а старият остава за минали периоди.
"""
from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from decimal import Decimal

# Входящите документи идват отвън (фактура от доставчик, получен SAF-T), затова
# се парсват с `defusedxml`: стандартният ElementTree е уязвим на entity expansion
# („billion laughs") и един малък файл може да изяде паметта на процеса.
from defusedxml.ElementTree import fromstring as safe_fromstring
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounting.models import (
    Account,
    AccountType,
    EntryStatus,
    JournalEntry,
    JournalLine,
)
from app.modules.companies.models import Company
from app.modules.counterparties.models import Counterparty, CounterpartyType
from app.modules.vat.models import VatCode
from app.tax_engine.export.base import ExportProvider, ExportResult
from app.tax_engine.export.validation import (
    ERROR,
    WARNING,
    ValidationReport,
    XsdSchema,
)

ZERO = Decimal("0.00")
_POSTED = (EntryStatus.POSTED, EntryStatus.REVERSED, EntryStatus.REVERSAL)

# Съответствие вътрешен тип сметка → SAF-T категория.
_ACCOUNT_TYPE = {
    AccountType.ASSET: "Asset",
    AccountType.LIABILITY: "Liability",
    AccountType.EQUITY: "Equity",
    AccountType.REVENUE: "Income",
    AccountType.EXPENSE: "Expense",
    AccountType.OFF_BALANCE: "Other",
}


def _n(value: Decimal | None) -> str:
    return f"{(value or ZERO):.2f}"


def _sub(parent: ET.Element, tag: str, text=None) -> ET.Element:
    e = ET.SubElement(parent, tag)
    if text is not None:
        e.text = str(text)
    return e


class SaftBgV1Provider(ExportProvider):
    """SAF-T за България, версия 1.0 (одитен файл за данъчни цели)."""

    code = "SAFT_BG"
    name = "SAF-T България (одитен файл)"
    version = "1.0"
    media_type = "application/xml"
    namespace = "urn:StandardAuditFile-Taxation-Financial:BG"

    # Официалната схема на НАП не се разпространява с кода — слага се ръчно тук.
    # Докато я няма, `validate` не мълчи, а го казва и пуска структурните проверки.
    schema = XsdSchema("saft-bg-1.0.xsd", "SAF-T България 1.0")

    # ------------------------------------------------------------------ секции
    def _header(self, root: ET.Element, company: Company, ctx: dict) -> None:
        h = _sub(root, "Header")
        _sub(h, "AuditFileVersion", self.version)
        _sub(h, "AuditFileCountry", company.country or "BG")
        _sub(h, "AuditFileDateCreated", dt.date.today().isoformat())
        _sub(h, "SoftwareCompanyName", "AI Finance OS")
        _sub(h, "SoftwareID", "AI-FINANCE-OS")
        _sub(h, "SoftwareVersion", ctx.get("software_version", "0.1.0"))

        c = _sub(h, "Company")
        _sub(c, "RegistrationNumber", company.eik or "")
        _sub(c, "Name", company.name)
        if company.name_latin:
            _sub(c, "NameLatin", company.name_latin)
        addr = _sub(c, "Address")
        _sub(addr, "StreetName", company.address_line or "")
        _sub(addr, "City", company.address_city or "")
        _sub(addr, "PostalCode", company.address_postcode or "")
        _sub(addr, "Country", company.country or "BG")
        if company.email or company.phone:
            contact = _sub(c, "Contact")
            _sub(contact, "Telephone", company.phone or "")
            _sub(contact, "Email", company.email or "")
        tax = _sub(c, "TaxRegistration")
        _sub(tax, "TaxRegistrationNumber", company.vat_number or "")
        _sub(tax, "TaxAuthority", "НАП")

        _sub(h, "DefaultCurrencyCode", company.base_currency)
        sel = _sub(h, "SelectionCriteria")
        _sub(sel, "SelectionStartDate", ctx["date_from"].isoformat())
        _sub(sel, "SelectionEndDate", ctx["date_to"].isoformat())
        _sub(h, "HeaderComment", ctx.get("comment", "Одитен файл по SAF-T"))

    def _master_files(self, root: ET.Element, db: Session, company: Company) -> None:
        master = _sub(root, "MasterFiles")

        # --- Сметкоплан ---
        accounts = list(
            db.scalars(
                select(Account).where(Account.company_id == company.id).order_by(Account.code)
            )
        )
        general = _sub(master, "GeneralLedgerAccounts")
        for a in accounts:
            node = _sub(general, "Account")
            _sub(node, "AccountID", a.code)
            _sub(node, "AccountDescription", a.name)
            _sub(node, "AccountType", _ACCOUNT_TYPE.get(a.type, "Other"))
            _sub(node, "GroupingCategory", "Group" if a.is_group else "Account")
            if a.parent_id is not None:
                parent = next((p for p in accounts if p.id == a.parent_id), None)
                if parent is not None:
                    _sub(node, "GroupingCode", parent.code)

        # --- Контрагенти (клиенти и доставчици в отделни секции по стандарта) ---
        parties = list(
            db.scalars(
                select(Counterparty)
                .where(Counterparty.company_id == company.id)
                .order_by(Counterparty.name)
            )
        )
        customers = _sub(master, "Customers")
        suppliers = _sub(master, "Suppliers")
        for p in parties:
            is_customer = p.type in (CounterpartyType.CUSTOMER, CounterpartyType.BOTH)
            is_supplier = p.type in (CounterpartyType.SUPPLIER, CounterpartyType.BOTH)
            for parent, tag, acc in (
                (customers, "Customer", "411"),
                (suppliers, "Supplier", "401"),
            ):
                if tag == "Customer" and not is_customer:
                    continue
                if tag == "Supplier" and not is_supplier:
                    continue
                node = _sub(parent, tag)
                _sub(node, f"{tag}ID", str(p.id))
                _sub(node, "AccountID", acc)
                _sub(node, "RegistrationNumber", p.eik or "")
                _sub(node, "Name", p.name)
                _sub(node, "TaxRegistrationNumber", p.vat_number or "")
                addr = _sub(node, "Address")
                _sub(addr, "AddressDetail", p.address or "")
                _sub(addr, "Country", p.country or "BG")

        # --- Данъчна таблица (ДДС кодове) ---
        tax_table = _sub(master, "TaxTable")
        for code in db.scalars(
            select(VatCode).where(VatCode.company_id == company.id).order_by(VatCode.code)
        ):
            entry = _sub(tax_table, "TaxTableEntry")
            _sub(entry, "TaxType", "VAT")
            _sub(entry, "TaxCode", code.code)
            _sub(entry, "Description", code.name)
            _sub(entry, "TaxPercentage", f"{code.rate:.2f}")
            _sub(entry, "Country", company.country or "BG")

    def _general_ledger_entries(
        self, root: ET.Element, db: Session, company: Company, ctx: dict
    ) -> tuple[int, Decimal, Decimal]:
        """Дневник на операциите; връща (брой, общо дебит, общо кредит)."""
        gl = _sub(root, "GeneralLedgerEntries")
        rows = db.execute(
            select(JournalEntry)
            .where(
                JournalEntry.company_id == company.id,
                JournalEntry.status.in_(_POSTED),
                JournalEntry.document_date >= ctx["date_from"],
                JournalEntry.document_date <= ctx["date_to"],
            )
            .order_by(JournalEntry.document_date, JournalEntry.entry_number)
        ).scalars().all()

        accounts = {
            a.id: a for a in db.scalars(select(Account).where(Account.company_id == company.id))
        }
        total_debit = total_credit = ZERO
        count = 0

        # По стандарта операциите се групират по дневник (journal).
        by_journal: dict[str, list[JournalEntry]] = {}
        for e in rows:
            by_journal.setdefault(e.journal.value, []).append(e)

        _sub(gl, "NumberOfEntries", str(len(rows)))
        totals_debit = _sub(gl, "TotalDebit")
        totals_credit = _sub(gl, "TotalCredit")

        for journal_code, entries in by_journal.items():
            j = _sub(gl, "Journal")
            _sub(j, "JournalID", journal_code)
            _sub(j, "Description", journal_code)
            for e in entries:
                count += 1
                t = _sub(j, "Transaction")
                _sub(t, "TransactionID", str(e.id))
                _sub(t, "Period", f"{e.document_date.month:02d}")
                _sub(t, "PeriodYear", str(e.document_date.year))
                _sub(t, "TransactionDate", e.document_date.isoformat())
                _sub(t, "SourceID", str(e.entry_number or ""))
                _sub(t, "Description", e.description or "")
                _sub(t, "DocArchivalNumber", e.document_number or "")
                _sub(t, "TransactionType", e.document_type or journal_code)
                _sub(t, "GLPostingDate", (e.posting_date or e.document_date).isoformat())
                lines = db.scalars(
                    select(JournalLine).where(JournalLine.entry_id == e.id).order_by(JournalLine.line_no)
                ).all()
                for line in lines:
                    acc = accounts.get(line.account_id)
                    side = "DebitLine" if line.debit_base > ZERO else "CreditLine"
                    node = _sub(t, side)
                    _sub(node, "RecordID", f"{e.id}-{line.line_no}")
                    _sub(node, "AccountID", acc.code if acc else "")
                    _sub(node, "SourceDocumentID", e.document_number or "")
                    _sub(node, "SystemEntryDate", (e.posting_date or e.document_date).isoformat())
                    _sub(node, "Description", line.description or e.description or "")
                    amount = line.debit_base if side == "DebitLine" else line.credit_base
                    amt = _sub(node, "Amount")
                    _sub(amt, "Amount", _n(amount))
                    _sub(amt, "CurrencyCode", e.currency)
                    if e.currency != company.base_currency:
                        _sub(amt, "CurrencyAmount", _n(line.debit if side == "DebitLine" else line.credit))
                        _sub(amt, "ExchangeRate", f"{e.exchange_rate:.6f}")
                    total_debit += line.debit_base
                    total_credit += line.credit_base

        totals_debit.text = _n(total_debit)
        totals_credit.text = _n(total_credit)
        return count, total_debit, total_credit

    # ------------------------------------------------------------------ експорт
    def export(self, company: Company, context: dict) -> ExportResult:
        db: Session = context["db"]
        root = ET.Element("AuditFile", {"xmlns": self.namespace})

        self._header(root, company, context)
        self._master_files(root, db, company)
        count, debit, credit = self._general_ledger_entries(root, db, company, context)

        warnings: list[str] = []
        if debit != credit:
            warnings.append(
                f"Небаланс в дневника: дебит {debit} ≠ кредит {credit} — провери операциите."
            )
        if count == 0:
            warnings.append("Няма осчетоводени операции в избрания период.")
        if not company.eik:
            warnings.append("Липсва ЕИК на дружеството — задължителен реквизит в SAF-T.")
        if not company.vat_number:
            warnings.append("Липсва ДДС номер — задължителен при регистрация по ЗДДС.")

        body = ET.tostring(root, encoding="unicode")
        xml = f'<?xml version="1.0" encoding="UTF-8"?>\n{body}'
        ident = (company.eik or "NOEIK").replace(" ", "")
        period = f"{context['date_from']:%Y%m%d}-{context['date_to']:%Y%m%d}"
        return ExportResult(
            filename=f"SAFT-BG-{ident}-{period}.xml",
            content=xml.encode("utf-8"),
            media_type=self.media_type,
            contents=[
                "Header — данни за дружеството и периода",
                "MasterFiles — сметкоплан, контрагенти, данъчна таблица",
                f"GeneralLedgerEntries — {count} операции",
            ],
            warnings=warnings,
        )

    # ------------------------------------------------------------------ валидация
    def validate(self, xml: bytes) -> ValidationReport:
        """Проверява готовия файл — първо срещу XSD, после структурно.

        Работи върху самия байтов резултат, а не върху междинно състояние: това е
        точно файлът, който ще бъде подаден. Структурните проверки не зависят от
        схемата и вършат работа и докато официалният XSD липсва.
        """
        report = ValidationReport(
            target=f"SAF-T България {self.version}",
            schema_name=self.schema.name,
            schema_present=self.schema.available,
        )
        report.extend(self.schema.validate(xml))

        try:
            root = safe_fromstring(xml)
        except ET.ParseError as exc:
            report.add(ERROR, f"Файлът не е валиден XML: {exc}")
            return report
        except Exception as exc:      # DTD/ENTITY — defusedxml отказва файла
            report.add(ERROR, f"Файлът е отказан по съображения за сигурност: {exc}")
            return report

        ns = f"{{{self.namespace}}}"

        def _qualified(path: str) -> str:
            """'a/b' → '{ns}a/{ns}b' — ElementTree иска namespace на всяко ниво."""
            return "/".join(f"{ns}{part}" for part in path.split("/"))

        def find(node, path: str):
            return node.find(_qualified(path))

        def findall(node, path: str):
            return node.findall(_qualified(path))

        def text(node, path: str) -> str:
            found = find(node, path)
            return (found.text or "").strip() if found is not None else ""

        # --- задължителни реквизити в заглавната част ---
        header = find(root, "Header")
        if header is None:
            report.add(ERROR, "Липсва секция <Header>", path="/AuditFile/Header")
            return report
        for path, label in (
            ("Company/RegistrationNumber", "ЕИК на дружеството"),
            ("Company/Name", "наименование на дружеството"),
            ("DefaultCurrencyCode", "отчетна валута"),
            ("SelectionCriteria/SelectionStartDate", "начална дата на периода"),
            ("SelectionCriteria/SelectionEndDate", "крайна дата на периода"),
        ):
            if not text(header, path):
                report.add(
                    ERROR,
                    f"Липсва задължителен реквизит: {label}",
                    path=f"/AuditFile/Header/{path}",
                )
        if not text(header, "Company/TaxRegistration/TaxRegistrationNumber"):
            report.add(
                WARNING,
                "Липсва ДДС номер — задължителен при регистрация по ЗДДС",
                path="/AuditFile/Header/Company/TaxRegistration/TaxRegistrationNumber",
            )

        # --- дневникът трябва да балансира ---
        gl = find(root, "GeneralLedgerEntries")
        if gl is None:
            report.add(ERROR, "Липсва секция <GeneralLedgerEntries>")
            return report

        declared_debit = _to_decimal(text(gl, "TotalDebit"))
        declared_credit = _to_decimal(text(gl, "TotalCredit"))
        if declared_debit != declared_credit:
            report.add(
                ERROR,
                f"Дневникът не балансира: общо дебит {declared_debit} ≠ общо кредит "
                f"{declared_credit}",
                path="/AuditFile/GeneralLedgerEntries",
            )

        # --- контролните суми срещу действително записаните редове ---
        actual_debit = actual_credit = ZERO
        transactions = 0
        for journal in findall(gl, "Journal"):
            for tx in findall(journal, "Transaction"):
                transactions += 1
                for side, bucket in (("DebitLine", "debit"), ("CreditLine", "credit")):
                    for line in findall(tx, side):
                        amount = _to_decimal(text(line, "Amount/Amount"))
                        if bucket == "debit":
                            actual_debit += amount
                        else:
                            actual_credit += amount

        if actual_debit != declared_debit:
            report.add(
                ERROR,
                f"Обявеният общ дебит ({declared_debit}) не съвпада със сбора на редовете "
                f"({actual_debit})",
                path="/AuditFile/GeneralLedgerEntries/TotalDebit",
            )
        if actual_credit != declared_credit:
            report.add(
                ERROR,
                f"Обявеният общ кредит ({declared_credit}) не съвпада със сбора на редовете "
                f"({actual_credit})",
                path="/AuditFile/GeneralLedgerEntries/TotalCredit",
            )

        declared_count = text(gl, "NumberOfEntries")
        if declared_count and declared_count.isdigit() and int(declared_count) != transactions:
            report.add(
                ERROR,
                f"Обявеният брой операции ({declared_count}) не съвпада с реално записаните "
                f"({transactions})",
                path="/AuditFile/GeneralLedgerEntries/NumberOfEntries",
            )

        # --- всяка сметка в дневника трябва да съществува в сметкоплана ---
        chart = {
            (a.findtext(f"{ns}AccountID") or "").strip()
            for a in findall(root, "MasterFiles/GeneralLedgerAccounts/Account")
        }
        missing: set[str] = set()
        for journal in findall(gl, "Journal"):
            for tx in findall(journal, "Transaction"):
                for side in ("DebitLine", "CreditLine"):
                    for line in findall(tx, side):
                        code = text(line, "AccountID")
                        if code and code not in chart:
                            missing.add(code)
        for code in sorted(missing):
            report.add(
                ERROR,
                f"Сметка {code} се ползва в дневника, но липсва в сметкоплана",
                path="/AuditFile/MasterFiles/GeneralLedgerAccounts",
            )

        if transactions == 0:
            report.add(WARNING, "В периода няма осчетоводени операции")
        return report


def _to_decimal(value: str) -> Decimal:
    try:
        return Decimal(value or "0")
    except Exception:
        return ZERO
