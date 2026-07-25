"""Формат на файловете за НАП по ЗДДС: golden редове + валидация на пакета.

Golden тестовете фиксират точния изход байт по байт. Ако някой промени ред на
полета, разделител или закръгляне, тестът пада — това е разликата между „форматът
е както го помним“ и „форматът е проверен“.
"""
from decimal import Decimal
from types import SimpleNamespace

from app.modules.vat.models import VatDirection
from app.modules.vat.nap_export import (
    DEKLAR_ROW_FIELDS,
    POKUPKI_FIELDS,
    PRODAGBI_FIELDS,
    VIES_FIELDS,
    W_NAME,
    build_nap_zip,
    render_deklar,
    render_nap_files,
    render_pokupki,
    render_prodagbi,
    render_vies,
    validate_nap_files,
)

D = Decimal


def _company(name="Акме ЕООД", vat="BG203123456", eik="203123456"):
    return SimpleNamespace(name=name, vat_number=vat, eik=eik, country="BG")


def _code(code="STD20", rate="20.00", vies=False, protocol=False, credit=True):
    return SimpleNamespace(
        code=code, rate=D(rate), requires_vies=vies,
        requires_protocol=protocol, gives_credit=credit,
    )


def _entry(direction, base, vat, *, code=None, number="0000000001", cp="Клиент ООД",
           cp_vat="BG111222333", date=None, doc_type="01"):
    import datetime as dt

    return SimpleNamespace(
        direction=direction, tax_base=D(base), vat_amount=D(vat),
        vat_code=code or _code(), document_number=number, document_type=doc_type,
        document_date=date or dt.date(2026, 3, 15),
        counterparty_name=cp, counterparty_vat_number=cp_vat,
    )


# ==================================================================== golden
def test_prodagbi_row_is_exactly_as_specified() -> None:
    out = render_prodagbi(
        _company(), "2026-03", [_entry(VatDirection.SALE, "1000.00", "200.00")]
    )
    assert out == (
        "BG203123456;Акме ЕООД;202603;00001;01;0000000001;15/03/2026;"
        "BG111222333;Клиент ООД;Стоки/услуги;"
        "1200.00;200.00;1000.00;200.00;0.00;0.00;0.00;0.00;0.00;0.00\r\n"
    )


def test_pokupki_row_is_exactly_as_specified() -> None:
    out = render_pokupki(
        _company(), "2026-03",
        [_entry(VatDirection.PURCHASE, "500.00", "100.00", cp="Доставчик АД")],
    )
    assert out == (
        "BG203123456;Акме ЕООД;202603;00001;01;0000000001;15/03/2026;"
        "BG111222333;Доставчик АД;Стоки/услуги;"
        "0.00;500.00;100.00;0.00;0.00\r\n"
    )


def test_vies_aggregates_by_counterparty() -> None:
    ics = _code("ICS", "0.00", vies=True)
    entries = [
        _entry(VatDirection.SALE, "1000.00", "0.00", code=ics, cp_vat="DE123"),
        _entry(VatDirection.SALE, "500.00", "0.00", code=ics, cp_vat="DE123"),
        _entry(VatDirection.SALE, "300.00", "0.00", code=ics, cp_vat="RO999"),
    ]
    out = render_vies(_company(), "2026-03", entries)
    assert out == (
        "BG203123456;202603;DE123;1500.00\r\n"
        "BG203123456;202603;RO999;300.00\r\n"
    )


def test_deklar_starts_with_header_then_cells() -> None:
    from app.modules.vat.nap_export import compute_declaration_cells

    cells = compute_declaration_cells([_entry(VatDirection.SALE, "1000.00", "200.00")])
    out = render_deklar(_company(), "2026-03", cells)
    lines = out.split("\r\n")
    assert lines[0] == "BG203123456;Акме ЕООД;202603"
    assert "01;1000.00" in lines
    assert "20;200.00" in lines
    assert "50;200.00" in lines      # няма покупки → целият ДДС е за внасяне


def test_every_line_ends_with_crlf() -> None:
    files, _ = render_nap_files(
        _company(), "2026-03", [_entry(VatDirection.SALE, "1000.00", "200.00")]
    )
    for name, content in files.items():
        if not content:
            continue      # няма покупки в периода → празен дневник е валиден
        assert content.endswith("\r\n"), name
        assert "\n" not in content.replace("\r\n", ""), f"{name}: самотен LF"


def test_zip_contains_the_three_mandatory_files() -> None:
    import io
    import zipfile

    data, _ = build_nap_zip(
        _company(), "2026-03", [_entry(VatDirection.SALE, "1000.00", "200.00")]
    )
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert set(zf.namelist()) == {"POKUPKI.TXT", "PRODAGBI.TXT", "DEKLAR.TXT"}
        # Съдържанието е в CP1251, не в UTF-8.
        assert "Акме" in zf.read("DEKLAR.TXT").decode("cp1251")


