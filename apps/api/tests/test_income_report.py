"""Тестове за Справката по чл. 73, ал. 6 от ЗДДФЛ (SPR73_6.xml)."""
import xml.etree.ElementTree as ET

from tests.conftest import register_and_login

IR = "/api/v1/income-reports/chl73-6/xml"


def _setup(client, email: str, eik="203123456"):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    cid = client.post("/api/v1/companies", headers=auth, json={"name": "Акме ЕООД", "eik": eik}).json()["id"]
    return {**auth, "X-Company-Id": cid}


def _person(ident="7501011234", code=0, main=1):
    return {
        "correctioncode": code,
        "firstname": "Иван",
        "thirdname": "Петров",
        "identtype": 0,
        "ident": ident,
        "ismainemployer": main,
        "income_lines": [
            {"incomecode": "101", "employereik": "203123456", "employername": "Акме ЕООД",
             "income": "24000.00", "advancetax": "2400.00", "healthinsbg": "3120.00"}
        ],
        "sumtaxdeducted": "2400.00",
    }


def test_generate_chl73_6_xml(client):
    h = _setup(client, "ir1@example.com")
    payload = {"year": 2025, "persons": [_person()]}
    r = client.post(IR, headers=h, json=payload)
    assert r.status_code == 200, r.text
    assert "windows-1251" in r.headers["content-type"]
    assert r.headers["content-disposition"].endswith('filename="SPR73_6.xml"')
    assert r.content[:5] == b"<?xml"
    assert b"WINDOWS-1251" in r.content[:60]

    # декодира се като WINDOWS-1251 и структурата съответства на XSD
    text = r.content.decode("windows-1251")
    root = ET.fromstring(text)
    assert root.tag == "dec736"
    assert root.find("year").text == "2025"
    assert root.find("part1/eik").text == "203123456"       # платецът е взет от компанията
    assert root.find("part1/name").text == "Акме ЕООД"
    row = root.find("part2/rowsenum")
    assert row.find("correctioncode").text == "0"
    assert row.find("ident").text == "7501011234"
    line = row.find("incomedata/incomerows/rowsenum")
    assert line.find("incomecode").text == "101"
    assert line.find("income").text == "24000.00"
    assert line.find("advancetax").text == "2400.00"
    assert line.find("healthinsbg").text == "3120.00"
    assert row.find("incomedata/sumtaxdeducted").text == "2400.00"


def test_explicit_payer_and_taxbase49(client):
    h = _setup(client, "ir2@example.com")
    person = _person()
    person["taxbase251"] = "20880.00"
    person["taxbase49"] = {"taxbase": "20880.00", "tax": "2088.00", "diff18": "-312.00", "sum19refund": "312.00"}
    payload = {
        "year": 2025, "isterm": 0,
        "payer": {"eik": "999888777", "name": "Правоприемник ООД", "mail": "b@b.bg"},
        "persons": [person],
    }
    r = client.post(IR, headers=h, json=payload)
    assert r.status_code == 200, r.text
    root = ET.fromstring(r.content.decode("windows-1251"))
    assert root.find("part1/eik").text == "999888777"
    assert root.find("part1/mail").text == "b@b.bg"
    inc = root.find("part2/rowsenum/incomedata")
    assert inc.find("taxbase251").text == "20880.00"
    # diff18 е единственото поле, което допуска отрицателна стойност
    assert inc.find("taxbase49/diff18").text == "-312.00"
    assert inc.find("taxbase49/sum19refund").text == "312.00"


def test_negative_income_rejected(client):
    h = _setup(client, "ir3@example.com")
    person = _person()
    person["income_lines"][0]["income"] = "-100.00"
    r = client.post(IR, headers=h, json={"year": 2025, "persons": [person]})
    assert r.status_code == 422  # не се допускат отрицателни стойности


def test_mixed_correction_codes_rejected(client):
    h = _setup(client, "ir4@example.com")
    # едно и също лице с основни (0) и коригиращи (1) данни в един файл
    payload = {"year": 2025, "persons": [_person(code=0), _person(code=1)]}
    r = client.post(IR, headers=h, json=payload)
    assert r.status_code == 422
    assert "смесване" in r.json()["detail"]


def test_year_before_2019_rejected(client):
    h = _setup(client, "ir5@example.com")
    r = client.post(IR, headers=h, json={"year": 2018, "persons": [_person()]})
    assert r.status_code == 422
