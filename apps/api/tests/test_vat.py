from tests.conftest import register_and_login

VAT = "/api/v1/vat"
ACC = "/api/v1/accounting"


def _setup_vat(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post(
        "/api/v1/companies", headers=auth, json={"name": "Акме ЕООД", "is_vat_registered": True}
    ).json()["id"]
    h = {**auth, "X-Company-Id": company_id}
    client.post(f"{ACC}/chart/seed", headers=h)
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    r = client.post(f"{VAT}/codes/seed", headers=h)
    assert r.status_code == 201, r.text
    codes = {c["code"]: c for c in r.json()}
    return h, codes


def _period_id(client, h, code: str = "2026-07") -> str:
    year = client.get(f"{ACC}/fiscal-years", headers=h).json()[0]
    return next(p["id"] for p in year["periods"] if p["code"] == code)


def _entry(code_id, base, *, vat=None, doc="F-1", vat_no=None):
    payload = {
        "vat_code_id": code_id,
        "document_date": "2026-07-10",
        "document_number": doc,
        "counterparty_name": "Контрагент ООД",
        "tax_base": base,
    }
    if vat is not None:
        payload["vat_amount"] = vat
    if vat_no is not None:
        payload["counterparty_vat_number"] = vat_no
    return payload


def test_seed_vat_codes(client):
    h, codes = _setup_vat(client, "vatseed@example.com")
    assert "S20" in codes and "P20" in codes and "PICA" in codes
    assert codes["PICA"]["requires_vies"] is True
    assert float(codes["S20"]["rate"]) == 20.0


def test_create_sale_entry_auto_vat(client):
    h, codes = _setup_vat(client, "sale@example.com")
    r = client.post(f"{VAT}/entries", headers=h, json=_entry(codes["S20"]["id"], "1000.00"))
    assert r.status_code == 201, r.text
    entry = r.json()
    assert float(entry["vat_amount"]) == 200.0
    assert entry["direction"] == "SALE"


def test_vat_amount_mismatch_rejected(client):
    h, codes = _setup_vat(client, "mismatch@example.com")
    r = client.post(
        f"{VAT}/entries", headers=h, json=_entry(codes["S20"]["id"], "1000.00", vat="150.00")
    )
    assert r.status_code == 422
    assert "не съответства" in r.json()["detail"]


def test_vies_number_required(client):
    h, codes = _setup_vat(client, "vies@example.com")
    # ВОП (PICA) изисква ДДС номер
    r = client.post(f"{VAT}/entries", headers=h, json=_entry(codes["PICA"]["id"], "500.00"))
    assert r.status_code == 422
    assert "VIES" in r.json()["detail"]
    # със ДДС номер минава
    r = client.post(
        f"{VAT}/entries", headers=h, json=_entry(codes["PICA"]["id"], "500.00", vat_no="DE123456789")
    )
    assert r.status_code == 201, r.text


def test_entry_without_period_rejected(client):
    h, codes = _setup_vat(client, "vatnoperiod@example.com")
    payload = _entry(codes["S20"]["id"], "100.00")
    payload["document_date"] = "2030-01-01"
    r = client.post(f"{VAT}/entries", headers=h, json=payload)
    assert r.status_code == 422


def test_vat_return_computation(client):
    h, codes = _setup_vat(client, "return@example.com")
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["S20"]["id"], "1000.00", doc="S-1"))
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["P20"]["id"], "500.00", doc="P-1"))

    pid = _period_id(client, h)
    r = client.get(f"{VAT}/returns/{pid}", headers=h)
    assert r.status_code == 200, r.text
    ret = r.json()
    assert ret["sales"]["count"] == 1
    assert float(ret["sales"]["total_vat"]) == 200.0
    assert float(ret["purchases"]["total_credit"]) == 100.0
    # 200 (продажби) - 100 (кредит) = 100 за внасяне
    assert float(ret["vat_payable"]) == 100.0
    assert float(ret["vat_refundable"]) == 0.0
    assert ret["has_blocking_errors"] is False


