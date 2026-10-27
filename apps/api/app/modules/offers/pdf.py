"""PDF на офертата — оформление по сайта heppsu.com.

Палитрата, шрифтовите роли и златните линии идват от `assets/css/style.css` на
сайта: сериф за заглавията, санс за текста, злато за линиите и рамките, кремав
фон вместо тъмния на сайта. Тъмен фон върху хартия изяжда тонер и прави текста
нечетим при печат — затова палитрата е обърната, а не копирана.

Четимост: `#9C7C3C` (сайтовото тъмно злато) върху кремаво дава контраст 3,67:1 и
не минава 4,5:1. Затова дребният златен текст е `#7F6228`, а същинското злато
остава за линии, рамки и големите декоративни елементи.

Шрифтът е DejaVu (сериф и санс), защото носи кирилица и е в образа. Cormorant
Garamond от сайта не се вгражда — няма го на сървъра, а да го носим в репото е
отделно решение за лиценз и размер.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException, status
from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.core.config import settings
from app.modules.offers import brand, markup
from app.modules.offers.markup import Block, Run
from app.modules.offers.models import Offer

# ---------------------------------------------------------------- палитра
CREAM = (251, 248, 243)       # хартията
INK = (36, 30, 26)            # основен текст (--ground на сайта)
MUTED = (122, 110, 99)        # второстепенен текст
GOLD = (201, 169, 97)         # --gold: линии, рамки, декор
GOLD_TEXT = (127, 98, 40)     # дребен златен текст с достатъчен контраст
LINE = (226, 213, 185)        # тънка разделителна линия

# ---------------------------------------------------------------- геометрия (mm)
PAGE_W, PAGE_H = 210.0, 297.0
MARGIN = 18.0
CONTENT_W = PAGE_W - 2 * MARGIN
HEADER_H = 46.0               # височината на шапката на всяка страница
FOOTER_TOP = 276.0            # над този ред не се пише текст

LOGO_W = 26.0
LOGO_H = LOGO_W * 591 / 775   # пропорцията на файла, за да не се деформира

# Кандидати за шрифт: първо Linux (образът носи fonts-dejavu-core), после macOS.
_SANS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]
_SANS_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
_SERIF = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/dejavu/DejaVuSerif.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
]
_SERIF_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSerif-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
]

_STATUS_LABELS = {
    "DRAFT": "ЧЕРНОВА",
    "SENT": "ИЗПРАТЕНА",
    "ACCEPTED": "ПРИЕТА",
    "DECLINED": "ОТКАЗАНА",
}


def _first_existing(candidates: list[str], *, required: bool) -> str | None:
    # `PDF_FONT_PATH` е НАКРАЯ нарочно, обратно на фактурите: там шрифтът е един,
    # а тук са четири роли (sans, sans-bold, serif, serif-bold). Ако зададеният
    # файл печелеше, и четирите щяха да сочат него — оформлението по сайта губи
    # serif-а и болда. Тук настройката е резервен вариант, не предпочитание.
    override = [settings.PDF_FONT_PATH] if settings.PDF_FONT_PATH else []
    for path in [*candidates, *override]:
        if path and Path(path).is_file():
            return path
    if required:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Няма наличен Unicode шрифт за PDF — задай PDF_FONT_PATH към .ttf с кирилица",
        )
    return None


def _money(value: Decimal) -> str:
    """1234.5 → „1 234,50" — както се пише на български."""
    text = f"{Decimal(value):,.2f}"
    return text.replace(",", " ").replace(".", ",")


def _qty(value: Decimal) -> str:
    """Количеството без излишните нули: 2.000 → „2", 1.500 → „1,5"."""
    normalized = Decimal(value).normalize()
    if normalized == normalized.to_integral_value():
        normalized = normalized.to_integral_value()
    return f"{normalized:f}".replace(".", ",")


