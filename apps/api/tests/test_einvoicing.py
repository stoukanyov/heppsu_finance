"""Електронно фактуриране: износ по EN 16931 / PEPPOL BIS 3.0, валидация и импорт."""
import io
import xml.etree.ElementTree as ET

from tests.conftest import register_and_login

INV = "/api/v1/invoices"
PUR = "/api/v1/purchase-invoices"
ACC = "/api/v1/accounting"
NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"


def _setup(client, email):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    cid = client.post("/api/v1/companies", headers=auth, json={
        "name": "Продавач ЕООД", "eik": "203123456", "vat_number": "BG203123456",
        "is_vat_registered": True}).json()["id"]
    h = {**auth, "X-Company-Id": cid}
    acc = {a["code"]: a["id"] for a in client.post(f"{ACC}/chart/seed", headers=h).json()}
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    codes = {c["code"]: c["id"] for c in client.post("/api/v1/vat/codes/seed", headers=h).json()}
    cp = client.post("/api/v1/counterparties", headers=h, json={
        "name": "Купувач ООД", "type": "BOTH", "eik": "111222333",
        "vat_number": "BG111222333", "address": "гр. Пловдив"}).json()
    return h, acc, codes, cp


def _issue_invoice(client, h, codes, cp, net="1000.00", qty="2.000", price="500.00"):
    # Кодовете за продажби започват с "S"; "P20" е покупен и се отхвърля.
    vat_code = codes["S20"]
    inv = client.post(INV, headers=h, json={
        "counterparty_id": cp["id"], "issue_date": "2026-03-15", "due_date": "2026-04-14",
        "currency": "EUR", "vat_code_id": vat_code,
        "lines": [{"description": "Консултантска услуга", "quantity": qty, "unit_price": price}],
    }).json()
    issued = client.post(f"{INV}/{inv['id']}/issue", headers=h).json()
    return issued


def _tree(xml: bytes):
    return ET.fromstring(xml)


def _cbc(node, tag):
    found = node.find(f"{{{NS_CBC}}}{tag}")
    return (found.text or "").strip() if found is not None else None


# ------------------------------------------------------------------ износ
def test_ubl_export_has_peppol_identifiers(client):
    h, acc, codes, cp = _setup(client, "ubl1@example.com")
    inv = _issue_invoice(client, h, codes, cp)

    r = client.get(f"{INV}/{inv['id']}/ubl", headers=h)
    assert r.status_code == 200, r.text
    assert "xml" in r.headers["content-type"]

    root = _tree(r.content)
    assert root.tag.endswith("Invoice")
    assert "peppol" in _cbc(root, "CustomizationID")
    assert _cbc(root, "InvoiceTypeCode") == "380"
    assert _cbc(root, "DocumentCurrencyCode") == "EUR"
    assert _cbc(root, "IssueDate") == "2026-03-15"
    assert _cbc(root, "DueDate") == "2026-04-14"


def test_ubl_export_carries_both_parties(client):
    h, acc, codes, cp = _setup(client, "ubl2@example.com")
    inv = _issue_invoice(client, h, codes, cp)
    root = _tree(client.get(f"{INV}/{inv['id']}/ubl", headers=h).content)

    def party_name(wrapper):
        node = root.find(f"{{{NS_CAC}}}{wrapper}/{{{NS_CAC}}}Party/{{{NS_CAC}}}PartyLegalEntity")
        return node.findtext(f"{{{NS_CBC}}}RegistrationName")

    assert party_name("AccountingSupplierParty") == "Продавач ЕООД"
    assert party_name("AccountingCustomerParty") == "Купувач ООД"

    endpoint = root.find(f"{{{NS_CAC}}}AccountingSupplierParty/{{{NS_CAC}}}Party/{{{NS_CBC}}}EndpointID")
    assert endpoint.text == "BG203123456"
    assert endpoint.get("schemeID") == "9926"


def test_ubl_totals_are_consistent(client):
    h, acc, codes, cp = _setup(client, "ubl3@example.com")
    inv = _issue_invoice(client, h, codes, cp)
    root = _tree(client.get(f"{INV}/{inv['id']}/ubl", headers=h).content)

    totals = root.find(f"{{{NS_CAC}}}LegalMonetaryTotal")
    net = float(_cbc(totals, "TaxExclusiveAmount"))
    gross = float(_cbc(totals, "TaxInclusiveAmount"))
    payable = float(_cbc(totals, "PayableAmount"))
    tax = float(_cbc(root.find(f"{{{NS_CAC}}}TaxTotal"), "TaxAmount"))

    assert net == 1000.0
    assert round(net + tax, 2) == gross
    assert payable == gross


def test_ubl_lines_are_exported(client):
    h, acc, codes, cp = _setup(client, "ubl4@example.com")
    inv = _issue_invoice(client, h, codes, cp)
    root = _tree(client.get(f"{INV}/{inv['id']}/ubl", headers=h).content)

    lines = root.findall(f"{{{NS_CAC}}}InvoiceLine")
    assert len(lines) == 1
    item = lines[0].find(f"{{{NS_CAC}}}Item")
    assert item.findtext(f"{{{NS_CBC}}}Name") == "Консултантска услуга"
    assert _cbc(lines[0], "InvoicedQuantity") == "2.000"


# ------------------------------------------------------------------ валидация
def test_generated_invoice_passes_business_rules(client):
    h, acc, codes, cp = _setup(client, "ubl5@example.com")
    inv = _issue_invoice(client, h, codes, cp)

    body = client.get(f"{INV}/{inv['id']}/ubl/validate", headers=h).json()
    assert body["ok"], body["errors"]


