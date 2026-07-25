"""Тестове на валидацията преди подаване (XSD, структура, дължини, кодировка).

Целта е валидаторът да **лови** грешки, а не само да пуска верните файлове —
затова всеки положителен случай има огледален отрицателен.
"""
import datetime as dt
from decimal import Decimal

import pytest

from app.modules.income_report.generator import build_xml, validate_xml
from app.modules.income_report.schemas import (
    Chl736IncomeLine,
    Chl736Payer,
    Chl736Person,
    Chl736Report,
)
from app.tax_engine.export.saft import SaftBgV1Provider
from app.tax_engine.export.validation import (
    ERROR,
    FieldSpec,
    ValidationReport,
    XsdSchema,
    check_encoding,
    validate_delimited,
)

D = Decimal


# ==================================================================== доклад
def test_report_is_ok_without_errors_but_warnings_do_not_block() -> None:
    report = ValidationReport(target="проба")
    report.add("WARNING", "нещо дребно")
    assert report.ok
    assert report.summary() == "Без грешки, 1 предупреждения"

    report.add(ERROR, "нещо сериозно")
    assert not report.ok


# ==================================================================== полета
def test_field_longer_than_spec_is_an_error() -> None:
    spec = [FieldSpec("Наименование", 5)]
    issues = validate_delimited("шестица", spec, source="X.TXT")
    assert len(issues) == 1
    assert "максимум 5" in issues[0].message
    assert issues[0].line == 1


def test_field_within_spec_passes() -> None:
    assert validate_delimited("кратко", [FieldSpec("Име", 20)], source="X.TXT") == []


def test_missing_required_field_is_an_error() -> None:
    spec = [FieldSpec("ЕИК", 15, required=True), FieldSpec("Име", 20)]
    issues = validate_delimited(";Акме", spec, source="X.TXT")
    assert any("Задължителното поле" in i.message for i in issues)


def test_wrong_number_of_columns_is_an_error() -> None:
    spec = [FieldSpec("A", 5), FieldSpec("B", 5)]
    issues = validate_delimited("едно;две;три", spec, source="X.TXT")
    assert len(issues) == 1
    assert "3 полета вместо 2" in issues[0].message


def test_non_numeric_value_in_numeric_field_is_an_error() -> None:
    spec = [FieldSpec("Сума", 15, numeric=True)]
    issues = validate_delimited("не-число", spec, source="X.TXT")
    assert any("не е число" in i.message for i in issues)


def test_numeric_field_is_not_checked_for_length() -> None:
    # Числата се форматират от кода, не се въвеждат — дължината им не е риск.
    assert validate_delimited("123456789012345678.00", [FieldSpec("Сума", 5, numeric=True)],
                              source="X.TXT") == []


# ==================================================================== кодировка
def test_cyrillic_passes_cp1251() -> None:
    assert check_encoding("Акме ЕООД, гр. София", "cp1251", source="X.TXT") == []


def test_em_dash_and_euro_sign_are_valid_cp1251() -> None:
    """CP1251 носи дългото тире и знака за евро — не бива да се вдига фалшива тревога."""
    assert check_encoding("Акме — 100 €", "cp1251", source="X.TXT") == []


def test_character_outside_cp1251_is_caught() -> None:
    # Румънското „ș“ е реалистичен случай: контрагент от Румъния в дневника.
    issues = check_encoding("Firma Popescu ș Fii", "cp1251", source="X.TXT")
    assert len(issues) == 1
    assert "CP1251" in issues[0].message
    assert issues[0].line == 1


def test_emoji_in_counterparty_name_is_caught() -> None:
    issues = check_encoding("Фирма 🙂", "cp1251", source="PRODAGBI.TXT")
    assert issues and issues[0].source == "PRODAGBI.TXT"


