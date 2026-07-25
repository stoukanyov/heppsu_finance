"""Генериране на PDF за фактури (fpdf2 + Unicode шрифт за кирилица)."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException, status
from fpdf import FPDF

from app.core.config import settings
from app.modules.invoicing.models import Invoice, InvoiceType

# Кандидати за Unicode TTF шрифт (Linux сървър и macOS dev).
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial.ttf",
]

_TITLES = {
    InvoiceType.INVOICE: "ФАКТУРА",
    InvoiceType.PROFORMA: "ПРОФОРМА ФАКТУРА",
    InvoiceType.CREDIT_NOTE: "КРЕДИТНО ИЗВЕСТИЕ",
    InvoiceType.DEBIT_NOTE: "ДЕБИТНО ИЗВЕСТИЕ",
    InvoiceType.ADVANCE: "АВАНСОВА ФАКТУРА",
}


def _font_path() -> str:
    candidates = ([settings.PDF_FONT_PATH] if settings.PDF_FONT_PATH else []) + _FONT_CANDIDATES
    for p in candidates:
        if p and Path(p).is_file():
            return p
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Няма наличен Unicode шрифт за PDF — задай PDF_FONT_PATH към .ttf с кирилица",
    )


def _money(v: Decimal) -> str:
    return f"{Decimal(v):,.2f}".replace(",", " ")


def render_invoice_pdf(company, invoice: Invoice, counterparty) -> bytes:
    pdf = FPDF(unit="mm", format="A4")
    pdf.add_font("uni", "", _font_path())
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    def text(x, y, s, size=10, w=0, align="L"):
        pdf.set_font("uni", size=size)
        pdf.set_xy(x, y)
        pdf.cell(w, 6, str(s or ""), align=align)

    title = _TITLES.get(invoice.invoice_type, "ФАКТУРА")
    text(10, 12, title, size=18)
    text(120, 14, f"№ {invoice.full_number or '(чернова)'}", size=12, w=80, align="R")
    text(120, 21, f"Дата: {invoice.issue_date}", size=10, w=80, align="R")
    if invoice.tax_event_date:
        text(120, 27, f"Дан. събитие: {invoice.tax_event_date}", size=10, w=80, align="R")

    # Доставчик / Получател
    text(10, 34, "ДОСТАВЧИК", size=9)
    text(10, 40, company.name, size=11)
    supplier_ids = " ".join(filter(None, [f"ЕИК {company.eik}" if company.eik else "", f"ДДС {company.vat_number}" if company.vat_number else ""]))
    text(10, 46, supplier_ids, size=9)

    text(110, 34, "ПОЛУЧАТЕЛ", size=9)
    text(110, 40, counterparty.name if counterparty else "", size=11)
    recv_ids = " ".join(filter(None, [f"ЕИК {counterparty.eik}" if counterparty and counterparty.eik else "",
                                       f"ДДС {counterparty.vat_number}" if counterparty and counterparty.vat_number else ""]))
    text(110, 46, recv_ids, size=9)
    if counterparty and counterparty.address:
        text(110, 52, counterparty.address[:60], size=9)

    # Таблица с редовете
    y = 64
    pdf.set_font("uni", size=9)
    cols = [(10, "№", "L"), (22, "Описание", "L"), (120, "К-во", "R"), (145, "Ед. цена", "R"), (175, "Стойност", "R")]
    for x, label, align in cols:
        pdf.set_xy(x, y)
        pdf.cell(25 if align == "R" else 95, 6, label, align=align)
    pdf.line(10, y + 7, 200, y + 7)
    y += 9
    for line in invoice.lines:
        pdf.set_font("uni", size=9)
        pdf.set_xy(10, y); pdf.cell(10, 6, str(line.line_no))
        pdf.set_xy(22, y); pdf.cell(95, 6, str(line.description)[:55])
        pdf.set_xy(120, y); pdf.cell(20, 6, _money(line.quantity), align="R")
        pdf.set_xy(145, y); pdf.cell(25, 6, _money(line.unit_price), align="R")
        pdf.set_xy(175, y); pdf.cell(25, 6, _money(line.line_net), align="R")
        y += 7

    # Тотали
    y += 4
    cur = invoice.currency
    for label, value in [("Данъчна основа:", invoice.subtotal), ("ДДС:", invoice.vat_amount), ("ОБЩО:", invoice.total)]:
        big = label.startswith("ОБЩО")
        pdf.set_font("uni", size=12 if big else 10)
        pdf.set_xy(120, y); pdf.cell(40, 6, label, align="R")
        pdf.set_xy(162, y); pdf.cell(38, 6, f"{_money(value)} {cur}", align="R")
        y += 8 if big else 6

    if invoice.notes:
        pdf.set_font("uni", size=8)
        pdf.set_xy(10, y + 6); pdf.multi_cell(190, 5, str(invoice.notes)[:400])

    pdf.set_font("uni", size=7)
    pdf.set_xy(10, 285); pdf.cell(190, 5, "Генерирано от AI Finance OS", align="C")

    return bytes(pdf.output())
