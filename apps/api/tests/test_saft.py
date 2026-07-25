"""Тестове за SAF-T експорта (одитен файл по OECD стандарт, българска версия)."""
import xml.etree.ElementTree as ET

from tests.conftest import register_and_login

ACC = "/api/v1/accounting"
VAT = "/api/v1/vat"
CP = "/api/v1/counterparties"
SUB = "/api/v1/submissions"
NS = "{urn:StandardAuditFile-Taxation-Financial:BG}"


def _setup(client, email: str, eik="208418861"):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    body = {
        "name": "ХЕПСУ КОНСУЛТИНГ ЕООД", "is_vat_registered": True,
        "address_city": "гр. София", "address_postcode": "1618",
        "address_line": "ул. Любляна 14", "name_latin": "Heppsu Consulting ltd",
    }
    if eik:
        body.update({"eik": eik, "vat_number": "BG" + eik})
    cid = client.post("/api/v1/companies", headers=auth, json=body).json()["id"]
    h = {**auth, "X-Company-Id": cid}
    acc = {a["code"]: a for a in client.post(f"{ACC}/chart/seed", headers=h).json()}
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    client.post(f"{VAT}/codes/seed", headers=h)
    return h, acc


def _post_entry(client, h, acc, dr, cr, amount, date="2026-07-15", num="DOC-1"):
    e = client.post(f"{ACC}/journal-entries", headers=h, json={
        "document_date": date, "document_number": num,
        "lines": [{"account_id": acc[dr]["id"], "debit": amount, "credit": "0"},
                  {"account_id": acc[cr]["id"], "debit": "0", "credit": amount}],
    }).json()
    client.post(f"{ACC}/journal-entries/{e['id']}/post", headers=h)
    return e["id"]


def _export(client, h, frm="2026-07-01", to="2026-07-31"):
    return client.get(f"{SUB}/saft?date_from={frm}&date_to={to}", headers=h)


# ============================ Провайдъри ============================
def test_export_providers_are_versioned(client):
    h, _ = _setup(client, "saft-prov@example.com")
    r = client.get(f"{SUB}/export-providers", headers=h).json()
    saft = next(p for p in r["providers"] if p["code"] == "SAFT_BG")
    assert saft["version"] == "1.0"
    assert saft["media_type"] == "application/xml"
    assert "версионирани" in r["note"]


