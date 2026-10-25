"""Тестове на модул „Оферти": разметка, срок на валидност, сметка, регистър, PDF."""
import datetime as dt
from decimal import Decimal

from app.db import registry  # noqa: F401 — регистрира всички модели преди мапването
from app.modules.offers import brand, markup, models
from app.modules.offers.models import Offer
from app.modules.offers.schemas import OfferLineIn
from app.modules.offers.service import totals, valid_until
from tests.conftest import register_and_login

CP = "/api/v1/counterparties"
OFF = "/api/v1/offers"


def _setup(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post(
        "/api/v1/companies", headers=auth, json={"name": "Акме ЕООД"}
    ).json()["id"]
    h = {**auth, "X-Company-Id": company_id}
    customer = client.post(
        CP, headers=h, json={"type": "CUSTOMER", "name": "Клиент ООД", "eik": "111222333"}
    ).json()["id"]
    return h, customer


BODY = """# Внедряване на счетоводна система

Благодарим за интереса. Предлагаме **пълно внедряване** в три етапа.

## Обхват на услугата

* Анализ на текущите процеси
* Миграция на данните
* Обучение на екипа

## Позиции и цени

[[позиции]]

Плащането е на два транша."""


def _payload(customer, **over):
    data = {
        "counterparty_id": customer,
        "title": "Внедряване на счетоводна система",
        "issue_date": "2026-10-26",
        "validity_days": 30,
        "body": BODY,
        "vat_rate": "20.00",
        "lines": [
            {"description": "Анализ и проектиране", "unit": "ч", "quantity": "24",
             "unit_price": "85.00"},
            {"description": "Миграция на данни", "quantity": "1", "unit_price": "1800.00"},
        ],
    }
    data.update(over)
    return data


# ---------------------------------------------------------------- разметка


def test_markup_headings_and_levels():
    blocks = markup.parse("# Едно\n## Две\n### Три")
    assert [b.kind for b in blocks] == ["h1", "h2", "h3"]
    assert [b.plain() for b in blocks] == ["Едно", "Две", "Три"]


def test_markup_hash_without_space_is_text():
    """`#1` е номер, не заглавие — иначе всяка решетка в текста става заглавие."""
    blocks = markup.parse("#1 от списъка")
    assert [b.kind for b in blocks] == ["paragraph"]
    assert blocks[0].plain() == "#1 от списъка"


def test_markup_asterisk_makes_bullets_and_groups_them():
    blocks = markup.parse("* едно\n* две\n\nабзац")
    assert [b.kind for b in blocks] == ["bullets", "paragraph"]
    assert [[r.text for r in item] for item in blocks[0].items] == [["едно"], ["две"]]


def test_markup_bold_runs_inside_a_line():
    blocks = markup.parse("Предлагаме **пълно внедряване** в три етапа.")
    runs = blocks[0].runs
    assert [(r.text, r.bold) for r in runs] == [
        ("Предлагаме ", False),
        ("пълно внедряване", True),
        (" в три етапа.", False),
    ]


def test_markup_consecutive_lines_join_into_one_paragraph():
    blocks = markup.parse("първи ред\nвтори ред\n\nнов абзац")
    assert [b.plain() for b in blocks] == ["първи ред втори ред", "нов абзац"]


def test_markup_escape_keeps_the_character():
    blocks = markup.parse("\\* това не е булет")
    assert blocks[0].kind == "paragraph"
    assert blocks[0].plain() == "* това не е булет"


def test_markup_items_marker_is_its_own_block():
    blocks = markup.parse("текст\n\n[[позиции]]\n\nслед таблицата")
    assert [b.kind for b in blocks] == ["paragraph", "items", "paragraph"]
    assert markup.has_items_marker("[[позиции]]") is True
    assert markup.has_items_marker("само текст") is False


# ---------------------------------------------------------------- срок и сметка


def test_valid_until_adds_calendar_days():
    assert valid_until(dt.date(2026, 10, 26), 30) == dt.date(2026, 11, 25)
    # През края на месеца и на годината — календарни дни, не работни.
    assert valid_until(dt.date(2026, 12, 20), 30) == dt.date(2027, 1, 19)
    assert valid_until(dt.date(2028, 2, 28), 1) == dt.date(2028, 2, 29)


def test_totals_round_each_line_then_sum():
    """Основата е сумата от закръглените редове, за да се сбира таблицата.

    0,335 × 3 реда: сумирането преди закръгляне дава 1,01, а написаните в
    таблицата редове сборно — 1,02. Клиентът сбира второто.
    """
    lines = [
        OfferLineIn(description="ред", quantity=Decimal("1"), unit_price=Decimal("0.335"))
        for _ in range(3)
    ]
    subtotal, vat, total, nets = totals(lines, Decimal("20.00"))
    assert nets == [Decimal("0.34")] * 3
    assert subtotal == Decimal("1.02")
    assert vat == Decimal("0.20")
    assert total == Decimal("1.22")


def test_totals_with_zero_vat_rate():
    lines = [OfferLineIn(description="ред", quantity=Decimal("2"), unit_price=Decimal("50"))]
    subtotal, vat, total, _ = totals(lines, Decimal("0"))
    assert (subtotal, vat, total) == (Decimal("100.00"), Decimal("0.00"), Decimal("100.00"))


def test_expiry_boundary_is_the_last_valid_day():
    offer = Offer(valid_until=dt.date(2026, 11, 25))
    assert offer.is_expired(dt.date(2026, 11, 25)) is False
    assert offer.is_expired(dt.date(2026, 11, 26)) is True


def test_expiry_uses_the_sofia_day_not_utc(monkeypatch):
    """В 01:00 софийско време UTC още е вчера — офертата вече е изтекла.

    Сървърът върви в UTC. Ако денят се вземе оттам, оферта с валидност до 25-и
    се води валидна до 02:00 на 26-и — два часа, в които регистърът лъже.
    """
    moment = dt.datetime(2026, 11, 25, 23, 0, tzinfo=dt.UTC)  # 01:00 на 26.11 в София

    class _Clock:
        date = dt.date
        timedelta = dt.timedelta

        class datetime:  # noqa: N801 — замества dt.datetime само в този модул
            @staticmethod
            def now(tz=None):
                return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)

    monkeypatch.setattr(models, "dt", _Clock)
    assert Offer(valid_until=dt.date(2026, 11, 25)).is_expired() is True
    assert Offer(valid_until=dt.date(2026, 11, 26)).is_expired() is False


