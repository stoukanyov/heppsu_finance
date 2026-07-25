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
from app.tax_engine.export.validation import (
    ERROR,
    WARNING,
    FieldSpec,
    ValidationReport,
    check_encoding,
    validate_delimited,
)

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


# ------------------------------------------------------ спецификация на полетата
# Единственото място, което знае дължините. Ползва се и от генерирането, и от
# валидацията (`validate_nap_files`) — така описанието не може да се разминe с
# това, което реално се записва. При промяна в спецификацията на НАП се пипа тук.
W_VAT_NO = 15      # идентификационен номер по ЗДДС
W_NAME = 50        # наименование на лицето
W_SEQ = 5          # пореден номер на документа в дневника
W_DOC_TYPE = 2     # вид на документа
W_DOC_NO = 20      # номер на документа
W_DESC = 30        # вид на стоката/услугата

_F = FieldSpec

PRODAGBI_FIELDS: list[FieldSpec] = [
    _F("ЕИК по ЗДДС", W_VAT_NO, required=True),
    _F("Наименование на лицето", W_NAME, required=True),
    _F("Данъчен период", 6, required=True),
    _F("Пореден номер", W_SEQ, required=True),
    _F("Вид на документа", W_DOC_TYPE, required=True),
    _F("Номер на документа", W_DOC_NO, required=True),
    _F("Дата на документа", 10, required=True),
    _F("ЕИК по ЗДДС на контрагента", W_VAT_NO),
    _F("Наименование на контрагента", W_NAME),
    _F("Вид на стоката/услугата", W_DESC),
    _F("к.11 Общ размер на ДО за облагане", 15, numeric=True),
    _F("к.12 Всичко начислен ДДС", 15, numeric=True),
    _F("к.13 ДО облагаема 20%", 15, numeric=True),
    _F("к.14 Начислен ДДС 20%", 15, numeric=True),
    _F("к.15 ДО облагаема 9%", 15, numeric=True),
    _F("к.16 Начислен ДДС 9%", 15, numeric=True),
    _F("к.17 ДО облагаема 0% (износ)", 15, numeric=True),
    _F("к.18 ДО на ВОД", 15, numeric=True),
    _F("к.19 ДО тристранна операция / чл. 21", 15, numeric=True),
    _F("к.20 ДО освободени доставки", 15, numeric=True),
]

POKUPKI_FIELDS: list[FieldSpec] = [
    _F("ЕИК по ЗДДС", W_VAT_NO, required=True),
    _F("Наименование на лицето", W_NAME, required=True),
    _F("Данъчен период", 6, required=True),
    _F("Пореден номер", W_SEQ, required=True),
    _F("Вид на документа", W_DOC_TYPE, required=True),
    _F("Номер на документа", W_DOC_NO, required=True),
    _F("Дата на документа", 10, required=True),
    _F("ЕИК по ЗДДС на контрагента", W_VAT_NO),
    _F("Наименование на контрагента", W_NAME),
    _F("Вид на стоката/услугата", W_DESC),
    _F("к.30 ДО без право на данъчен кредит", 15, numeric=True),
    _F("к.31 ДО с право на пълен данъчен кредит", 15, numeric=True),
    _F("к.41 ДДС с право на пълен данъчен кредит", 15, numeric=True),
    _F("к.33 ДО с право на частичен данъчен кредит", 15, numeric=True),
    _F("к.42 ДДС с право на частичен данъчен кредит", 15, numeric=True),
]

DEKLAR_HEADER_FIELDS: list[FieldSpec] = [
    _F("ЕИК по ЗДДС", W_VAT_NO, required=True),
    _F("Наименование на лицето", W_NAME, required=True),
    _F("Данъчен период", 6, required=True),
]

DEKLAR_ROW_FIELDS: list[FieldSpec] = [
    _F("Номер на клетка", 2, required=True),
    _F("Стойност", 15, numeric=True),
]

VIES_FIELDS: list[FieldSpec] = [
    _F("ЕИК по ЗДДС", W_VAT_NO, required=True),
    _F("Данъчен период", 6, required=True),
    _F("ЕИК по ЗДДС на контрагента", W_VAT_NO, required=True),
    _F("Данъчна основа", 15, numeric=True),
]


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
            _clip(company.name, W_NAME),
            per,
            f"{seq:0{W_SEQ}d}",
            _clip(e.document_type or "01", W_DOC_TYPE),
            _clip(e.document_number, W_DOC_NO),
            _ddmmyyyy(e.document_date),
            _clip(e.counterparty_vat_number, W_VAT_NO),
            _clip(e.counterparty_name, W_NAME),
            _clip((e.document_type and "Стоки/услуги") or "Стоки/услуги", W_DESC),
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
            _clip(company.name, W_NAME),
            per,
            f"{seq:0{W_SEQ}d}",
            _clip(e.document_type or "01", W_DOC_TYPE),
            _clip(e.document_number, W_DOC_NO),
            _ddmmyyyy(e.document_date),
            _clip(e.counterparty_vat_number, W_VAT_NO),
            _clip(e.counterparty_name, W_NAME),
            _clip("Стоки/услуги", W_DESC),
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
    header = ";".join([ident, _clip(company.name, W_NAME), per])
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
        lines.append(";".join([ident, per, _clip(vat_no, W_VAT_NO), _num(base)]))
    return NEWLINE.join(lines) + (NEWLINE if lines else "")


