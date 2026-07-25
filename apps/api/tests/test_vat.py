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


def test_close_vat_period(client):
    h, codes = _setup_vat(client, "vatclose@example.com")
    ACC = "/api/v1/accounting"
    accounts = {a["code"]: a for a in client.get(f"{ACC}/accounts", headers=h).json()}
    def je(dr, cr, amt, num):
        e = client.post(f"{ACC}/journal-entries", headers=h, json={"document_date": "2026-07-15", "document_number": num,
            "lines": [{"account_id": accounts[dr]["id"], "debit": amt, "credit": "0"},
                      {"account_id": accounts[cr]["id"], "debit": "0", "credit": amt}]}).json()
        client.post(f"{ACC}/journal-entries/{e['id']}/post", headers=h)
    # продажба: Дт 411 1200 / Кт 703 1000 / Кт 4532 200  → тук опростено две операции
    je("411", "703", "1000.00", "S-1")
    je("411", "4532", "200.00", "S-1v")   # начислен ДДС продажби
    # покупка: Дт 4531 100 (данъчен кредит)
    je("4531", "401", "100.00", "P-1v")

    pid = _period_id(client, h)
    r = client.post(f"{VAT}/periods/{pid}/close", headers=h)
    assert r.status_code == 201, r.text
    cl = r.json()
    assert float(cl["output_vat"]) == 200.0
    assert float(cl["input_vat"]) == 100.0
    assert float(cl["net_payable"]) == 100.0
    assert float(cl["net_refundable"]) == 0.0
    assert cl["journal_entry_id"]

    # приключвателната операция зануляет 4531/4532 и дава 100 в 4538
    tb = {x["code"]: x for x in client.get("/api/v1/reports/trial-balance", headers=h).json()["rows"]}
    assert float(tb["4532"]["closing_balance"]) == 0.0
    assert float(tb["4531"]["closing_balance"]) == 0.0
    assert float(tb["4538"]["closing_balance"]) == -100.0   # кредитно салдо = задължение за внасяне


def test_close_twice_rejected(client):
    h, codes = _setup_vat(client, "vatclose2@example.com")
    ACC = "/api/v1/accounting"
    accounts = {a["code"]: a for a in client.get(f"{ACC}/accounts", headers=h).json()}
    e = client.post(f"{ACC}/journal-entries", headers=h, json={"document_date": "2026-07-15", "document_number": "S",
        "lines": [{"account_id": accounts["411"]["id"], "debit": "200.00", "credit": "0"},
                  {"account_id": accounts["4532"]["id"], "debit": "0", "credit": "200.00"}]}).json()
    client.post(f"{ACC}/journal-entries/{e['id']}/post", headers=h)
    pid = _period_id(client, h)
    assert client.post(f"{VAT}/periods/{pid}/close", headers=h).status_code == 201
    assert client.post(f"{VAT}/periods/{pid}/close", headers=h).status_code == 409


def _post_je(client, h, accounts, dr: str, cr: str, amount: str, num: str):
    """Помощна: осчетоводена операция с два реда (дебит/кредит)."""
    e = client.post(
        f"{ACC}/journal-entries",
        headers=h,
        json={
            "document_date": "2026-07-15",
            "document_number": num,
            "lines": [
                {"account_id": accounts[dr]["id"], "debit": amount, "credit": "0"},
                {"account_id": accounts[cr]["id"], "debit": "0", "credit": amount},
            ],
        },
    ).json()
    client.post(f"{ACC}/journal-entries/{e['id']}/post", headers=h)


def _periods(client, h) -> list[dict]:
    r = client.get(f"{VAT}/periods", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _period_row(client, h, code: str = "2026-07") -> dict:
    return next(p for p in _periods(client, h) if p["code"] == code)


def test_list_vat_periods_sorted_and_summed(client):
    h, codes = _setup_vat(client, "vatperiods@example.com")
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["S20"]["id"], "1000.00", doc="S-1"))
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["P20"]["id"], "500.00", doc="P-1"))

    periods = _periods(client, h)
    assert len(periods) == 12  # 12 месечни периода за фискалната година
    # най-новите първи
    assert [p["code"] for p in periods][:3] == ["2026-12", "2026-11", "2026-10"]

    july = next(p for p in periods if p["code"] == "2026-07")
    assert july["start_date"] == "2026-07-01" and july["end_date"] == "2026-07-31"
    assert float(july["output_vat"]) == 200.0
    assert float(july["input_vat"]) == 100.0
    assert float(july["net_payable"]) == 100.0
    assert july["status"] == "READY"
    assert july["closed_at"] is None
    # период без данни
    june = next(p for p in periods if p["code"] == "2026-06")
    assert june["status"] == "OPEN"
    assert float(june["net_payable"]) == 0.0


def test_vat_period_refundable_is_negative(client):
    h, codes = _setup_vat(client, "vatperiodsref@example.com")
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["S20"]["id"], "100.00", doc="S-1"))
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["P20"]["id"], "1000.00", doc="P-1"))
    july = _period_row(client, h)
    # начислен 20, кредит 200 → −180 (за възстановяване)
    assert float(july["net_payable"]) == -180.0
    assert july["status"] == "READY"