# ---------------------------------------------------------------- API


def test_create_offer_numbers_computes_and_sums(client):
    h, customer = _setup(client, "off1@example.com")
    r = client.post(OFF, headers=h, json=_payload(customer))
    assert r.status_code == 201, r.text
    offer = r.json()

    assert offer["number"] == 1 and offer["full_number"] == "ОФ-0001"
    assert offer["valid_until"] == "2026-11-25"
    assert offer["currency"] == "EUR"
    # 24 × 85,00 = 2040,00 + 1800,00 = 3840,00; ДДС 20% = 768,00
    assert Decimal(offer["subtotal"]) == Decimal("3840.00")
    assert Decimal(offer["vat_amount"]) == Decimal("768.00")
    assert Decimal(offer["total"]) == Decimal("4608.00")
    assert [line["line_no"] for line in offer["lines"]] == [1, 2]
    assert offer["counterparty_name"] == "Клиент ООД"
    assert offer["status"] == "DRAFT"

    second = client.post(OFF, headers=h, json=_payload(customer)).json()
    assert second["full_number"] == "ОФ-0002"


def test_offer_for_a_supplier_is_refused(client):
    h, _ = _setup(client, "off2@example.com")
    supplier = client.post(
        CP, headers=h, json={"type": "SUPPLIER", "name": "Доставчик ООД"}
    ).json()["id"]
    r = client.post(OFF, headers=h, json=_payload(supplier))
    assert r.status_code == 422
    assert "клиент" in r.json()["detail"]


