"""Електронна фактура по EN 16931 — UBL 2.1 / PEPPOL BIS Billing 3.0.

Подготовка, не спешност: B2B мандатът в България още няма законов срок, но се очаква
след разгръщането на SAF-T. Затова е направено като **още един export провайдър** през
същия регистър, а не като преработка на модула `invoicing` — при мандат се сменя версия,
не се пипа ядрото.

Съзнателно **не се изпраща по мрежата PEPPOL**. Изпращането иска Access Point (акредитиран
доставчик, договор, сертификати) и е отделно решение. Тук се генерира и се чете файл.

Бизнес правилата (BR-xx) са подмножеството, което реално отхвърля документ: без тях
файлът минава XSD-то, но го връща получателят. По-полезно е да се хванат тук.
"""
from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from decimal import Decimal

from app.tax_engine.export.base import ExportProvider, ExportResult
from app.tax_engine.export.validation import ERROR, WARNING, ValidationReport

ZERO = Decimal("0.00")

# Пространствата от имена по UBL 2.1.
NS_INVOICE = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
NS_CREDIT = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

PEPPOL_CUSTOMIZATION = (
    "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
)
PEPPOL_PROFILE = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"

# UNTDID 1001 — вид на документа. 380 фактура, 381 кредитно, 383 дебитно известие.
TYPE_INVOICE = "380"
TYPE_CREDIT_NOTE = "381"
TYPE_DEBIT_NOTE = "383"


def _q(tag: str, ns: str = NS_CBC) -> str:
    return f"{{{ns}}}{tag}"


def _sub(parent: ET.Element, tag: str, text=None, ns: str = NS_CBC, **attrs) -> ET.Element:
    node = ET.SubElement(parent, _q(tag, ns), attrs)
    if text is not None:
        node.text = str(text)
    return node


def _money(value: Decimal | None) -> str:
    return f"{(value if value is not None else ZERO):.2f}"