def render_nap_files(
    company: Company, period_code: str, entries: list[VatEntry]
) -> tuple[dict[str, str], DeclarationCells]:
    """Генерира съдържанието на файловете (без пакетиране) + клетките."""
    cells = compute_declaration_cells(entries)
    files = {
        "POKUPKI.TXT": render_pokupki(company, period_code, entries),
        "PRODAGBI.TXT": render_prodagbi(company, period_code, entries),
        "DEKLAR.TXT": render_deklar(company, period_code, cells),
    }
    vies = render_vies(company, period_code, entries)
    if vies.strip():
        files["VIES.TXT"] = vies
    return files, cells


def validate_nap_files(
    company: Company, period_code: str, entries: list[VatEntry]
) -> ValidationReport:
    """Проверява пакета за НАП, преди да е свален и подаден.

    Обхваща три вида грешки: структурни (брой и дължина на полетата), кодировъчни
    (знак, който CP1251 не носи) и контролни (клетките на декларацията срещу
    сумите в дневниците).
    """
    report = ValidationReport(target=f"Пакет за НАП · период {period_code}")
    files, cells = render_nap_files(company, period_code, entries)

    specs = {
        "POKUPKI.TXT": POKUPKI_FIELDS,
        "PRODAGBI.TXT": PRODAGBI_FIELDS,
        "VIES.TXT": VIES_FIELDS,
    }
    for name, content in files.items():
        report.extend(check_encoding(content, ENCODING, source=name))
        if name in specs:
            report.extend(validate_delimited(content, specs[name], source=name))

    # DEKLAR.TXT е с различна структура: заглавен ред + редове „клетка;стойност“.
    deklar = files["DEKLAR.TXT"].splitlines()
    if deklar:
        report.extend(validate_delimited(deklar[0], DEKLAR_HEADER_FIELDS, source="DEKLAR.TXT"))
        body = NEWLINE.join(deklar[1:])
        report.extend(validate_delimited(body, DEKLAR_ROW_FIELDS, source="DEKLAR.TXT"))

    # --- контролни суми ---
    # Начисленият ДДС по к.20 е този от продажбите плюс самоначисленият по ВОП/чл.82.
    charged = sum(
        (
            e.vat_amount
            for e in entries
            if e.direction == VatDirection.SALE
            or classify_purchase(e) == PurchaseBucket.ICA
        ),
        _ZERO,
    )
    if cells.c20_vat_total != charged:
        report.add(
            ERROR,
            f"Клетка 20 ({cells.c20_vat_total}) не съвпада с начисления ДДС по записите "
            f"({charged}) — продажбите плюс самоначисления по ВОП и чл. 82",
            path="к.20",
            source="DEKLAR.TXT",
        )

    sum_of_bases = (
        cells.c11_base_20 + cells.c12_base_ica_82 + cells.c13_base_9
        + cells.c14_base_export + cells.c15_base_ics + cells.c17_base_tri
    )
    if cells.c01_base_taxable != sum_of_bases:
        report.add(
            ERROR,
            f"Клетка 01 ({cells.c01_base_taxable}) не е сборът на клетки 11, 12, 13, 14, "
            f"15 и 17 ({sum_of_bases})",
            path="к.01",
            source="DEKLAR.TXT",
        )

    if cells.c40_credit_total != cells.c41_vat_full + cells.c42_vat_partial:
        report.add(
            ERROR,
            "Клетка 40 не е сборът на клетки 41 и 42",
            path="к.40",
            source="DEKLAR.TXT",
        )

    if cells.c50_vat_payable > _ZERO and cells.c60_vat_refundable > _ZERO:
        report.add(
            ERROR,
            "Едновременно попълнени клетка 50 (за внасяне) и клетка 60 (за възстановяване) "
            "— взаимно изключващи се",
            path="к.50/60",
            source="DEKLAR.TXT",
        )
    net = cells.c20_vat_total - cells.c40_credit_total
    if cells.c50_vat_payable - cells.c60_vat_refundable != net:
        report.add(
            ERROR,
            f"Резултатът за периода ({cells.c50_vat_payable - cells.c60_vat_refundable}) "
            f"не отговаря на клетка 20 минус клетка 40 ({net})",
            path="к.50/60",
            source="DEKLAR.TXT",
        )

    # Дневникът за продажбите срещу декларацията: сборът на колона к.12 в дневника
    # трябва да е начисленият ДДС от продажби.
    sales_vat = sum(
        (e.vat_amount for e in entries if e.direction == VatDirection.SALE), _ZERO
    )
    journal_vat = _ZERO
    for row in files["PRODAGBI.TXT"].splitlines():
        parts = row.split(";")
        if len(parts) == len(PRODAGBI_FIELDS):
            journal_vat += Decimal(parts[11])
    if journal_vat != sales_vat:
        report.add(
            ERROR,
            f"Сборът на колона к.12 в дневника за продажбите ({journal_vat}) не съвпада "
            f"с начисления ДДС по записите ({sales_vat})",
            source="PRODAGBI.TXT",
        )

    # --- реквизити, без които НАП отхвърля подаването ---
    if not (company.vat_number or company.eik):
        report.add(ERROR, "Липсва идентификационен номер на дружеството (ДДС номер или ЕИК)")
    if not company.vat_number:
        report.add(WARNING, "Липсва ДДС номер — подава се ЕИК, което НАП може да не приеме")
    if not entries:
        report.add(WARNING, "В периода няма ДДС записи — подава се празна декларация")

    missing_cp = sum(
        1 for e in entries if not (e.counterparty_vat_number or e.counterparty_name)
    )
    if missing_cp:
        report.add(
            WARNING,
            f"{missing_cp} записа са без данни за контрагента — проверете ги преди подаване",
        )
    return report


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