def test_register_filters_by_client(client):
    h, first = _setup(client, "off3@example.com")
    second = client.post(
        CP, headers=h, json={"type": "CUSTOMER", "name": "Втори клиент ЕООД"}
    ).json()["id"]
    client.post(OFF, headers=h, json=_payload(first))
    client.post(OFF, headers=h, json=_payload(second, title="Друга оферта"))

    assert len(client.get(OFF, headers=h).json()) == 2
    only_second = client.get(f"{OFF}?counterparty_id={second}", headers=h).json()
    assert [o["counterparty_id"] for o in only_second] == [second]

    # Регистърът е най-новата оферта първа.
    assert [o["number"] for o in client.get(OFF, headers=h).json()] == [2, 1]


def test_copy_returns_text_without_client_and_dates(client):
    h, customer = _setup(client, "off4@example.com")
    created = client.post(OFF, headers=h, json=_payload(customer)).json()

    r = client.get(f"{OFF}/{created['id']}/copy", headers=h)
    assert r.status_code == 200, r.text
    template = r.json()

    assert template["body"] == BODY
    assert template["title"] == "Внедряване на счетоводна система"
    assert len(template["lines"]) == 2
    # Точно това, което потребителят поиска да е празно.
    assert "counterparty_id" not in template
    assert "issue_date" not in template
    assert "validity_days" not in template
    assert template["source_number"] == "ОФ-0001"


def test_update_recomputes_valid_until_and_totals(client):
    h, customer = _setup(client, "off5@example.com")
    created = client.post(OFF, headers=h, json=_payload(customer)).json()

    r = client.patch(
        f"{OFF}/{created['id']}",
        headers=h,
        json={"validity_days": 10, "lines": [
            {"description": "Само едно", "quantity": "1", "unit_price": "100.00"}
        ]},
    )
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["valid_until"] == "2026-11-05"
    assert Decimal(updated["subtotal"]) == Decimal("100.00")
    assert Decimal(updated["total"]) == Decimal("120.00")
    assert len(updated["lines"]) == 1

    # Смяна само на ставката мести тотала, без да се подават редове.
    rated = client.patch(f"{OFF}/{created['id']}", headers=h, json={"vat_rate": "0"}).json()
    assert Decimal(rated["vat_amount"]) == Decimal("0.00")
    assert Decimal(rated["total"]) == Decimal("100.00")


def test_expired_offer_is_marked_in_the_register(client):
    h, customer = _setup(client, "off6@example.com")
    long_ago = (dt.date.today() - dt.timedelta(days=40)).isoformat()
    offer = client.post(
        OFF, headers=h, json=_payload(customer, issue_date=long_ago, validity_days=5)
    ).json()
    assert offer["is_expired"] is True

    fresh = client.post(
        OFF, headers=h, json=_payload(customer, issue_date=dt.date.today().isoformat())
    ).json()
    assert fresh["is_expired"] is False


def test_preview_before_saving_returns_blocks_and_sums(client):
    h, _ = _setup(client, "off7@example.com")
    r = client.post(
        f"{OFF}/preview",
        headers=h,
        json={
            "body": "## Обхват\n\n* едно\n\n[[позиции]]",
            "issue_date": "2026-10-26",
            "validity_days": 14,
            "vat_rate": "20.00",
            "lines": [{"description": "Услуга", "quantity": "2", "unit_price": "100.00"}],
        },
    )
    assert r.status_code == 200, r.text
    preview = r.json()
    assert [b["kind"] for b in preview["blocks"]] == ["h2", "bullets", "items"]
    assert preview["has_items_marker"] is True
    assert preview["valid_until"] == "2026-11-09"
    assert Decimal(preview["total"]) == Decimal("240.00")
    assert preview["lines"][0]["line_net"] == "200.00"
    # Нищо не е записано — прегледът не създава оферта.
    assert client.get(OFF, headers=h).json() == []