class UblBisBillingProvider(ExportProvider):
    """PEPPOL BIS Billing 3.0 (EN 16931), UBL 2.1."""

    code = "UBL_BIS"
    name = "Електронна фактура EN 16931 (PEPPOL BIS Billing 3.0)"
    version = "3.0"
    media_type = "application/xml"

    # ------------------------------------------------------------------ износ
    def export(self, company, context: dict) -> ExportResult:
        """Генерира UBL документ за една фактура.

        Очаква в `context`: `invoice` (модел `Invoice`), `counterparty`, `vat_rate`.
        """
        invoice = context["invoice"]
        counterparty = context["counterparty"]
        vat_rate: Decimal = context.get("vat_rate") or ZERO

        credit = context.get("document_type_code") == TYPE_CREDIT_NOTE
        ns_root = NS_CREDIT if credit else NS_INVOICE
        root = ET.Element(
            _q("CreditNote" if credit else "Invoice", ns_root),
            {"xmlns": ns_root, "xmlns:cac": NS_CAC, "xmlns:cbc": NS_CBC},
        )

        _sub(root, "CustomizationID", PEPPOL_CUSTOMIZATION)
        _sub(root, "ProfileID", PEPPOL_PROFILE)
        _sub(root, "ID", _invoice_number(invoice))
        _sub(root, "IssueDate", invoice.issue_date.isoformat())
        if invoice.due_date and not credit:
            _sub(root, "DueDate", invoice.due_date.isoformat())
        _sub(
            root,
            "CreditNoteTypeCode" if credit else "InvoiceTypeCode",
            context.get("document_type_code") or TYPE_INVOICE,
        )
        if invoice.notes:
            _sub(root, "Note", invoice.notes)
        _sub(root, "DocumentCurrencyCode", invoice.currency)

        self._party(root, "AccountingSupplierParty", company.name, company.eik,
                    company.vat_number, getattr(company, "address_line", None),
                    getattr(company, "address_city", None),
                    getattr(company, "address_postcode", None),
                    getattr(company, "country", "BG"))
        self._party(root, "AccountingCustomerParty", counterparty.name, counterparty.eik,
                    counterparty.vat_number, getattr(counterparty, "address", None),
                    None, None, getattr(counterparty, "country", "BG"))

        # --- данъчно обобщение ---
        tax_total = ET.SubElement(root, _q("TaxTotal", NS_CAC))
        _sub(tax_total, "TaxAmount", _money(invoice.vat_amount), currencyID=invoice.currency)
        subtotal = ET.SubElement(tax_total, _q("TaxSubtotal", NS_CAC))
        _sub(subtotal, "TaxableAmount", _money(invoice.subtotal), currencyID=invoice.currency)
        _sub(subtotal, "TaxAmount", _money(invoice.vat_amount), currencyID=invoice.currency)
        category = ET.SubElement(subtotal, _q("TaxCategory", NS_CAC))
        _sub(category, "ID", _tax_category(vat_rate))
        _sub(category, "Percent", f"{vat_rate:.2f}")
        scheme = ET.SubElement(category, _q("TaxScheme", NS_CAC))
        _sub(scheme, "ID", "VAT")

        # --- суми на документа ---
        totals = ET.SubElement(root, _q("LegalMonetaryTotal", NS_CAC))
        _sub(totals, "LineExtensionAmount", _money(invoice.subtotal), currencyID=invoice.currency)
        _sub(totals, "TaxExclusiveAmount", _money(invoice.subtotal), currencyID=invoice.currency)
        _sub(totals, "TaxInclusiveAmount", _money(invoice.total), currencyID=invoice.currency)
        _sub(totals, "PayableAmount", _money(invoice.total), currencyID=invoice.currency)

        # --- редове ---
        line_tag = "CreditNoteLine" if credit else "InvoiceLine"
        qty_tag = "CreditedQuantity" if credit else "InvoicedQuantity"
        for line in sorted(invoice.lines, key=lambda x: x.line_no):
            node = ET.SubElement(root, _q(line_tag, NS_CAC))
            _sub(node, "ID", str(line.line_no))
            _sub(node, qty_tag, f"{line.quantity:.3f}", unitCode="C62")   # C62 = брой
            _sub(node, "LineExtensionAmount", _money(line.line_net), currencyID=invoice.currency)
            item = ET.SubElement(node, _q("Item", NS_CAC))
            _sub(item, "Name", line.description[:100])
            item_tax = ET.SubElement(item, _q("ClassifiedTaxCategory", NS_CAC))
            _sub(item_tax, "ID", _tax_category(vat_rate))
            _sub(item_tax, "Percent", f"{vat_rate:.2f}")
            item_scheme = ET.SubElement(item_tax, _q("TaxScheme", NS_CAC))
            _sub(item_scheme, "ID", "VAT")
            price = ET.SubElement(node, _q("Price", NS_CAC))
            _sub(price, "PriceAmount", f"{line.unit_price:.4f}", currencyID=invoice.currency)

        body = ET.tostring(root, encoding="unicode")
        xml = f'<?xml version="1.0" encoding="UTF-8"?>\n{body}'
        return ExportResult(
            filename=f"{_invoice_number(invoice)}-ubl.xml",
            content=xml.encode("utf-8"),
            media_type=self.media_type,
            contents=[
                f"{'Кредитно известие' if credit else 'Фактура'} {_invoice_number(invoice)}",
                f"{len(invoice.lines)} реда · {_money(invoice.total)} {invoice.currency}",
                "Формат: EN 16931 / PEPPOL BIS Billing 3.0 (UBL 2.1)",
            ],
            warnings=["Файлът не се изпраща по мрежата PEPPOL — това иска Access Point."],
        )

    def _party(self, root, wrapper: str, name: str, eik, vat, street, city, postcode, country):
        node = ET.SubElement(root, _q(wrapper, NS_CAC))
        party = ET.SubElement(node, _q("Party", NS_CAC))
        if vat:
            endpoint = _sub(party, "EndpointID", vat)
            endpoint.set("schemeID", "9926")   # 9926 = български ДДС номер в PEPPOL
        address = ET.SubElement(party, _q("PostalAddress", NS_CAC))
        if street:
            _sub(address, "StreetName", street)
        if city:
            _sub(address, "CityName", city)
        if postcode:
            _sub(address, "PostalZone", postcode)
        country_node = ET.SubElement(address, _q("Country", NS_CAC))
        _sub(country_node, "IdentificationCode", country or "BG")
        if vat:
            scheme = ET.SubElement(party, _q("PartyTaxScheme", NS_CAC))
            _sub(scheme, "CompanyID", vat)
            tax_scheme = ET.SubElement(scheme, _q("TaxScheme", NS_CAC))
            _sub(tax_scheme, "ID", "VAT")
        legal = ET.SubElement(party, _q("PartyLegalEntity", NS_CAC))
        _sub(legal, "RegistrationName", name)
        if eik:
            _sub(legal, "CompanyID", eik)

    # ------------------------------------------------------------------ валидация
    def validate(self, xml: bytes) -> ValidationReport:
        """Проверява документа срещу задължителните бизнес правила на EN 16931.

        Формалната XSD проверка иска официалните UBL схеми; те се слагат в
        `schemas/` както при SAF-T. Правилата тук важат независимо от това и ловят
        точно случаите, в които получателят връща документа.
        """
        report = ValidationReport(target="Електронна фактура EN 16931 / PEPPOL BIS 3.0")
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            report.add(ERROR, f"Файлът не е валиден XML: {exc}")
            return report

        def cbc(node, tag: str) -> str:
            found = node.find(_q(tag))
            return (found.text or "").strip() if found is not None else ""

        rules = [
            ("BR-01", "CustomizationID", "Липсва идентификатор на спецификацията (CustomizationID)"),
            ("BR-02", "ID", "Липсва номер на фактурата"),
            ("BR-03", "IssueDate", "Липсва дата на издаване"),
            ("BR-04", "InvoiceTypeCode", "Липсва код за вид на документа"),
            ("BR-05", "DocumentCurrencyCode", "Липсва валута на документа"),
        ]
        is_credit = root.tag.endswith("CreditNote")
        for code, tag, message in rules:
            if is_credit and tag == "InvoiceTypeCode":
                tag = "CreditNoteTypeCode"
            if not cbc(root, tag):
                report.add(ERROR, f"{code}: {message}", path=f"/{tag}")

        # BR-06 / BR-07 — наименование на продавача и на купувача.
        for wrapper, code, label in (
            ("AccountingSupplierParty", "BR-06", "продавача"),
            ("AccountingCustomerParty", "BR-07", "купувача"),
        ):
            node = root.find(_q(wrapper, NS_CAC))
            name = ""
            if node is not None:
                legal = node.find(f"{_q('Party', NS_CAC)}/{_q('PartyLegalEntity', NS_CAC)}")
                if legal is not None:
                    name = (legal.findtext(_q("RegistrationName")) or "").strip()
            if not name:
                report.add(ERROR, f"{code}: Липсва наименование на {label}", path=f"/{wrapper}")

        # BR-16 — поне един ред.
        line_tag = "CreditNoteLine" if is_credit else "InvoiceLine"
        lines = root.findall(_q(line_tag, NS_CAC))
        if not lines:
            report.add(ERROR, "BR-16: Документът трябва да има поне един ред")

        # BR-CO-10 / BR-CO-13 / BR-CO-15 — сумите трябва да се връзват.
        totals = root.find(_q("LegalMonetaryTotal", NS_CAC))
        if totals is None:
            report.add(ERROR, "BR-13: Липсва секция със сумите на документа")
            return report

        line_sum = sum(
            (_to_decimal(node.findtext(_q("LineExtensionAmount"))) for node in lines), ZERO
        )
        declared_lines = _to_decimal(totals.findtext(_q("LineExtensionAmount")))
        if declared_lines != line_sum:
            report.add(
                ERROR,
                f"BR-CO-10: Сборът на редовете ({line_sum}) не съвпада с обявената сума "
                f"({declared_lines})",
                path="/LegalMonetaryTotal/LineExtensionAmount",
            )

        exclusive = _to_decimal(totals.findtext(_q("TaxExclusiveAmount")))
        inclusive = _to_decimal(totals.findtext(_q("TaxInclusiveAmount")))
        payable = _to_decimal(totals.findtext(_q("PayableAmount")))
        tax_total = root.find(_q("TaxTotal", NS_CAC))
        tax_amount = _to_decimal(tax_total.findtext(_q("TaxAmount"))) if tax_total is not None else ZERO

        if inclusive != exclusive + tax_amount:
            report.add(
                ERROR,
                f"BR-CO-13: Сумата с данък ({inclusive}) не е сумата без данък ({exclusive}) "
                f"плюс данъка ({tax_amount})",
                path="/LegalMonetaryTotal/TaxInclusiveAmount",
            )
        if payable != inclusive:
            report.add(
                ERROR,
                f"BR-CO-15: Дължимата сума ({payable}) не съвпада със сумата с данък ({inclusive})",
                path="/LegalMonetaryTotal/PayableAmount",
            )

        # Липсващ ДДС номер не е грешка по стандарта, но за БГ фактура е проблем.
        supplier = root.find(_q("AccountingSupplierParty", NS_CAC))
        if supplier is not None:
            endpoint = supplier.find(f"{_q('Party', NS_CAC)}/{_q('EndpointID')}")
            if endpoint is None or not (endpoint.text or "").strip():
                report.add(
                    WARNING,
                    "Липсва електронен адрес на продавача (EndpointID) — без него документът "
                    "не може да се маршрутизира в PEPPOL",
                    path="/AccountingSupplierParty/Party/EndpointID",
                )
        return report


