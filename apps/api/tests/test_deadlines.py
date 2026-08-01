"""Тестове за календара със сроковете (НАП, НСИ, Търговски регистър)."""
import datetime as dt

from app.modules.deadlines.holidays import (
    holiday_calendar,
    is_working_day,
    next_working_day,
    orthodox_easter,
)
from tests.conftest import register_and_login

DL = "/api/v1/deadlines/upcoming"
ACC = "/api/v1/accounting"
VAT = "/api/v1/vat"


def _setup(client, email: str, *, vat_registered: bool = True):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post(
        "/api/v1/companies",
        headers=auth,
        json={"name": "Акме ЕООД", "eik": "203123456", "is_vat_registered": vat_registered},
    ).json()["id"]
    return {**auth, "X-Company-Id": company_id}


def _get(client, headers, reference_date: str, days_ahead: int = 60):
    r = client.get(
        DL, headers=headers, params={"reference_date": reference_date, "days_ahead": days_ahead}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _by_key(items: list[dict]) -> dict[str, dict]:
    return {item["key"]: item for item in items}


# ============================ православен Великден ============================
def test_orthodox_easter_known_years():
    """Известни дати на православния Великден (григориански календар)."""
    expected = {
        2020: dt.date(2020, 4, 19),
        2021: dt.date(2021, 5, 2),
        2022: dt.date(2022, 4, 24),
        2023: dt.date(2023, 4, 16),
        2024: dt.date(2024, 5, 5),
        2025: dt.date(2025, 4, 20),
        2026: dt.date(2026, 4, 12),
        2027: dt.date(2027, 5, 2),
        2028: dt.date(2028, 4, 16),
    }
    for year, date_ in expected.items():
        assert orthodox_easter(year) == date_, year
        assert orthodox_easter(year).weekday() == 6  # Великден винаги е неделя


def test_easter_holidays_are_non_working():
    """Разпети петък, Велика събота, Великден и Велики понеделник са неприсъствени."""
    calendar_2026 = holiday_calendar(2026)
    for date_ in (
        dt.date(2026, 4, 10),  # Разпети петък
        dt.date(2026, 4, 11),  # Велика събота
        dt.date(2026, 4, 12),  # Великден
        dt.date(2026, 4, 13),  # Велики понеделник
    ):
        assert date_ in calendar_2026
        assert not is_working_day(date_)
    # Великденските празници НЕ се пренасят — вторникът след тях е работен.
    assert is_working_day(dt.date(2026, 4, 14))


def test_fixed_holiday_shifted_from_weekend():
    """Официален празник в събота/неделя → следващият работен ден е неприсъствен."""
    calendar_2026 = holiday_calendar(2026)
    # 24 май 2026 е неделя → 25 май (понеделник) е почивен.
    assert dt.date(2026, 5, 24).weekday() == 6
    assert "Почивен ден" in calendar_2026[dt.date(2026, 5, 25)]
    # 6 септември 2026 е неделя → 7 септември е почивен.
    assert "Почивен ден" in calendar_2026[dt.date(2026, 9, 7)]
    # Коледа 2027: 25 (събота) и 26 (неделя) → 27 и 28 декември са почивни.
    calendar_2027 = holiday_calendar(2027)
    assert dt.date(2027, 12, 27) in calendar_2027
    assert dt.date(2027, 12, 28) in calendar_2027
    # 2016: Великден съвпада с 1 май → компенсацията се мести на 3 май (2 май е Велики понеделник).
    calendar_2016 = holiday_calendar(2016)
    assert orthodox_easter(2016) == dt.date(2016, 5, 1)
    assert dt.date(2016, 5, 3) in calendar_2016


def test_next_working_day_skips_weekend_and_holiday():
    assert next_working_day(dt.date(2026, 2, 14)) == dt.date(2026, 2, 16)  # събота → понеделник
    assert next_working_day(dt.date(2026, 5, 25)) == dt.date(2026, 5, 26)  # почивен → вторник
    assert next_working_day(dt.date(2026, 7, 14)) == dt.date(2026, 7, 14)  # работен ден


# ================================ ДДС срокове =================================
def test_vat_deadline_for_registered_company(client):
    h = _setup(client, "dl-vat@example.com", vat_registered=True)
    items = _by_key(_get(client, h, "2026-07-25"))
    vat = items["vat-return:2026-07"]
    assert vat["due_date"] == "2026-08-14"
    assert vat["original_due_date"] == "2026-08-14"
    assert vat["moved_for_holiday"] is False
    assert vat["period_label"] == "юли 2026"
    assert vat["category"] == "VAT"
    assert vat["authority"] == "НАП"
    assert vat["conditional"] is False
    assert vat["days_remaining"] == 20
    assert "дневник покупки" in vat["description"]
    # ДДС-свързаните условни срокове също присъстват
    assert items["intrastat:2026-07"]["conditional"] is True
    assert items["vies:2026-07"]["conditional"] is True
    assert "ВОД" in items["vies:2026-07"]["conditional_note"]


def test_no_vat_deadlines_for_unregistered_company(client):
    h = _setup(client, "dl-novat@example.com", vat_registered=False)
    items = _by_key(_get(client, h, "2026-07-25"))
    assert "vat-return:2026-07" not in items
    assert "vies:2026-07" not in items
    assert "intrastat:2026-07" not in items
    # осигурителните и корпоративните срокове обаче остават
    assert "payroll-declarations:2026-07" in items
    assert "cit-advance-monthly:2026-08" in items


def test_vies_not_conditional_when_ics_sales_exist(client):
    h = _setup(client, "dl-vies@example.com", vat_registered=True)
    client.post(f"{ACC}/chart/seed", headers=h)
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    codes = {c["code"]: c for c in client.post(f"{VAT}/codes/seed", headers=h).json()}
    r = client.post(
        f"{VAT}/entries",
        headers=h,
        json={
            "vat_code_id": codes["SICS"]["id"],
            "document_date": "2026-07-10",
            "document_number": "F-100",
            "counterparty_name": "EU Buyer GmbH",
            "counterparty_vat_number": "DE123456789",
            "tax_base": "5000.00",
        },
    )
    assert r.status_code == 201, r.text

    items = _by_key(_get(client, h, "2026-08-01", days_ahead=20))
    vies = items["vies:2026-07"]
    assert vies["conditional"] is False
    assert vies["conditional_note"] is None
    assert vies["due_date"] == "2026-08-14"
    # за месец без ВОД срокът остава условен
    items = _by_key(_get(client, h, "2026-09-01", days_ahead=20))
    assert items["vies:2026-08"]["conditional"] is True


# =========================== преместване при неработен ден ====================
def test_deadline_moved_when_due_on_saturday(client):
    """14 февруари 2026 е събота → ДДС срокът се мести на понеделник, 16 февруари."""
    h = _setup(client, "dl-sat@example.com")
    items = _by_key(_get(client, h, "2026-02-01", days_ahead=30))
    vat = items["vat-return:2026-01"]
    assert vat["original_due_date"] == "2026-02-14"
    assert vat["due_date"] == "2026-02-16"
    assert vat["moved_for_holiday"] is True
    assert vat["period_label"] == "януари 2026"


def test_deadline_moved_when_due_on_public_holiday(client):
    """25 май 2026 е почивен (пренасяне за 24 май, неделя) → обр. 1 и 6 падат на 26 май."""
    h = _setup(client, "dl-holiday@example.com")
    items = _by_key(_get(client, h, "2026-05-01", days_ahead=40))
    payroll = items["payroll-declarations:2026-04"]
    assert payroll["original_due_date"] == "2026-05-25"
    assert payroll["due_date"] == "2026-05-26"
    assert payroll["moved_for_holiday"] is True
    assert payroll["category"] == "PAYROLL"


# =============================== годишни срокове ==============================
def test_annual_deadlines_in_june_window(client):
    h = _setup(client, "dl-annual@example.com")
    items = _by_key(_get(client, h, "2026-06-01", days_ahead=45))
    cit = items["cit-annual-return:2025"]
    assert cit["due_date"] == "2026-06-30"
    assert cit["period_label"] == "2025 г."
    assert cit["category"] == "CORPORATE_TAX"
    assert cit["authority"] == "НАП"
    assert cit["conditional"] is False
    nsi = items["nsi-annual-report:2025"]
    assert nsi["due_date"] == "2026-06-30"
    assert nsi["authority"] == "НСИ"
    assert nsi["category"] == "STATISTICS"
    # ГФО е чак на 30 септември → извън този прозорец
    assert "afr-publication:2025" not in items


def test_annual_report_publication_and_chl73(client):
    h = _setup(client, "dl-annual2@example.com")
    items = _by_key(_get(client, h, "2026-09-01", days_ahead=40))
    afr = items["afr-publication:2025"]
    assert afr["due_date"] == "2026-09-30"
    assert afr["authority"] == "Търговски регистър"
    assert afr["category"] == "ANNUAL_REPORT"

    # Справките по чл. 73 — 28 февруари 2026 е събота → 2 март 2026
    items = _by_key(_get(client, h, "2026-02-01", days_ahead=40))
    chl73 = items["income-report-chl73:2025"]
    assert chl73["original_due_date"] == "2026-02-28"
    assert chl73["due_date"] == "2026-03-02"
    assert chl73["moved_for_holiday"] is True
    assert "SPR73_6.xml" in chl73["description"]


# ============================= тримесечни срокове =============================
def test_quarterly_advance_and_withholding_tax(client):
    h = _setup(client, "dl-quarter@example.com")
    items = _by_key(_get(client, h, "2026-07-01", days_ahead=40))
    advance = items["cit-advance-quarterly:2026-Q2"]
    assert advance["due_date"] == "2026-07-15"
    assert advance["period_label"] == "II тримесечие на 2026 г."
    withholding = items["withholding-tax:2026-Q2"]
    assert withholding["original_due_date"] == "2026-07-31"
    assert withholding["conditional"] is True

    # За III тримесечие авансова вноска не се дължи (октомврийският прозорец)
    items = _by_key(_get(client, h, "2026-10-01", days_ahead=40))
    assert "cit-advance-quarterly:2026-Q3" not in items
    assert "withholding-tax:2026-Q3" in items


def test_monthly_cit_advance_only_may_to_december(client):
    h = _setup(client, "dl-citmonthly@example.com")
    items = _by_key(_get(client, h, "2026-05-01", days_ahead=20))
    advance = items["cit-advance-monthly:2026-05"]
    assert advance["due_date"] == "2026-05-15"
    assert advance["conditional"] is True
    # Бележката сочи разпоредбата, а не сума: праговете в лева са предефинирани в
    # закона с приемането на еврото, а не преизчислени по курса.
    assert "чл. 83, ал. 2 ЗКПО" in advance["conditional_note"]
    # През януари–април месечна авансова вноска не се генерира
    items = _by_key(_get(client, h, "2026-03-01", days_ahead=40))
    assert not [k for k in items if k.startswith("cit-advance-monthly:2026-0")]


# ============================== общо поведение ================================
def test_sorted_by_due_date_and_days_remaining(client):
    h = _setup(client, "dl-sort@example.com")
    items = _get(client, h, "2026-07-25", days_ahead=90)
    dates = [item["due_date"] for item in items]
    assert dates == sorted(dates)
    for item in items:
        due = dt.date.fromisoformat(item["due_date"])
        assert item["days_remaining"] == (due - dt.date(2026, 7, 25)).days
        assert item["days_remaining"] >= 0


def test_days_ahead_limits_the_result(client):
    h = _setup(client, "dl-window@example.com")
    short = _get(client, h, "2026-07-25", days_ahead=10)
    long = _get(client, h, "2026-07-25", days_ahead=120)
    assert len(short) < len(long)
    assert {item["key"] for item in short} <= {item["key"] for item in long}
    assert all(item["days_remaining"] <= 10 for item in short)
    # нищо не изтича преди отправната дата
    assert all(item["due_date"] >= "2026-07-25" for item in long)


def test_days_ahead_validation(client):
    h = _setup(client, "dl-validate@example.com")
    assert client.get(DL, headers=h, params={"days_ahead": 401}).status_code == 422
    assert client.get(DL, headers=h, params={"days_ahead": 0}).status_code == 422
    # без reference_date работи (по подразбиране днес)
    assert client.get(DL, headers=h).status_code == 200


def test_keys_are_stable_between_calls(client):
    h = _setup(client, "dl-stable@example.com")
    first = {item["key"] for item in _get(client, h, "2026-07-25")}
    second = {item["key"] for item in _get(client, h, "2026-07-25")}
    assert first == second
    assert len(first) == len(_get(client, h, "2026-07-25"))  # без дублирани ключове


def test_requires_company_context(client):
    token = register_and_login(client, "dl-auth@example.com")
    r = client.get(DL, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400
    assert client.get(DL).status_code == 401  # без токен


# ============================ отметки „подадено“ ============================

FILINGS = "/api/v1/deadlines/filings"


def _first_key(client, headers) -> str:
    return _get(client, headers, "2026-07-01")[0]["key"]


def test_marking_a_deadline_filed_shows_in_the_list(client):
    headers = _setup(client, "filed-1@example.com")
    key = _first_key(client, headers)

    r = client.post(FILINGS, headers=headers, json={"key": key, "note": "подадено през портала"})
    assert r.status_code == 201, r.text

    marked = _by_key(_get(client, headers, "2026-07-01"))[key]
    assert marked["filed"] is True
    assert marked["filed_at"] is not None


def test_filed_deadlines_are_not_hidden_by_default(client):
    """Човек трябва да вижда какво вече е подал — и да може да отмени грешка."""
    headers = _setup(client, "filed-2@example.com")
    key = _first_key(client, headers)
    client.post(FILINGS, headers=headers, json={"key": key})

    assert key in _by_key(_get(client, headers, "2026-07-01"))


def test_include_filed_false_leaves_only_what_is_pending(client):
    """Мобилният клиент насрочва напомняния само за непубликуваното."""
    headers = _setup(client, "filed-3@example.com")
    key = _first_key(client, headers)
    client.post(FILINGS, headers=headers, json={"key": key})

    r = client.get(
        DL,
        headers=headers,
        params={"reference_date": "2026-07-01", "days_ahead": 60, "include_filed": False},
    )
    assert key not in _by_key(r.json())


def test_marking_twice_is_not_an_error(client):
    """Две натискания от два телефона дават един и същ резултат."""
    headers = _setup(client, "filed-4@example.com")
    key = _first_key(client, headers)

    assert client.post(FILINGS, headers=headers, json={"key": key}).status_code == 201
    r = client.post(FILINGS, headers=headers, json={"key": key, "note": "второ"})
    assert r.status_code == 201
    assert r.json()["note"] == "второ"

    assert len(client.get(FILINGS, headers=headers).json()) == 1


def test_unmarking_restores_the_deadline(client):
    headers = _setup(client, "filed-5@example.com")
    key = _first_key(client, headers)
    client.post(FILINGS, headers=headers, json={"key": key})

    r = client.delete(FILINGS, headers=headers, params={"key": key})
    assert r.status_code == 204

    assert _by_key(_get(client, headers, "2026-07-01"))[key]["filed"] is False


def test_unmarking_something_never_marked_is_not_an_error(client):
    headers = _setup(client, "filed-6@example.com")
    r = client.delete(FILINGS, headers=headers, params={"key": "vat-return:2020-01"})
    assert r.status_code == 204


def test_filings_do_not_leak_between_companies(client):
    """Отметката е на компанията, не на потребителя."""
    headers_a = _setup(client, "filed-7@example.com")
    key = _first_key(client, headers_a)
    client.post(FILINGS, headers=headers_a, json={"key": key})

    headers_b = _setup(client, "filed-8@example.com")
    assert _by_key(_get(client, headers_b, "2026-07-01"))[key]["filed"] is False