def test_pdf_is_generated(client):
    h, customer = _setup(client, "off8@example.com")
    created = client.post(OFF, headers=h, json=_payload(customer)).json()
    r = client.get(f"{OFF}/{created['id']}/pdf", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    # Документът не е празен скелет: шапка, текст, таблица и подпис.
    assert len(r.content) > 8000


def test_pdf_without_items_marker_still_shows_the_table(client):
    """Таблицата не изчезва само защото в текста липсва [[позиции]]."""
    h, customer = _setup(client, "off9@example.com")
    created = client.post(
        OFF, headers=h, json=_payload(customer, body="## Обхват\n\n* нещо")
    ).json()
    with_marker = client.post(OFF, headers=h, json=_payload(customer)).json()

    plain = client.get(f"{OFF}/{created['id']}/pdf", headers=h).content
    marked = client.get(f"{OFF}/{with_marker['id']}/pdf", headers=h).content
    # Двата документа носят таблицата, затова са съизмерими по размер.
    assert abs(len(plain) - len(marked)) < len(marked) * 0.3


def test_brand_logo_only_for_its_own_company(client):
    """Логото на ХЕПСУ не застава върху оферта на чуждо дружество.

    Системата е многофирмена: кантора води офертите на клиентските дружества.
    Чужд знак върху чужд документ е грешка, която никой няма да хване в PDF-а.
    """
    token = register_and_login(client, "off13@example.com")
    auth = {"Authorization": f"Bearer {token}"}

    own = client.post("/api/v1/companies", headers=auth,
                      json={"name": "ХЕПСУ КОНСУЛТИНГ ЕООД", "eik": brand.BRAND_EIK}).json()["id"]
    other = client.post("/api/v1/companies", headers=auth,
                        json={"name": "Чуждо ЕООД", "eik": "111222333"}).json()["id"]

    own_preview = client.post(f"{OFF}/preview", headers={**auth, "X-Company-Id": own}, json={}).json()
    other_preview = client.post(f"{OFF}/preview", headers={**auth, "X-Company-Id": other}, json={}).json()
    assert own_preview["has_brand_logo"] is True
    assert other_preview["has_brand_logo"] is False
    assert other_preview["company_name"] == "Чуждо ЕООД"

    # И в PDF-а: своят документ носи вграден образ, чуждият — не.
    def _pdf(company_id: str) -> bytes:
        h = {**auth, "X-Company-Id": company_id}
        customer = client.post(CP, headers=h, json={"type": "CUSTOMER", "name": "Клиент"}).json()["id"]
        offer = client.post(OFF, headers=h, json=_payload(customer, body="текст")).json()
        return client.get(f"{OFF}/{offer['id']}/pdf", headers=h).content

    # `/ImageB` стои в ProcSet на всеки PDF с шрифт — затова се търси самият обект.
    assert b"/Subtype /Image" in _pdf(own)
    assert b"/Subtype /Image" not in _pdf(other)


def test_other_company_cannot_reach_the_offer(client):
    h_one, customer = _setup(client, "off10@example.com")
    created = client.post(OFF, headers=h_one, json=_payload(customer)).json()

    h_two, _ = _setup(client, "off11@example.com")
    assert client.get(f"{OFF}/{created['id']}", headers=h_two).status_code == 404
    assert client.get(OFF, headers=h_two).json() == []


def test_delete_removes_the_offer(client):
    h, customer = _setup(client, "off12@example.com")
    created = client.post(OFF, headers=h, json=_payload(customer)).json()
    assert client.delete(f"{OFF}/{created['id']}", headers=h).status_code == 204
    assert client.get(f"{OFF}/{created['id']}", headers=h).status_code == 404