# ==================================================================== XSD
def test_missing_schema_warns_and_says_where_to_put_it() -> None:
    schema = XsdSchema("няма-такъв.xsd", "Несъществуваща схема")
    assert not schema.available
    issues = schema.validate(b"<a/>")
    assert len(issues) == 1
    assert issues[0].level == "WARNING"
    assert "няма-такъв.xsd" in issues[0].message


def test_chl73_generated_file_validates_against_the_real_nra_schema() -> None:
    """Най-важният тест тук: генерираното наистина отговаря на схемата на НАП."""
    report = validate_xml(build_xml(_chl73_report()))
    assert report.schema_present, "SPR73_6.xsd трябва да е в репото"
    assert report.ok, [i.as_text() for i in report.errors]


@pytest.mark.parametrize(
    "xml, expected",
    [
        ('<dec736><part1><eik>203123456</eik><name>Акме</name></part1></dec736>', "year"),
        ('<dec736><year>2025</year><part1><eik>АБ</eik><name>Акме</name></part1></dec736>', "eik"),
    ],
)
def test_invalid_chl73_documents_are_rejected(xml: str, expected: str) -> None:
    doc = f'<?xml version="1.0" encoding="WINDOWS-1251"?>\n{xml}'
    report = validate_xml(doc.encode("windows-1251"))
    assert not report.ok
    assert any(expected in (i.path or "") + i.message for i in report.errors)


def test_malformed_xml_is_reported_as_such() -> None:
    report = validate_xml(b'<?xml version="1.0" encoding="WINDOWS-1251"?>\n<dec736>')
    assert not report.ok
    assert "не е валиден XML" in report.errors[0].message


def _chl73_report() -> Chl736Report:
    return Chl736Report(
        year=2025,
        payer=Chl736Payer(eik="203123456", name="Акме ЕООД"),
        persons=[
            Chl736Person(
                correctioncode=0, firstname="Иван", thirdname="Петров", identtype=0,
                ident="7501011234", ismainemployer=1,
                income_lines=[
                    Chl736IncomeLine(
                        incomecode="101", employereik="203123456", employername="Акме ЕООД",
                        income=D("24000.00"), advancetax=D("2400.00"), healthinsbg=D("3120.00"),
                    )
                ],
                sumtaxdeducted=D("2400.00"),
            )
        ],
    )


# ==================================================================== SAF-T структура
_NS = "urn:StandardAuditFile-Taxation-Financial:BG"


def _saft(total_debit="100.00", total_credit="100.00", entries="1",
          line_amount="100.00", account="601", chart=("601", "401")) -> bytes:
    accounts = "".join(
        f"<Account><AccountID>{c}</AccountID><AccountDescription>Сметка {c}</AccountDescription>"
        f"<AccountType>Expense</AccountType></Account>" for c in chart
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<AuditFile xmlns="{_NS}">'
        f"<Header><Company><RegistrationNumber>203123456</RegistrationNumber><Name>Акме</Name>"
        f"<TaxRegistration><TaxRegistrationNumber>BG203123456</TaxRegistrationNumber></TaxRegistration>"
        f"</Company><DefaultCurrencyCode>EUR</DefaultCurrencyCode>"
        f"<SelectionCriteria><SelectionStartDate>2026-01-01</SelectionStartDate>"
        f"<SelectionEndDate>2026-01-31</SelectionEndDate></SelectionCriteria></Header>"
        f"<MasterFiles><GeneralLedgerAccounts>{accounts}</GeneralLedgerAccounts></MasterFiles>"
        f"<GeneralLedgerEntries><NumberOfEntries>{entries}</NumberOfEntries>"
        f"<TotalDebit>{total_debit}</TotalDebit><TotalCredit>{total_credit}</TotalCredit>"
        f"<Journal><JournalID>GENERAL</JournalID>"
        f"<Transaction><TransactionID>1</TransactionID>"
        f"<DebitLine><AccountID>{account}</AccountID>"
        f"<Amount><Amount>{line_amount}</Amount></Amount></DebitLine>"
        f"<CreditLine><AccountID>401</AccountID>"
        f"<Amount><Amount>100.00</Amount></Amount></CreditLine>"
        f"</Transaction></Journal></GeneralLedgerEntries></AuditFile>"
    ).encode()