def test_validator_catches_missing_mandatory_fields():
    from app.tax_engine.export.ubl import UblBisBillingProvider

    xml = b'<?xml version="1.0" encoding="UTF-8"?><Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"/>'
    report = UblBisBillingProvider().validate(xml)
    assert not report.ok
    codes = " ".join(i.message for i in report.errors)
    assert "BR-01" in codes and "BR-02" in codes and "BR-16" in codes


def test_validator_catches_wrong_totals():
    from app.tax_engine.export.ubl import UblBisBillingProvider

    xml = _minimal_invoice(payable="999.00")
    report = UblBisBillingProvider().validate(xml)
    assert not report.ok
    assert any("BR-CO-15" in i.message for i in report.errors)


def test_validator_catches_line_sum_mismatch():
    from app.tax_engine.export.ubl import UblBisBillingProvider

    xml = _minimal_invoice(line_total="50.00")
    report = UblBisBillingProvider().validate(xml)
    assert any("BR-CO-10" in i.message for i in report.errors)


def test_validator_warns_about_missing_endpoint():
    from app.tax_engine.export.ubl import UblBisBillingProvider

    report = UblBisBillingProvider().validate(_minimal_invoice(endpoint=False))
    assert report.ok
    assert any("EndpointID" in i.message for i in report.warnings)


def test_malformed_xml_is_reported():
    from app.tax_engine.export.ubl import UblBisBillingProvider

    report = UblBisBillingProvider().validate(b"<Invoice>")
    assert not report.ok
    assert "не е валиден XML" in report.errors[0].message


def _minimal_invoice(payable="120.00", line_total="100.00", endpoint=True) -> bytes:
    ep = '<cbc:EndpointID schemeID="9926">BG111222333</cbc:EndpointID>' if endpoint else ""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
  xmlns:cac="{NS_CAC}" xmlns:cbc="{NS_CBC}">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0</cbc:CustomizationID>
  <cbc:ID>0000000001</cbc:ID>
  <cbc:IssueDate>2026-03-15</cbc:IssueDate>
  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty><cac:Party>{ep}
    <cac:PartyLegalEntity><cbc:RegistrationName>Доставчик ООД</cbc:RegistrationName>
      <cbc:CompanyID>111222333</cbc:CompanyID></cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyLegalEntity><cbc:RegistrationName>Купувач ЕООД</cbc:RegistrationName></cac:PartyLegalEntity>
    </cac:Party></cac:AccountingCustomerParty>
  <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">20.00</cbc:TaxAmount></cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="EUR">100.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="EUR">120.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">{payable}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine><cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="C62">1.000</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="EUR">{line_total}</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Услуга</cbc:Name></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="EUR">100.0000</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>
</Invoice>'''.encode()


# ------------------------------------------------------------------ импорт
def test_import_creates_draft_purchase(client):
    h, acc, codes, cp = _setup(client, "ubl6@example.com")
    xml = _minimal_invoice()

    r = client.post(f"{PUR}/import-ubl", headers=h,
                    files={"file": ("inv.xml", io.BytesIO(xml), "application/xml")},
                    data={"vat_code_id": codes["P20"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True
    assert body["supplier"] == "Купувач ООД"      # намерен по ЕИК 111222333
    assert body["document_number"] == "0000000001"

    purchase = client.get(f"{PUR}/{body['purchase_id']}", headers=h).json()
    assert purchase["supplier_document_number"] == "0000000001"


def test_import_without_known_supplier_does_not_create_silently(client):
    h, acc, codes, cp = _setup(client, "ubl7@example.com")
    xml = _minimal_invoice().replace(b"111222333", b"999888777")

    body = client.post(f"{PUR}/import-ubl", headers=h,
                       files={"file": ("inv.xml", io.BytesIO(xml), "application/xml")}).json()
    assert body["created"] is False
    assert "не е в регистъра" in body["reason"]
    assert body["parsed"]["document_number"] == "0000000001"


def test_import_refuses_invalid_document(client):
    h, acc, codes, cp = _setup(client, "ubl8@example.com")
    bad = b'<?xml version="1.0"?><Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"/>'

    r = client.post(f"{PUR}/import-ubl", headers=h,
                    files={"file": ("inv.xml", io.BytesIO(bad), "application/xml")})
    assert r.status_code == 422
    assert "EN 16931" in r.json()["detail"]


def test_round_trip_export_then_import(client):
    """Изнесеното от нас трябва да може да се внесе от нас — най-простата проверка за съгласуваност."""
    h, acc, codes, cp = _setup(client, "ubl9@example.com")
    inv = _issue_invoice(client, h, codes, cp)
    xml = client.get(f"{INV}/{inv['id']}/ubl", headers=h).content

    from app.tax_engine.export.ubl import parse_ubl

    parsed = parse_ubl(xml)
    assert parsed["currency"] == "EUR"
    assert parsed["supplier_name"] == "Продавач ЕООД"
    assert str(parsed["subtotal"]) == "1000.00"
    assert len(parsed["lines"]) == 1
    assert parsed["lines"][0]["description"] == "Консултантска услуга"


def test_provider_is_registered_and_versioned():
    from app.tax_engine.export.registry import get_export_provider

    provider = get_export_provider("UBL_BIS")
    assert provider.version == "3.0"
    assert get_export_provider("UBL_BIS", "3.0") is not None