def test_purchase_without_credit_not_deducted(client):
    h, codes = _setup_vat(client, "nocredit@example.com")
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["S20"]["id"], "1000.00", doc="S-2"))
    # покупка без право на кредит — ДДС не намалява задължението
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["PNOCR"]["id"], "500.00", doc="P-2"))
    pid = _period_id(client, h)
    ret = client.get(f"{VAT}/returns/{pid}", headers=h).json()
    assert float(ret["purchases"]["total_credit"]) == 0.0
    assert float(ret["vat_payable"]) == 200.0


def test_duplicate_document_control(client):
    h, codes = _setup_vat(client, "dup@example.com")
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["P20"]["id"], "100.00", doc="DUP-1"))
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["P20"]["id"], "100.00", doc="DUP-1"))
    pid = _period_id(client, h)
    controls = client.get(f"{VAT}/periods/{pid}/controls", headers=h).json()
    assert any(c["code"] == "DUPLICATE_DOCUMENT" for c in controls)


def test_vat_codes_tenant_isolated(client):
    h_a, _ = _setup_vat(client, "vat-tenant-a@example.com")
    r = client.get(f"{VAT}/codes", headers=h_a)
    assert r.status_code == 200 and len(r.json()) == 10


def test_vat_declaration_cells(client):
    h, codes = _setup_vat(client, "decl@example.com")
    # продажба 20%: основа 1000, ДДС 200
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["S20"]["id"], "1000.00", doc="S-1"))
    # покупка с пълен кредит: основа 500, ДДС 100
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["P20"]["id"], "500.00", doc="P-1"))
    pid = _period_id(client, h)
    r = client.get(f"{VAT}/returns/{pid}/declaration", headers=h)
    assert r.status_code == 200, r.text
    decl = r.json()
    cells = {c["cell"]: float(c["amount"]) for c in decl["cells"]}
    assert cells["11"] == 1000.0   # ДО облагаеми 20%
    assert cells["20"] == 200.0    # всичко начислен ДДС
    assert cells["31"] == 500.0    # ДО с право на пълен кредит
    assert cells["41"] == 100.0    # ДДС пълен кредит
    assert cells["40"] == 100.0    # общ данъчен кредит
    assert cells["50"] == 100.0    # ДДС за внасяне
    assert cells["60"] == 0.0


def test_vat_declaration_refundable(client):
    h, codes = _setup_vat(client, "declref@example.com")
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["S20"]["id"], "100.00", doc="S-1"))
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["P20"]["id"], "1000.00", doc="P-1"))
    pid = _period_id(client, h)
    cells = {
        c["cell"]: float(c["amount"])
        for c in client.get(f"{VAT}/returns/{pid}/declaration", headers=h).json()["cells"]
    }
    # начислен 20, кредит 200 → 180 за възстановяване
    assert cells["50"] == 0.0
    assert cells["60"] == 180.0


def test_nap_files_zip(client):
    import io
    import zipfile

    h, codes = _setup_vat(client, "napzip@example.com")
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["S20"]["id"], "1000.00", doc="S-1"))
    client.post(
        f"{VAT}/entries",
        headers=h,
        json=_entry(codes["SICS"]["id"], "2000.00", doc="S-2", vat_no="DE111111111"),
    )
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["P20"]["id"], "500.00", doc="P-1"))
    pid = _period_id(client, h)
    r = client.get(f"{VAT}/returns/{pid}/nap-files", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert {"POKUPKI.TXT", "PRODAGBI.TXT", "DEKLAR.TXT"} <= names
    assert "VIES.TXT" in names  # има ВОД → VIES файл
    # съдържанието е CP1251 и има редове
    prodagbi = zf.read("PRODAGBI.TXT").decode("cp1251")
    assert "S-1" in prodagbi and "S-2" in prodagbi
    deklar = zf.read("DEKLAR.TXT").decode("cp1251")
    assert "50;" in deklar or "60;" in deklar  # има клетка резултат
    vies = zf.read("VIES.TXT").decode("cp1251")
    assert "DE111111111" in vies
