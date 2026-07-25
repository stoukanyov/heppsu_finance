from tests.conftest import register_and_login

CP = "/api/v1/counterparties"


def _setup(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post("/api/v1/companies", headers=auth, json={"name": "Акме ЕООД"}).json()["id"]
    return {**auth, "X-Company-Id": company_id}


def _customer(name="Клиент ООД", eik=None, vat=None, iban=None):
    body = {"type": "CUSTOMER", "name": name}
    if eik:
        body["eik"] = eik
    if vat:
        body["vat_number"] = vat
    if iban:
        body["bank_accounts"] = [{"iban": iban, "is_primary": True}]
    return body


def test_create_with_bank_account(client):
    h = _setup(client, "cp1@example.com")
    r = client.post(f"{CP}", headers=h, json=_customer(eik="203123456", iban="BG80BNBG96611020345678"))
    assert r.status_code == 201, r.text
    cp = r.json()
    assert cp["type"] == "CUSTOMER"
    assert cp["is_active"] is True
    assert len(cp["bank_accounts"]) == 1
    assert cp["bank_accounts"][0]["iban"] == "BG80BNBG96611020345678"


def test_hard_duplicate_eik_rejected(client):
    h = _setup(client, "cp2@example.com")
    client.post(f"{CP}", headers=h, json=_customer(name="Първи", eik="111222333"))
    r = client.post(f"{CP}", headers=h, json=_customer(name="Втори", eik="111222333"))
    assert r.status_code == 409
    assert "ЕИК" in r.json()["detail"]


def test_hard_duplicate_vat_rejected(client):
    h = _setup(client, "cp3@example.com")
    client.post(f"{CP}", headers=h, json=_customer(name="A", vat="BG111222333"))
    r = client.post(f"{CP}", headers=h, json=_customer(name="B", vat="BG111222333"))
    assert r.status_code == 409


def test_list_filter_customer_includes_both(client):
    h = _setup(client, "cp4@example.com")
    client.post(f"{CP}", headers=h, json={"type": "CUSTOMER", "name": "Клиент"})
    client.post(f"{CP}", headers=h, json={"type": "SUPPLIER", "name": "Доставчик"})
    client.post(f"{CP}", headers=h, json={"type": "BOTH", "name": "И двете"})

    customers = client.get(f"{CP}?type=CUSTOMER", headers=h).json()
    names = {c["name"] for c in customers}
    assert names == {"Клиент", "И двете"}


def test_search_query(client):
    h = _setup(client, "cp5@example.com")
    client.post(f"{CP}", headers=h, json=_customer(name="Алфа Технолоджис"))
    client.post(f"{CP}", headers=h, json=_customer(name="Бета Софт"))
    r = client.get(f"{CP}?q=алфа", headers=h).json()
    assert len(r) == 1 and r[0]["name"] == "Алфа Технолоджис"


def test_update_partial(client):
    h = _setup(client, "cp6@example.com")
    cp_id = client.post(f"{CP}", headers=h, json=_customer(name="Старо име")).json()["id"]
    r = client.patch(f"{CP}/{cp_id}", headers=h, json={"name": "Ново име", "email": "info@acme.bg"})
    assert r.status_code == 200
    assert r.json()["name"] == "Ново име"
    assert r.json()["email"] == "info@acme.bg"


def test_deactivate_via_update(client):
    h = _setup(client, "cp7@example.com")
    cp_id = client.post(f"{CP}", headers=h, json=_customer()).json()["id"]
    r = client.patch(f"{CP}/{cp_id}", headers=h, json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False


def test_find_duplicates_by_eik_and_iban(client):
    h = _setup(client, "cp8@example.com")
    client.post(f"{CP}", headers=h, json=_customer(name="Акме ЕООД", eik="999888777", iban="BG18RZBB91550123456789"))

    r = client.post(f"{CP}/check-duplicates", headers=h, json={"eik": "999888777"}).json()
    assert len(r) == 1 and "ЕИК" in r[0]["reasons"]

    r = client.post(f"{CP}/check-duplicates", headers=h, json={"iban": "BG18RZBB91550123456789"}).json()
    assert len(r) == 1 and "IBAN" in r[0]["reasons"]

    # сходно наименование въпреки различна правна форма/регистър
    r = client.post(f"{CP}/check-duplicates", headers=h, json={"name": "акме оод"}).json()
    assert len(r) == 1 and "сходно наименование" in r[0]["reasons"]


def test_invalid_default_account_rejected(client):
    h = _setup(client, "cp9@example.com")
    body = _customer()
    body["default_account_id"] = "00000000-0000-0000-0000-000000000000"
    r = client.post(f"{CP}", headers=h, json=body)
    assert r.status_code == 422
    assert "сметка" in r.json()["detail"].lower()


def test_tenant_isolation(client):
    h_a = _setup(client, "cp-a@example.com")
    cp_id = client.post(f"{CP}", headers=h_a, json=_customer()).json()["id"]
    h_b = _setup(client, "cp-b@example.com")
    r = client.get(f"{CP}/{cp_id}", headers=h_b)
    assert r.status_code == 404