# ============================ Структура на файла ============================
def test_saft_has_header_with_company_details(client):
    h, acc = _setup(client, "saft-head@example.com")
    _post_entry(client, h, acc, "501", "703", "1000.00")

    r = _export(client, h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/xml")
    assert "SAFT-BG-208418861-20260701-20260731.xml" in r.headers["content-disposition"]

    root = ET.fromstring(r.content.decode("utf-8"))
    assert root.tag == f"{NS}AuditFile"
    header = root.find(f"{NS}Header")
    assert header.find(f"{NS}AuditFileVersion").text == "1.0"
    assert header.find(f"{NS}AuditFileCountry").text == "BG"
    assert header.find(f"{NS}DefaultCurrencyCode").text == "EUR"
    company = header.find(f"{NS}Company")
    assert company.find(f"{NS}RegistrationNumber").text == "208418861"
    assert company.find(f"{NS}Name").text == "ХЕПСУ КОНСУЛТИНГ ЕООД"
    assert company.find(f"{NS}NameLatin").text == "Heppsu Consulting ltd"
    assert company.find(f"{NS}TaxRegistration/{NS}TaxRegistrationNumber").text == "BG208418861"
    addr = company.find(f"{NS}Address")
    assert addr.find(f"{NS}City").text == "гр. София"
    assert addr.find(f"{NS}PostalCode").text == "1618"
    # периодът на извадката
    sel = header.find(f"{NS}SelectionCriteria")
    assert sel.find(f"{NS}SelectionStartDate").text == "2026-07-01"
    assert sel.find(f"{NS}SelectionEndDate").text == "2026-07-31"


def test_saft_master_files_contain_chart_parties_and_taxes(client):
    h, acc = _setup(client, "saft-master@example.com")
    client.post(CP, headers=h, json={"type": "CUSTOMER", "name": "Клиент ООД",
                                     "eik": "111222333", "vat_number": "BG111222333"})
    client.post(CP, headers=h, json={"type": "SUPPLIER", "name": "Доставчик ЕООД",
                                     "eik": "444555666"})
    _post_entry(client, h, acc, "501", "703", "500.00")

    root = ET.fromstring(_export(client, h).content.decode("utf-8"))
    master = root.find(f"{NS}MasterFiles")

    # сметкоплан
    codes = {a.find(f"{NS}AccountID").text for a in master.findall(f"{NS}GeneralLedgerAccounts/{NS}Account")}
    assert {"501", "703", "411", "401", "4531"} <= codes
    revenue = next(a for a in master.findall(f"{NS}GeneralLedgerAccounts/{NS}Account")
                   if a.find(f"{NS}AccountID").text == "703")
    assert revenue.find(f"{NS}AccountType").text == "Income"

    # контрагенти в правилните секции
    customers = master.findall(f"{NS}Customers/{NS}Customer")
    suppliers = master.findall(f"{NS}Suppliers/{NS}Supplier")
    assert [c.find(f"{NS}Name").text for c in customers] == ["Клиент ООД"]
    assert [s.find(f"{NS}Name").text for s in suppliers] == ["Доставчик ЕООД"]
    assert customers[0].find(f"{NS}AccountID").text == "411"
    assert suppliers[0].find(f"{NS}AccountID").text == "401"
    assert customers[0].find(f"{NS}TaxRegistrationNumber").text == "BG111222333"

    # данъчна таблица от ДДС кодовете
    taxes = master.findall(f"{NS}TaxTable/{NS}TaxTableEntry")
    by_code = {t.find(f"{NS}TaxCode").text: t for t in taxes}
    assert "S20" in by_code and by_code["S20"].find(f"{NS}TaxPercentage").text == "20.00"
    assert all(t.find(f"{NS}TaxType").text == "VAT" for t in taxes)


def test_saft_general_ledger_entries_balance(client):
    h, acc = _setup(client, "saft-gl@example.com")
    _post_entry(client, h, acc, "501", "703", "1200.00", num="F-1")
    _post_entry(client, h, acc, "602", "401", "300.00", num="F-2")

    root = ET.fromstring(_export(client, h).content.decode("utf-8"))
    gl = root.find(f"{NS}GeneralLedgerEntries")
    assert gl.find(f"{NS}NumberOfEntries").text == "2"
    assert gl.find(f"{NS}TotalDebit").text == "1500.00"
    assert gl.find(f"{NS}TotalCredit").text == "1500.00"

    transactions = gl.findall(f"{NS}Journal/{NS}Transaction")
    assert len(transactions) == 2
    t = transactions[0]
    assert t.find(f"{NS}TransactionDate").text == "2026-07-15"
    assert t.find(f"{NS}Period").text == "07"
    assert t.find(f"{NS}PeriodYear").text == "2026"
    # всяка операция има дебитен и кредитен ред със сума и валута
    debit = t.find(f"{NS}DebitLine")
    credit = t.find(f"{NS}CreditLine")
    assert debit.find(f"{NS}Amount/{NS}Amount").text == "1200.00"
    assert debit.find(f"{NS}Amount/{NS}CurrencyCode").text == "EUR"
    assert credit.find(f"{NS}AccountID").text == "703"


def test_saft_respects_period_filter(client):
    h, acc = _setup(client, "saft-period@example.com")
    _post_entry(client, h, acc, "501", "703", "100.00", date="2026-06-10", num="JUN")
    _post_entry(client, h, acc, "501", "703", "200.00", date="2026-07-10", num="JUL")

    root = ET.fromstring(_export(client, h, "2026-07-01", "2026-07-31").content.decode("utf-8"))
    gl = root.find(f"{NS}GeneralLedgerEntries")
    assert gl.find(f"{NS}NumberOfEntries").text == "1"
    assert gl.find(f"{NS}TotalDebit").text == "200.00"


def test_saft_excludes_draft_entries(client):
    """Черновите не влизат в одитния файл."""
    h, acc = _setup(client, "saft-draft@example.com")
    client.post(f"{ACC}/journal-entries", headers=h, json={
        "document_date": "2026-07-15", "document_number": "DRAFT",
        "lines": [{"account_id": acc["501"]["id"], "debit": "99.00", "credit": "0"},
                  {"account_id": acc["703"]["id"], "debit": "0", "credit": "99.00"}],
    })
    root = ET.fromstring(_export(client, h).content.decode("utf-8"))
    assert root.find(f"{NS}GeneralLedgerEntries/{NS}NumberOfEntries").text == "0"


# ============================ Преглед и предупреждения ============================
def test_saft_preview_lists_contents(client):
    h, acc = _setup(client, "saft-prev@example.com")
    _post_entry(client, h, acc, "501", "703", "1000.00")
    pv = client.get(f"{SUB}/saft/preview?date_from=2026-07-01&date_to=2026-07-31", headers=h).json()
    assert pv["provider"] == "SAFT_BG" and pv["version"] == "1.0"
    assert pv["size_bytes"] > 0
    assert any("MasterFiles" in c for c in pv["contents"])
    assert any("1 операции" in c for c in pv["contents"])
    assert pv["warnings"] == []


def test_saft_warns_about_missing_identifiers(client):
    h, acc = _setup(client, "saft-noid@example.com", eik=None)
    pv = client.get(f"{SUB}/saft/preview?date_from=2026-07-01&date_to=2026-07-31", headers=h).json()
    joined = " ".join(pv["warnings"])
    assert "ЕИК" in joined
    assert "Няма осчетоводени операции" in joined


def test_saft_requires_export_permission(client):
    """Без право reports.export файлът не се генерира."""
    from tests.conftest import register_and_login as reg

    h, _ = _setup(client, "saft-perm-owner@example.com")
    roles = {r["code"]: r for r in client.post("/api/v1/rbac/roles/seed", headers=h).json()}
    reg(client, "saft-perm-emp@example.com")
    m = client.post("/api/v1/members", headers=h,
                    json={"email": "saft-perm-emp@example.com", "role": "ACCOUNTANT"}).json()
    client.post(f"/api/v1/rbac/members/{m['id']}/role", headers=h,
                json={"role_id": roles["EMPLOYEE"]["id"]})
    token = client.post("/api/v1/auth/login",
                        json={"email": "saft-perm-emp@example.com", "password": "supersecret1"}).json()["access_token"]
    emp_h = {"Authorization": f"Bearer {token}", "X-Company-Id": h["X-Company-Id"]}

    r = client.get(f"{SUB}/saft?date_from=2026-07-01&date_to=2026-07-31", headers=emp_h)
    assert r.status_code == 403
    assert r.json()["code"] == "PERMISSION_DENIED"
