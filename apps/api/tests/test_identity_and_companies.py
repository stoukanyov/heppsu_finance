from tests.conftest import register_and_login


def test_register_and_me(client):
    token = register_and_login(client, "owner@example.com")
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == "owner@example.com"


def test_duplicate_registration_rejected(client):
    register_and_login(client, "dup@example.com")
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "password": "supersecret1"},
    )
    assert r.status_code == 409


def test_login_wrong_password(client):
    register_and_login(client, "wrongpass@example.com")
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "wrongpass@example.com", "password": "nopenope1"},
    )
    assert r.status_code == 401


def test_me_requires_auth(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code in (401, 403)


def test_create_and_list_company(client):
    token = register_and_login(client, "biz@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        "/api/v1/companies",
        headers=headers,
        json={"name": "Акме ЕООД", "eik": "123456789", "is_vat_registered": True},
    )
    assert r.status_code == 201, r.text
    company = r.json()
    assert company["role"] == "OWNER"
    assert company["base_currency"] == "EUR"
    assert company["country"] == "BG"
    company_id = company["id"]

    r = client.get("/api/v1/companies", headers=headers)
    assert r.status_code == 200
    assert any(c["id"] == company_id for c in r.json())

    r = client.get(
        "/api/v1/companies/current",
        headers={**headers, "X-Company-Id": company_id},
    )
    assert r.status_code == 200
    assert r.json()["id"] == company_id


def test_company_missing_header(client):
    token = register_and_login(client, "noheader@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/v1/companies", headers=headers, json={"name": "NoHeader Ltd"})
    company_id = r.json()["id"]
    # без X-Company-Id → 400
    r = client.get("/api/v1/companies/current", headers=headers)
    assert r.status_code == 400
    assert company_id  # sanity


def test_tenant_isolation(client):
    token_a = register_and_login(client, "tenant-a@example.com")
    r = client.post(
        "/api/v1/companies",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "A Corp"},
    )
    company_id = r.json()["id"]

    token_b = register_and_login(client, "tenant-b@example.com")
    r = client.get(
        "/api/v1/companies/current",
        headers={"Authorization": f"Bearer {token_b}", "X-Company-Id": company_id},
    )
    assert r.status_code == 403