def test_vat_period_ready_then_approved(client):
    h, codes = _setup_vat(client, "vatapprove@example.com")
    accounts = {a["code"]: a for a in client.get(f"{ACC}/accounts", headers=h).json()}
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["S20"]["id"], "1000.00", doc="S-1"))
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["P20"]["id"], "500.00", doc="P-1"))
    _post_je(client, h, accounts, "411", "4532", "200.00", "S-1v")
    _post_je(client, h, accounts, "4531", "401", "100.00", "P-1v")

    assert _period_row(client, h)["status"] == "READY"

    pid = _period_id(client, h)
    assert client.post(f"{VAT}/periods/{pid}/close", headers=h).status_code == 201

    july = _period_row(client, h)
    assert july["status"] == "APPROVED"
    assert july["closed_at"] is not None
    assert float(july["output_vat"]) == 200.0
    assert float(july["input_vat"]) == 100.0
    assert float(july["net_payable"]) == 100.0


def test_reject_vat_period(client):
    h, codes = _setup_vat(client, "vatreject@example.com")
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["S20"]["id"], "1000.00", doc="S-1"))
    pid = _period_id(client, h)

    r = client.post(f"{VAT}/periods/{pid}/reject", headers=h, json={"reason": "Липсва фактура F-7"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["period_id"] == pid
    assert out["status"] == "REJECTED"
    assert out["rejection_reason"] == "Липсва фактура F-7"
    assert float(out["output_vat"]) == 200.0

    # отразено и в списъка
    july = _period_row(client, h)
    assert july["status"] == "REJECTED"
    assert july["rejection_reason"] == "Липсва фактура F-7"


def test_reject_without_reason(client):
    h, codes = _setup_vat(client, "vatreject2@example.com")
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["S20"]["id"], "100.00", doc="S-1"))
    pid = _period_id(client, h)
    r = client.post(f"{VAT}/periods/{pid}/reject", headers=h, json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "REJECTED"
    assert r.json()["rejection_reason"] is None


def test_reject_approved_period_conflict(client):
    h, codes = _setup_vat(client, "vatreject3@example.com")
    accounts = {a["code"]: a for a in client.get(f"{ACC}/accounts", headers=h).json()}
    _post_je(client, h, accounts, "411", "4532", "200.00", "S-1v")
    pid = _period_id(client, h)
    assert client.post(f"{VAT}/periods/{pid}/close", headers=h).status_code == 201

    r = client.post(f"{VAT}/periods/{pid}/reject", headers=h, json={"reason": "късно"})
    assert r.status_code == 409
    assert "приключен" in r.json()["detail"]


def test_approve_after_reject_clears_status(client):
    h, codes = _setup_vat(client, "vatreject4@example.com")
    accounts = {a["code"]: a for a in client.get(f"{ACC}/accounts", headers=h).json()}
    client.post(f"{VAT}/entries", headers=h, json=_entry(codes["S20"]["id"], "1000.00", doc="S-1"))
    _post_je(client, h, accounts, "411", "4532", "200.00", "S-1v")
    pid = _period_id(client, h)

    assert client.post(f"{VAT}/periods/{pid}/reject", headers=h, json={"reason": "корекция"}).status_code == 200
    assert _period_row(client, h)["status"] == "REJECTED"
    # след корекциите отчетът се одобрява → приключването има превес над отказа
    assert client.post(f"{VAT}/periods/{pid}/close", headers=h).status_code == 201
    july = _period_row(client, h)
    assert july["status"] == "APPROVED"
    assert july["rejection_reason"] is None


def test_vat_periods_tenant_isolated(client):
    h_a, codes_a = _setup_vat(client, "vatper-a@example.com")
    client.post(f"{VAT}/entries", headers=h_a, json=_entry(codes_a["S20"]["id"], "1000.00", doc="S-1"))
    h_b, _ = _setup_vat(client, "vatper-b@example.com")
    assert all(float(p["output_vat"]) == 0.0 for p in _periods(client, h_b))
    assert all(p["status"] == "OPEN" for p in _periods(client, h_b))


def test_no_vat_entries_after_closing(client):
    h, codes = _setup_vat(client, "vatclose3@example.com")
    ACC = "/api/v1/accounting"
    accounts = {a["code"]: a for a in client.get(f"{ACC}/accounts", headers=h).json()}
    e = client.post(f"{ACC}/journal-entries", headers=h, json={"document_date": "2026-07-15", "document_number": "S",
        "lines": [{"account_id": accounts["411"]["id"], "debit": "200.00", "credit": "0"},
                  {"account_id": accounts["4532"]["id"], "debit": "0", "credit": "200.00"}]}).json()
    client.post(f"{ACC}/journal-entries/{e['id']}/post", headers=h)
    pid = _period_id(client, h)
    client.post(f"{VAT}/periods/{pid}/close", headers=h)
    # нов ДДС запис в приключен период се отхвърля
    r = client.post(f"{VAT}/entries", headers=h, json=_entry(codes["S20"]["id"], "500.00", doc="LATE"))
    assert r.status_code == 409
    assert "приключен" in r.json()["detail"]