def test_saft_valid_structure_passes() -> None:
    report = SaftBgV1Provider().validate(_saft())
    assert report.ok, [i.as_text() for i in report.errors]


def test_saft_unbalanced_journal_is_rejected() -> None:
    report = SaftBgV1Provider().validate(_saft(total_debit="150.00", line_amount="150.00"))
    assert not report.ok
    assert any("не балансира" in i.message for i in report.errors)


def test_saft_control_total_mismatch_is_caught() -> None:
    """Обявената сума се разминава с реално записаните редове."""
    report = SaftBgV1Provider().validate(_saft(total_debit="100.00", line_amount="70.00",
                                               total_credit="100.00"))
    assert not report.ok
    assert any("не съвпада със сбора на редовете" in i.message for i in report.errors)


def test_saft_entry_count_mismatch_is_caught() -> None:
    report = SaftBgV1Provider().validate(_saft(entries="7"))
    assert not report.ok
    assert any("брой операции" in i.message for i in report.errors)


def test_saft_account_missing_from_chart_is_caught() -> None:
    report = SaftBgV1Provider().validate(_saft(account="999", chart=("601", "401")))
    assert not report.ok
    assert any("999" in i.message and "липсва в сметкоплана" in i.message
               for i in report.errors)


def test_saft_missing_header_field_is_caught() -> None:
    xml = _saft().replace("<Name>Акме</Name>".encode(), b"")
    report = SaftBgV1Provider().validate(xml)
    assert not report.ok
    assert any("наименование" in i.message for i in report.errors)


def test_saft_reports_missing_schema_without_failing() -> None:
    """Липсващият официален XSD е предупреждение, не грешка — структурата пак се проверява."""
    report = SaftBgV1Provider().validate(_saft())
    assert not report.schema_present
    assert any("не е инсталирана" in i.message for i in report.warnings)
    assert report.ok


def test_saft_malformed_xml_is_reported() -> None:
    report = SaftBgV1Provider().validate(b"<AuditFile>")
    assert not report.ok
    assert any("не е валиден XML" in i.message for i in report.errors)


def test_saft_export_and_validate_agree(client) -> None:
    """Реално генериран файл от базата минава собствената си валидация."""
    from tests.conftest import register_and_login

    token = register_and_login(client, "saftval@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    cid = client.post("/api/v1/companies", headers=auth,
                      json={"name": "Акме ЕООД", "eik": "203123456"}).json()["id"]
    h = {**auth, "X-Company-Id": cid}
    client.post("/api/v1/accounting/chart/seed", headers=h)

    r = client.get("/api/v1/submissions/saft/validate",
                   headers=h, params={"date_from": "2026-01-01", "date_to": "2026-01-31"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"], body["errors"]
    assert body["schema_present"] is False        # официалният XSD още не е доставен
    assert any("не е инсталирана" in w["message"] for w in body["warnings"])


def test_saft_validate_endpoint_reports_dates(client) -> None:
    from tests.conftest import register_and_login

    token = register_and_login(client, "saftval2@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    cid = client.post("/api/v1/companies", headers=auth, json={"name": "Без ЕИК ООД"}).json()["id"]
    h = {**auth, "X-Company-Id": cid}
    client.post("/api/v1/accounting/chart/seed", headers=h)

    r = client.get("/api/v1/submissions/saft/validate",
                   headers=h, params={"date_from": "2026-01-01", "date_to": "2026-01-31"})
    body = r.json()
    # Липсващият ЕИК е блокиращ реквизит за SAF-T.
    assert not body["ok"]
    assert any("ЕИК" in e["message"] for e in body["errors"])
    assert dt.date.today().year >= 2026
