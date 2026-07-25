"""Генериране на файловете за НАП по ЗДДС: дневник покупки, дневник продажби,
справка-декларация и VIES декларация.

Изходът следва структурата на форматираните текстови файлове по ППЗДДС
(Приложение № 12) — фиксирана дължина на полетата, кодиране Windows-1251, край
на реда CRLF. Файловете са три задължителни (POKUPKI.TXT, PRODAGBI.TXT,
DEKLAR.TXT) плюс по избор VIES.TXT.

ВАЖНО (Q-006): точните дължини на полетата и номерата на клетките се управляват
централизирано в таблиците по-долу. Преди реално подаване форматът трябва да се
валидира спрямо актуалната техническа спецификация на НАП за съответната година —
това е единственото място за корекция.

Класификацията на всеки ДДС запис в колона на дневника се извежда от атрибутите
на ДДС кода (ставка, VIES, протокол, право на кредит) — виж ``classify_sale`` и
``classify_purchase`` — така че потребителски кодове също се разпределят коректно.
"""
from __future__ import annotations

import datetime as dt
import io
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.modules.companies.models import Company
from app.modules.vat.models import VatDirection, VatEntry

ENCODING = "cp1251"
NEWLINE = "\r\n"
_ZERO = Decimal("0.00")


# ------------------------------------------------------------------ помощни
def _num(value: Decimal | None) -> str:
    """Парична стойност → низ с точка и 2 знака (НАП формат: 1234.56)."""
    if value is None:
        value = _ZERO
    return f"{value:.2f}"