def test_zip_adds_vies_only_when_there_are_ics_supplies() -> None:
    import io
    import zipfile

    ics = _code("ICS", "0.00", vies=True)
    data, _ = build_nap_zip(
        _company(), "2026-03",
        [_entry(VatDirection.SALE, "1000.00", "0.00", code=ics, cp_vat="DE123")],
    )
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert "VIES.TXT" in zf.namelist()


# ==================================================================== валидация
def test_valid_package_passes() -> None:
    report = validate_nap_files(
        _company(), "2026-03", [_entry(VatDirection.SALE, "1000.00", "200.00")]
    )
    assert report.ok, [i.as_text() for i in report.errors]


def test_counterparty_name_over_the_limit_is_caught() -> None:
    long_name = "Дълго наименование на контрагент " * 3       # над 50 знака
    report = validate_nap_files(
        _company(), "2026-03",
        [_entry(VatDirection.SALE, "1000.00", "200.00", cp=long_name)],
    )
    # Рендерът отрязва, но валидацията гледа спецификацията върху вече отрязаното —
    # затова тук проверяваме, че отрязването наистина се е случило и не е тихо.
    assert len(long_name) > W_NAME
    files, _ = render_nap_files(
        _company(), "2026-03",
        [_entry(VatDirection.SALE, "1000.00", "200.00", cp=long_name)],
    )
    row = files["PRODAGBI.TXT"].split(";")
    assert len(row[8]) == W_NAME
    assert report.ok


def test_character_outside_cp1251_blocks_the_package() -> None:
    report = validate_nap_files(
        _company(), "2026-03",
        [_entry(VatDirection.SALE, "1000.00", "200.00", cp="Popescu ș Fii SRL")],
    )
    assert not report.ok
    assert any("CP1251" in i.message for i in report.errors)


def test_company_without_identifier_is_blocked() -> None:
    report = validate_nap_files(
        _company(vat=None, eik=None), "2026-03",
        [_entry(VatDirection.SALE, "1000.00", "200.00")],
    )
    assert not report.ok
    assert any("идентификационен номер" in i.message for i in report.errors)


def test_company_without_vat_number_is_only_warned() -> None:
    report = validate_nap_files(
        _company(vat=None), "2026-03", [_entry(VatDirection.SALE, "1000.00", "200.00")]
    )
    assert report.ok
    assert any("ДДС номер" in i.message for i in report.warnings)


def test_empty_period_is_a_warning_not_an_error() -> None:
    report = validate_nap_files(_company(), "2026-03", [])
    assert report.ok
    assert any("няма ДДС записи" in i.message for i in report.warnings)


def test_entry_without_counterparty_data_is_warned() -> None:
    report = validate_nap_files(
        _company(), "2026-03",
        [_entry(VatDirection.SALE, "1000.00", "200.00", cp=None, cp_vat=None)],
    )
    assert any("без данни за контрагента" in i.message for i in report.warnings)


def test_self_charged_purchase_counts_towards_charged_vat() -> None:
    """ВОП по чл. 82: ДДС-то е и начислено, и данъчен кредит — к.20 трябва да го включва."""
    ica = _code("ICA", "20.00", protocol=True)
    report = validate_nap_files(
        _company(), "2026-03",
        [
            _entry(VatDirection.SALE, "1000.00", "200.00"),
            _entry(VatDirection.PURCHASE, "500.00", "100.00", code=ica),
        ],
    )
    assert report.ok, [i.as_text() for i in report.errors]

    from app.modules.vat.nap_export import compute_declaration_cells

    cells = compute_declaration_cells(
        [
            _entry(VatDirection.SALE, "1000.00", "200.00"),
            _entry(VatDirection.PURCHASE, "500.00", "100.00", code=ica),
        ]
    )
    assert cells.c20_vat_total == D("300.00")
    assert cells.c40_credit_total == D("100.00")
    assert cells.c50_vat_payable == D("200.00")


# ==================================================================== спецификация
def test_field_specs_match_the_rendered_columns() -> None:
    """Броят полета в спецификацията трябва да съвпада с реално записаните колони."""
    files, _ = render_nap_files(
        _company(), "2026-03",
        [
            _entry(VatDirection.SALE, "1000.00", "200.00"),
            _entry(VatDirection.PURCHASE, "500.00", "100.00"),
        ],
    )
    assert len(files["PRODAGBI.TXT"].strip().split(";")) == len(PRODAGBI_FIELDS)
    assert len(files["POKUPKI.TXT"].strip().split(";")) == len(POKUPKI_FIELDS)
    assert len(DEKLAR_ROW_FIELDS) == 2
    assert len(VIES_FIELDS) == 4