def parse_ubl(xml: bytes) -> dict:
    """Чете входяща e-фактура и връща данните за чернова покупка.

    Замества OCR: когато доставчикът прати структуриран документ, няма какво да се
    разпознава — данните вече са машинни.
    """
    root = ET.fromstring(xml)
    is_credit = root.tag.endswith("CreditNote")

    def cbc(node, tag: str) -> str | None:
        found = node.find(_q(tag))
        text = (found.text or "").strip() if found is not None else ""
        return text or None

    supplier_name = supplier_eik = supplier_vat = None
    supplier = root.find(_q("AccountingSupplierParty", NS_CAC))
    if supplier is not None:
        party = supplier.find(_q("Party", NS_CAC))
        if party is not None:
            legal = party.find(_q("PartyLegalEntity", NS_CAC))
            if legal is not None:
                supplier_name = (legal.findtext(_q("RegistrationName")) or "").strip() or None
                supplier_eik = (legal.findtext(_q("CompanyID")) or "").strip() or None
            endpoint = party.find(_q("EndpointID"))
            if endpoint is not None:
                supplier_vat = (endpoint.text or "").strip() or None

    totals = root.find(_q("LegalMonetaryTotal", NS_CAC))
    tax_total = root.find(_q("TaxTotal", NS_CAC))
    line_tag = "CreditNoteLine" if is_credit else "InvoiceLine"
    qty_tag = "CreditedQuantity" if is_credit else "InvoicedQuantity"

    lines = []
    for node in root.findall(_q(line_tag, NS_CAC)):
        item = node.find(_q("Item", NS_CAC))
        price = node.find(_q("Price", NS_CAC))
        lines.append({
            "line_no": int(cbc(node, "ID") or len(lines) + 1),
            "description": (item.findtext(_q("Name")) if item is not None else None) or "Стока/услуга",
            "quantity": _to_decimal(cbc(node, qty_tag) or "1"),
            "unit_price": _to_decimal(price.findtext(_q("PriceAmount")) if price is not None else "0"),
            "line_net": _to_decimal(cbc(node, "LineExtensionAmount")),
        })

    issue_date = cbc(root, "IssueDate")
    return {
        "document_type": "CREDIT_NOTE" if is_credit else "INVOICE",
        "document_number": cbc(root, "ID"),
        "issue_date": dt.date.fromisoformat(issue_date) if issue_date else None,
        "due_date": (dt.date.fromisoformat(cbc(root, "DueDate")) if cbc(root, "DueDate") else None),
        "currency": cbc(root, "DocumentCurrencyCode") or "EUR",
        "supplier_name": supplier_name,
        "supplier_eik": supplier_eik,
        "supplier_vat_number": supplier_vat,
        "subtotal": _to_decimal(totals.findtext(_q("TaxExclusiveAmount")) if totals is not None else "0"),
        "vat_amount": _to_decimal(tax_total.findtext(_q("TaxAmount")) if tax_total is not None else "0"),
        "total": _to_decimal(totals.findtext(_q("PayableAmount")) if totals is not None else "0"),
        "notes": cbc(root, "Note"),
        "lines": lines,
    }


def _invoice_number(invoice) -> str:
    if invoice.number is None:
        return f"{invoice.series}DRAFT" if invoice.series else "DRAFT"
    return f"{invoice.series}{invoice.number:010d}" if invoice.series else f"{invoice.number:010d}"


def _tax_category(rate: Decimal) -> str:
    """UNCL5305: S = стандартна ставка, Z = нулева, E = освободена."""
    if rate > ZERO:
        return "S"
    return "Z"


def _to_decimal(value: str | None) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except Exception:
        return ZERO