def _ddmmyyyy(d: dt.date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def _period_code(period_code: str) -> str:
    """'2026-07' → '202607' (ГГГГММ)."""
    return period_code.replace("-", "")[:6]


def _clip(text: str | None, width: int) -> str:
    return (text or "")[:width]


# ------------------------------------------------------ класификация в колони
class SaleBucket(str, Enum):
    STD20 = "STD20"        # облагаеми 20%
    STD9 = "STD9"          # облагаеми 9%
    ICS = "ICS"            # ВОД (вътреобщностни доставки) 0%
    EXPORT = "EXPORT"      # износ 0% (глава трета)
    EXEMPT = "EXEMPT"      # освободени доставки
    TRICOUNTRY = "TRI"     # тристранни / услуги чл.21 в ЕС
    REVERSE = "REVERSE"    # обратно начисляване чл.163а


class PurchaseBucket(str, Enum):
    FULL = "FULL"          # пълен данъчен кредит
    PARTIAL = "PARTIAL"    # частичен данъчен кредит
    NOCREDIT = "NOCREDIT"  # без право на данъчен кредит или без данък
    ICA = "ICA"            # ВОП / самоначисляване по чл.82


def classify_sale(entry: VatEntry) -> SaleBucket:
    code = entry.vat_code
    rate = code.rate
    if rate == Decimal("20.00"):
        return SaleBucket.STD20
    if rate == Decimal("9.00"):
        return SaleBucket.STD9
    # ставка 0 / освободени
    if code.requires_vies:
        return SaleBucket.ICS
    upper = (code.code or "").upper()
    if "EXM" in upper or "EXEMPT" in upper or "ОСВ" in upper:
        return SaleBucket.EXEMPT
    if "REV" in upper or "163" in upper:
        return SaleBucket.REVERSE
    return SaleBucket.EXPORT


def classify_purchase(entry: VatEntry) -> PurchaseBucket:
    code = entry.vat_code
    if code.requires_vies or code.requires_protocol:
        return PurchaseBucket.ICA
    if not code.gives_credit:
        return PurchaseBucket.NOCREDIT
    upper = (code.code or "").upper()
    if "PART" in upper or "ЧАСТ" in upper:
        return PurchaseBucket.PARTIAL
    return PurchaseBucket.FULL


# ------------------------------------------------------------- клетки на СД
@dataclass
class DeclarationCells:
    """Клетки на справка-декларацията по ЗДДС (стойности в базова валута)."""

    # Начислен данък
    c01_base_taxable: Decimal = _ZERO   # к.01 обща ДО за облагане с ДДС
    c11_base_20: Decimal = _ZERO        # к.11 ДО облагаеми 20% (в страната)
    c12_base_ica_82: Decimal = _ZERO    # к.12 ДО на ВОП и получени по чл.82
    c13_base_9: Decimal = _ZERO         # к.13 ДО облагаеми 9%
    c14_base_export: Decimal = _ZERO    # к.14 ДО 0% по глава трета (износ)
    c15_base_ics: Decimal = _ZERO       # к.15 ДО на ВОД
    c17_base_tri: Decimal = _ZERO       # к.17 ДО тристранни/услуги чл.21 в ЕС
    c18_base_exempt: Decimal = _ZERO    # к.18 ДО освободени доставки и ВОП
    c20_vat_total: Decimal = _ZERO      # к.20 всичко начислен ДДС
    c21_vat_ica_82: Decimal = _ZERO     # к.21 начислен ДДС за ВОП и по чл.82

    # Данъчен кредит
    c30_base_nocredit: Decimal = _ZERO  # к.30 ДО без право на ДК или без данък
    c31_base_full: Decimal = _ZERO      # к.31 ДО с право на пълен данъчен кредит
    c41_vat_full: Decimal = _ZERO       # к.41 ДДС с право на пълен данъчен кредит
    c33_base_partial: Decimal = _ZERO   # к.33 ДО с право на частичен данъчен кредит
    c42_vat_partial: Decimal = _ZERO    # к.42 ДДС с право на частичен данъчен кредит
    c40_credit_total: Decimal = _ZERO   # к.40 общ данъчен кредит

    # Резултат за периода
    c50_vat_payable: Decimal = _ZERO    # к.50 ДДС за внасяне
    c60_vat_refundable: Decimal = _ZERO  # к.60 ДДС за възстановяване

    def as_rows(self) -> list[dict]:
        """Подредени клетки за преглед в UI (номер, описание, стойност)."""
        spec = [
            ("01", "Обща сума на данъчните основи за облагане с ДДС", self.c01_base_taxable),
            ("11", "ДО на облагаемите доставки със ставка 20%", self.c11_base_20),
            ("12", "ДО на ВОП и на получени доставки по чл.82 (самоначисляване)", self.c12_base_ica_82),
            ("13", "ДО на облагаемите доставки със ставка 9%", self.c13_base_9),
            ("14", "ДО на доставки със ставка 0% по глава трета (износ)", self.c14_base_export),
            ("15", "ДО на вътреобщностни доставки (ВОД)", self.c15_base_ics),
            ("17", "ДО на тристранни операции и услуги по чл.21 в ЕС", self.c17_base_tri),
            ("18", "ДО на освободени доставки и освободени ВОП", self.c18_base_exempt),
            ("20", "Всичко начислен ДДС", self.c20_vat_total),
            ("21", "Начислен ДДС за ВОП и за доставки по чл.82", self.c21_vat_ica_82),
            ("30", "ДО на получени доставки без право на ДК или без данък", self.c30_base_nocredit),
            ("31", "ДО на получени доставки с право на пълен данъчен кредит", self.c31_base_full),
            ("41", "ДДС с право на пълен данъчен кредит", self.c41_vat_full),
            ("33", "ДО на получени доставки с право на частичен данъчен кредит", self.c33_base_partial),
            ("42", "ДДС с право на частичен данъчен кредит", self.c42_vat_partial),
            ("40", "Общ данъчен кредит", self.c40_credit_total),
            ("50", "ДДС за внасяне", self.c50_vat_payable),
            ("60", "ДДС за възстановяване", self.c60_vat_refundable),
        ]
        return [{"cell": c, "label": lbl, "amount": amt} for c, lbl, amt in spec]


def compute_declaration_cells(entries: list[VatEntry]) -> DeclarationCells:
    """Агрегира ДДС записите в клетките на справка-декларацията."""
    d = DeclarationCells()

    for e in entries:
        if e.direction == VatDirection.SALE:
            bucket = classify_sale(e)
            d.c20_vat_total += e.vat_amount
            if bucket == SaleBucket.STD20:
                d.c11_base_20 += e.tax_base
            elif bucket == SaleBucket.STD9:
                d.c13_base_9 += e.tax_base
            elif bucket == SaleBucket.EXPORT:
                d.c14_base_export += e.tax_base
            elif bucket == SaleBucket.ICS:
                d.c15_base_ics += e.tax_base
            elif bucket == SaleBucket.TRICOUNTRY:
                d.c17_base_tri += e.tax_base
            elif bucket == SaleBucket.EXEMPT:
                d.c18_base_exempt += e.tax_base
            elif bucket == SaleBucket.REVERSE:
                d.c11_base_20 += e.tax_base
        else:  # PURCHASE
            bucket = classify_purchase(e)
            if bucket == PurchaseBucket.ICA:
                d.c12_base_ica_82 += e.tax_base
                d.c21_vat_ica_82 += e.vat_amount
                d.c20_vat_total += e.vat_amount  # самоначисленият ДДС е и начислен
                d.c31_base_full += e.tax_base
                d.c41_vat_full += e.vat_amount
            elif bucket == PurchaseBucket.FULL:
                d.c31_base_full += e.tax_base
                d.c41_vat_full += e.vat_amount
            elif bucket == PurchaseBucket.PARTIAL:
                d.c33_base_partial += e.tax_base
                d.c42_vat_partial += e.vat_amount
            else:  # NOCREDIT
                d.c30_base_nocredit += e.tax_base

    # к.01 = сумата на облагаемите основи
    d.c01_base_taxable = (
        d.c11_base_20 + d.c12_base_ica_82 + d.c13_base_9 + d.c14_base_export
        + d.c15_base_ics + d.c17_base_tri
    )
    # к.40 общ данъчен кредит (за частичния се прилага коефициент; тук приемаме 1.0)
    d.c40_credit_total = d.c41_vat_full + d.c42_vat_partial

    net = d.c20_vat_total - d.c40_credit_total
    if net >= 0:
        d.c50_vat_payable = net
    else:
        d.c60_vat_refundable = -net
    return d


# ------------------------------------------------------- рендиране на файлове
def render_prodagbi(company: Company, period_code: str, entries: list[VatEntry]) -> str:
    """Дневник за ПРОДАЖБИТЕ (PRODAGBI.TXT) — по един ред на документ."""
    ident = company.vat_number or company.eik or ""
    per = _period_code(period_code)
    lines: list[str] = []
    seq = 0
    for e in entries:
        if e.direction != VatDirection.SALE:
            continue
        seq += 1
        b = classify_sale(e)
        base20 = e.tax_base if b == SaleBucket.STD20 else _ZERO
        vat20 = e.vat_amount if b == SaleBucket.STD20 else _ZERO
        base9 = e.tax_base if b == SaleBucket.STD9 else _ZERO
        vat9 = e.vat_amount if b == SaleBucket.STD9 else _ZERO
        base_export = e.tax_base if b == SaleBucket.EXPORT else _ZERO
        base_ics = e.tax_base if b == SaleBucket.ICS else _ZERO
        base_tri = e.tax_base if b == SaleBucket.TRICOUNTRY else _ZERO
        base_exempt = e.tax_base if b == SaleBucket.EXEMPT else _ZERO
        fields = [
            ident,
            _clip(company.name, 50),
            per,
            f"{seq:05d}",
            _clip(e.document_type or "01", 2),
            _clip(e.document_number, 20),
            _ddmmyyyy(e.document_date),
            _clip(e.counterparty_vat_number, 15),
            _clip(e.counterparty_name, 50),
            _clip((e.document_type and "Стоки/услуги") or "Стоки/услуги", 30),
            _num(e.tax_base + e.vat_amount),  # к.11 общ размер ДО за облагане
            _num(e.vat_amount),               # к.12 всичко начислен ДДС
            _num(base20),                     # к.13
            _num(vat20),                      # к.14
            _num(base9),                      # к.15
            _num(vat9),                       # к.16
            _num(base_export),                # к.17 износ 0%
            _num(base_ics),                   # к.18 ВОД
            _num(base_tri),                   # к.19 тристранни/чл.21
            _num(base_exempt),                # к.20 освободени
        ]
        lines.append(";".join(fields))
    return NEWLINE.join(lines) + (NEWLINE if lines else "")


def render_pokupki(company: Company, period_code: str, entries: list[VatEntry]) -> str:
    """Дневник за ПОКУПКИТЕ (POKUPKI.TXT) — по един ред на документ."""
    ident = company.vat_number or company.eik or ""
    per = _period_code(period_code)
    lines: list[str] = []
    seq = 0
    for e in entries:
        if e.direction != VatDirection.PURCHASE:
            continue
        seq += 1
        b = classify_purchase(e)
        base_full = e.tax_base if b in (PurchaseBucket.FULL, PurchaseBucket.ICA) else _ZERO
        vat_full = e.vat_amount if b in (PurchaseBucket.FULL, PurchaseBucket.ICA) else _ZERO
        base_partial = e.tax_base if b == PurchaseBucket.PARTIAL else _ZERO
        vat_partial = e.vat_amount if b == PurchaseBucket.PARTIAL else _ZERO
        base_nocredit = e.tax_base if b == PurchaseBucket.NOCREDIT else _ZERO
        fields = [
            ident,
            _clip(company.name, 50),
            per,
            f"{seq:05d}",
            _clip(e.document_type or "01", 2),
            _clip(e.document_number, 20),
            _ddmmyyyy(e.document_date),
            _clip(e.counterparty_vat_number, 15),
            _clip(e.counterparty_name, 50),
            _clip("Стоки/услуги", 30),
            _num(base_nocredit),  # к.30 ДО без право на ДК
            _num(base_full),      # к.31 ДО пълен ДК
            _num(vat_full),       # к.41 ДДС пълен ДК
            _num(base_partial),   # к.33 ДО частичен ДК
            _num(vat_partial),    # к.42 ДДС частичен ДК
        ]
        lines.append(";".join(fields))
    return NEWLINE.join(lines) + (NEWLINE if lines else "")


def render_deklar(company: Company, period_code: str, cells: DeclarationCells) -> str:
    """Справка-декларация (DEKLAR.TXT) — клетка;стойност на ред."""
    ident = company.vat_number or company.eik or ""
    per = _period_code(period_code)
    header = ";".join([ident, _clip(company.name, 50), per])
    lines = [header]
    for row in cells.as_rows():
        lines.append(f"{row['cell']};{_num(row['amount'])}")
    return NEWLINE.join(lines) + NEWLINE


def render_vies(company: Company, period_code: str, entries: list[VatEntry]) -> str:
    """VIES декларация — само ВОД и услуги към регистрирани лица в ЕС."""
    ident = company.vat_number or company.eik or ""
    per = _period_code(period_code)
    lines: list[str] = []
    # групиране по ДДС номер на контрагента
    agg: dict[str, Decimal] = {}
    for e in entries:
        if e.direction != VatDirection.SALE:
            continue
        if classify_sale(e) not in (SaleBucket.ICS, SaleBucket.TRICOUNTRY):
            continue
        vat = e.counterparty_vat_number or ""
        agg[vat] = agg.get(vat, _ZERO) + e.tax_base
    for vat_no, base in sorted(agg.items()):
        lines.append(";".join([ident, per, _clip(vat_no, 15), _num(base)]))
    return NEWLINE.join(lines) + (NEWLINE if lines else "")


def build_nap_zip(
    company: Company, period_code: str, entries: list[VatEntry]
) -> tuple[bytes, DeclarationCells]:
    """Пакетира трите задължителни файла (+ VIES при наличие) в ZIP (CP1251)."""
    cells = compute_declaration_cells(entries)
    files = {
        "POKUPKI.TXT": render_pokupki(company, period_code, entries),
        "PRODAGBI.TXT": render_prodagbi(company, period_code, entries),
        "DEKLAR.TXT": render_deklar(company, period_code, cells),
    }
    vies = render_vies(company, period_code, entries)
    if vies.strip():
        files["VIES.TXT"] = vies

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content.encode(ENCODING, errors="replace"))
    return buf.getvalue(), cells