def _date(value: dt.date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


class _OfferPDF(FPDF):
    """Страницата с шапката и подписа — рисуват се на всяка страница.

    `header()` и `footer()` се викат от fpdf2 и при автоматичното прехвърляне на
    нова страница; затова кремавият фон и златните линии не се пропускат, когато
    текстът на офертата стане по-дълъг от една страница.
    """

    def __init__(self, company, offer: Offer, counterparty) -> None:
        super().__init__(unit="mm", format="A4")
        self.company = company
        self.offer = offer
        self.counterparty = counterparty
        self.set_auto_page_break(auto=True, margin=PAGE_H - FOOTER_TOP + 4)
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.set_title(f"{offer.full_number} — {offer.title}")
        self.set_creator("AI Finance OS")

        self.add_font("sans", "", _first_existing(_SANS, required=True))
        bold = _first_existing(_SANS_BOLD, required=False)
        self.add_font("sans", "B", bold or _first_existing(_SANS, required=True))
        serif = _first_existing(_SERIF, required=False) or _first_existing(_SANS, required=True)
        self.add_font("serif", "", serif)
        serif_bold = _first_existing(_SERIF_BOLD, required=False)
        self.add_font("serif", "B", serif_bold or serif)

    # ------------------------------------------------------------ шапка
    def header(self) -> None:
        self.set_fill_color(*CREAM)
        self.rect(0, 0, PAGE_W, PAGE_H, style="F")

        # Златната линия най-горе — същият акцент като на сайта.
        self.set_fill_color(*GOLD)
        self.rect(0, 0, PAGE_W, 1.2, style="F")

        logo = brand.logo_for(self.company)
        if logo is not None:
            self.image(str(logo), x=MARGIN, y=13, w=LOGO_W)
        else:
            # Чуждо дружество носи името си, не чужд знак.
            self.set_font("serif", "B", 15)
            self.set_text_color(*INK)
            self.set_xy(MARGIN, 18)
            self.cell(100, 8, self.company.name)

        # Дясна страна: „ОФЕРТА" с разредка и номерът със сериф.
        self._letterspaced("ОФЕРТА", x=PAGE_W - MARGIN, y=15, size=8.5,
                           color=GOLD_TEXT, spacing=1.6, align="R")
        self.set_font("serif", "B", 17)
        self.set_text_color(*INK)
        self.set_xy(PAGE_W - MARGIN - 70, 19.5)
        self.cell(70, 8, self.offer.full_number, align="R",
                  new_x=XPos.LEFT, new_y=YPos.NEXT)

        if self.offer.status.value != "SENT":
            self._letterspaced(_STATUS_LABELS.get(self.offer.status.value, ""),
                               x=PAGE_W - MARGIN, y=29, size=7, color=MUTED,
                               spacing=1.2, align="R")

        self.set_draw_color(*GOLD)
        self.set_line_width(0.3)
        self.line(MARGIN, HEADER_H - 6, PAGE_W - MARGIN, HEADER_H - 6)

        self.set_xy(MARGIN, HEADER_H)
        self.set_text_color(*INK)

    # ------------------------------------------------------------ долен колонтитул
    def footer(self) -> None:
        self.set_draw_color(*LINE)
        self.set_line_width(0.2)
        self.line(MARGIN, FOOTER_TOP + 4, PAGE_W - MARGIN, FOOTER_TOP + 4)

        requisites = " · ".join(
            part
            for part in [
                self.company.name,
                f"ЕИК {self.company.eik}" if self.company.eik else "",
                f"ДДС {self.company.vat_number}" if self.company.vat_number else "",
                self.company.address_line or "",
            ]
            if part
        )
        self.set_font("sans", "", 6.8)
        self.set_text_color(*MUTED)
        self.set_xy(MARGIN, FOOTER_TOP + 7)
        self.cell(CONTENT_W - 14, 4, requisites[:150])
        self.set_xy(PAGE_W - MARGIN - 14, FOOTER_TOP + 7)
        self.cell(14, 4, f"{self.page_no()} / {{nb}}", align="R")

    # ------------------------------------------------------------ помощни
    def _letterspaced(self, text: str, *, x: float, y: float, size: float,
                      color: tuple[int, int, int], spacing: float, align: str = "L") -> None:
        """Разреден текст — разредката на сайта за малките надписи с главни букви.

        fpdf2 не умее letter-spacing, затова интервалите се вмъкват в самия низ.
        """
        spaced = " ".join(text)
        self.set_font("sans", "", size)
        self.set_text_color(*color)
        width = 80.0
        self.set_xy(x - width if align == "R" else x, y)
        self.set_char_spacing(spacing * 0.6)
        self.cell(width, 5, spaced, align=align)
        self.set_char_spacing(0)

    def write_runs(self, runs: list[Run], *, family: str, size: float,
                   color: tuple[int, int, int], line_h: float) -> None:
        """Изписва отрязъците един след друг — получерът е в реда, не отделен абзац."""
        self.set_text_color(*color)
        for run in runs:
            self.set_font(family, "B" if run.bold else "", size)
            self.write(line_h, run.text)
        self.ln(line_h)


def _draw_meta(pdf: _OfferPDF, offer: Offer) -> None:
    """Трите дати: изготвяне, срок и крайна дата в златна рамка."""
    y = pdf.get_y() + 2
    column = CONTENT_W / 3
    cells = [
        ("ДАТА НА ИЗГОТВЯНЕ", _date(offer.issue_date), False),
        ("СРОК НА ВАЛИДНОСТ", f"{offer.validity_days} дни", False),
        ("ВАЛИДНА ДО", _date(offer.valid_until), True),
    ]
    for index, (label, value, framed) in enumerate(cells):
        x = MARGIN + index * column
        if framed:
            pdf.set_draw_color(*GOLD)
            pdf.set_line_width(0.3)
            pdf.set_fill_color(247, 241, 228)
            pdf.rect(x - 1, y - 1, column - 2, 15, style="DF")
        pdf._letterspaced(label, x=x + 1.5, y=y, size=6.6, color=GOLD_TEXT, spacing=1.1)
        pdf.set_font("serif", "B" if framed else "", 11.5)
        pdf.set_text_color(*INK)
        pdf.set_xy(x + 1.5, y + 5.5)
        pdf.cell(column - 4, 7, value)
    pdf.set_xy(MARGIN, y + 17)


def _draw_recipient(pdf: _OfferPDF, counterparty) -> None:
    """Блокът „До" със златна черта отляво."""
    if counterparty is None:
        return
    y = pdf.get_y()
    lines = [counterparty.name]
    ids = " · ".join(
        part
        for part in [
            f"ЕИК {counterparty.eik}" if counterparty.eik else "",
            f"ДДС {counterparty.vat_number}" if counterparty.vat_number else "",
        ]
        if part
    )
    if ids:
        lines.append(ids)
    if counterparty.address:
        lines.append(counterparty.address[:90])
    if counterparty.contact_person:
        lines.append(f"на вниманието на {counterparty.contact_person}")

    height = 6 + 5.2 * len(lines)
    pdf.set_fill_color(*GOLD)
    pdf.rect(MARGIN, y, 0.9, height, style="F")

    pdf._letterspaced("ДО", x=MARGIN + 4, y=y - 0.5, size=6.6, color=GOLD_TEXT, spacing=1.1)
    pdf.set_xy(MARGIN + 4, y + 4.5)
    pdf.set_font("serif", "B", 12)
    pdf.set_text_color(*INK)
    pdf.cell(CONTENT_W - 4, 6, lines[0], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    for extra in lines[1:]:
        pdf.set_x(MARGIN + 4)
        pdf.set_font("sans", "", 8.6)
        pdf.set_text_color(*MUTED)
        pdf.cell(CONTENT_W - 4, 5, extra, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_xy(MARGIN, y + height + 3.5)


def _draw_title(pdf: _OfferPDF, title: str) -> None:
    pdf.set_font("serif", "B", 19)
    pdf.set_text_color(*INK)
    pdf.set_x(MARGIN)
    pdf.multi_cell(CONTENT_W, 9, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    y = pdf.get_y() + 2
    pdf.set_draw_color(*GOLD)
    pdf.set_line_width(0.8)
    pdf.line(MARGIN, y, MARGIN + 34, y)
    pdf.set_xy(MARGIN, y + 5)


def _draw_items_table(pdf: _OfferPDF, offer: Offer) -> None:
    """Таблицата с позициите и сметката под нея."""
    if not offer.lines:
        return

    # № / Описание / К-во / Ед. цена / Сума — ширините сборно дават CONTENT_W.
    widths = [8.0, CONTENT_W - 8.0 - 18.0 - 27.0 - 29.0, 18.0, 27.0, 29.0]
    headers = ["№", "Описание", "К-во", "Ед. цена", "Сума"]
    aligns = ["L", "L", "R", "R", "R"]

    pdf.set_font("sans", "", 6.8)
    pdf.set_text_color(*GOLD_TEXT)
    y = pdf.get_y()
    x = MARGIN
    for width, header, align in zip(widths, headers, aligns, strict=True):
        pdf.set_xy(x, y)
        pdf.cell(width, 5, header.upper(), align=align)
        x += width
    pdf.set_draw_color(*GOLD)
    pdf.set_line_width(0.3)
    pdf.line(MARGIN, y + 5.4, PAGE_W - MARGIN, y + 5.4)
    pdf.set_xy(MARGIN, y + 7)

    for line in offer.lines:
        # Високо описание пренася реда — височината се мери преди рисуването,
        # за да не се застъпят съседните колони.
        pdf.set_font("sans", "", 9)
        description = line.description
        text_lines = pdf.multi_cell(widths[1], 5, description, dry_run=True, output="LINES")
        row_h = max(6.0, 5.0 * len(text_lines))

        if pdf.get_y() + row_h > FOOTER_TOP:
            pdf.add_page()

        y = pdf.get_y()
        pdf.set_text_color(*MUTED)
        pdf.set_font("sans", "", 8)
        pdf.set_xy(MARGIN, y)
        pdf.cell(widths[0], 5, str(line.line_no))

        pdf.set_text_color(*INK)
        pdf.set_font("sans", "", 9)
        pdf.set_xy(MARGIN + widths[0], y)
        pdf.multi_cell(widths[1], 5, description, new_x=XPos.LEFT, new_y=YPos.TOP)

        quantity = _qty(line.quantity) + (f" {line.unit}" if line.unit else "")
        values = [quantity, _money(line.unit_price), _money(line.line_net)]
        x = MARGIN + widths[0] + widths[1]
        for width, value, bold in zip(widths[2:], values, [False, False, True], strict=True):
            pdf.set_font("sans", "B" if bold else "", 9)
            pdf.set_xy(x, y)
            pdf.cell(width, 5, value, align="R")
            x += width

        pdf.set_xy(MARGIN, y + row_h)
        pdf.set_draw_color(*LINE)
        pdf.set_line_width(0.15)
        pdf.line(MARGIN, pdf.get_y() - 1, PAGE_W - MARGIN, pdf.get_y() - 1)

    _draw_totals(pdf, offer)


def _draw_totals(pdf: _OfferPDF, offer: Offer) -> None:
    box_w = 86.0
    x = PAGE_W - MARGIN - box_w
    y = pdf.get_y() + 3

    if y + 28 > FOOTER_TOP:
        pdf.add_page()
        y = pdf.get_y() + 3

    rows = [
        ("Данъчна основа", _money(offer.subtotal)),
        (f"ДДС {_qty(offer.vat_rate)}%", _money(offer.vat_amount)),
    ]
    for label, value in rows:
        pdf.set_font("sans", "", 8.6)
        pdf.set_text_color(*MUTED)
        pdf.set_xy(x, y)
        pdf.cell(box_w - 34, 5, label, align="R")
        pdf.set_font("sans", "", 9)
        pdf.set_text_color(*INK)
        pdf.set_xy(x + box_w - 34, y)
        pdf.cell(34, 5, f"{value} {offer.currency}", align="R")
        y += 5.6

    y += 1.5
    pdf.set_draw_color(*GOLD)
    pdf.set_line_width(0.3)
    pdf.set_fill_color(247, 241, 228)
    pdf.rect(x, y, box_w, 13, style="DF")
    pdf._letterspaced("ОБЩО ЗА ПЛАЩАНЕ", x=x + 3, y=y + 1.3, size=6.6,
                      color=GOLD_TEXT, spacing=1.1)
    pdf.set_font("serif", "B", 13)
    pdf.set_text_color(*INK)
    pdf.set_xy(x + 3, y + 6)
    pdf.cell(box_w - 6, 6, f"{_money(offer.total)} {offer.currency}", align="R")
    pdf.set_xy(MARGIN, y + 18)


#: Височината на подписния блок: черта, име и длъжност.
SIGNATURE_H = 11.0


def _draw_signature(pdf: _OfferPDF, company) -> None:
    """Подписът веднага след текста, не закован за долния ръб.

    Закованият подпис отваряше втора страница при оферта, която иначе се побира
    на една — читателят получаваше празен лист с едно име на него.
    """
    if pdf.get_y() + 4 + SIGNATURE_H > FOOTER_TOP:
        pdf.add_page()
    y = pdf.get_y() + 4
    # Позицията е изчислена: автоматичното прехвърляне само ще я развали.
    pdf.set_auto_page_break(auto=False)
    pdf.set_draw_color(*LINE)
    pdf.set_line_width(0.2)
    pdf.line(PAGE_W - MARGIN - 62, y, PAGE_W - MARGIN, y)
    pdf.set_font("serif", "B", 10.5)
    pdf.set_text_color(*INK)
    pdf.set_xy(PAGE_W - MARGIN - 62, y + 1.5)
    pdf.cell(62, 5, company.manager_name or company.name, align="R")
    pdf.set_font("sans", "", 7.6)
    pdf.set_text_color(*MUTED)
    pdf.set_xy(PAGE_W - MARGIN - 62, y + 6.5)
    pdf.cell(62, 4, "Управител", align="R")
    pdf.set_auto_page_break(auto=True, margin=PAGE_H - FOOTER_TOP + 4)


def _draw_blocks(pdf: _OfferPDF, blocks: list[Block], offer: Offer) -> None:
    """Текстът на офертата; `[[позиции]]` слага таблицата на своето място."""
    for block in blocks:
        if pdf.get_y() > FOOTER_TOP - 14:
            pdf.add_page()

        if block.kind == "items":
            _draw_items_table(pdf, offer)
            continue

        if block.kind == "h1":
            _draw_title(pdf, block.plain())
            continue

        if block.kind in ("h2", "h3"):
            size = 13.5 if block.kind == "h2" else 11.5
            pdf.ln(2)
            pdf.set_x(MARGIN)
            pdf.write_runs(block.runs, family="serif", size=size, color=INK, line_h=6.5)
            if block.kind == "h2":
                y = pdf.get_y() + 0.5
                pdf.set_draw_color(*LINE)
                pdf.set_line_width(0.25)
                pdf.line(MARGIN, y, PAGE_W - MARGIN, y)
                pdf.set_xy(MARGIN, y + 2.5)
            else:
                pdf.ln(1)
            continue

        if block.kind == "bullets":
            for item in block.items:
                if pdf.get_y() > FOOTER_TOP - 10:
                    pdf.add_page()
                y = pdf.get_y()
                pdf.set_fill_color(*GOLD)
                pdf.circle(x=MARGIN + 1.2, y=y + 2.1, radius=0.75, style="F")
                # Отстъпът се прави с лявото поле, за да се пренася текстът под
                # първата си буква, а не под точката.
                pdf.set_left_margin(MARGIN + 5)
                pdf.set_xy(MARGIN + 5, y)
                pdf.write_runs(item, family="sans", size=9.2, color=INK, line_h=5.2)
                pdf.set_left_margin(MARGIN)
                pdf.set_x(MARGIN)
                pdf.ln(0.6)
            pdf.ln(1.5)
            continue

        pdf.set_x(MARGIN)
        pdf.write_runs(block.runs, family="sans", size=9.4, color=INK, line_h=5.4)
        pdf.ln(1.2)


def render_offer_pdf(company, offer: Offer, counterparty) -> bytes:
    """Готовият PDF на офертата."""
    pdf = _OfferPDF(company, offer, counterparty)
    pdf.alias_nb_pages()
    pdf.add_page()

    _draw_meta(pdf, offer)
    _draw_recipient(pdf, counterparty)

    blocks = markup.parse(offer.body)
    if not any(b.kind == "h1" for b in blocks):
        _draw_title(pdf, offer.title)
    _draw_blocks(pdf, blocks, offer)

    # Позициите без маркер в текста застават след него — иначе таблицата изчезва
    # мълчаливо само защото в текста липсва [[позиции]].
    if offer.lines and not any(b.kind == "items" for b in blocks):
        pdf.ln(2)
        _draw_items_table(pdf, offer)

    _draw_signature(pdf, company)
    return bytes(pdf.output())
