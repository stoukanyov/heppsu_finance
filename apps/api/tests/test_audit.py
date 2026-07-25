from tests.conftest import register_and_login

ACC = "/api/v1/accounting"
AUDIT = "/api/v1/audit"


def _setup(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post("/api/v1/companies", headers=auth, json={"name": "Акме ЕООД"}).json()["id"]
    h = {**auth, "X-Company-Id": company_id}
    return h, auth, company_id


def test_mutating_action_is_logged(client):
    h, auth, company_id = _setup(client, "audit1@example.com")
    me = client.get("/api/v1/auth/me", headers=auth).json()

    client.post(f"{ACC}/chart/seed", headers=h)  # променящо действие
    logs = client.get(AUDIT, headers=h).json()

    seed = next((x for x in logs if "chart/seed" in x["path"]), None)
    assert seed is not None
    assert seed["method"] == "POST"
    assert seed["status_code"] == 201
    assert seed["user_id"] == me["id"]
    assert seed["company_id"] == company_id


def test_reads_not_logged(client):
    h, _, _ = _setup(client, "audit2@example.com")
    client.get(f"{ACC}/accounts", headers=h)  # GET — не се логва
    logs = client.get(AUDIT, headers=h).json()
    assert not any(x["method"] == "GET" for x in logs)


def test_filter_by_method(client):
    h, _, _ = _setup(client, "audit3@example.com")
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    logs = client.get(f"{AUDIT}?method=POST", headers=h).json()
    assert logs and all(x["method"] == "POST" for x in logs)


def test_tenant_isolation(client):
    h_a, _, _ = _setup(client, "audit-a@example.com")
    client.post(f"{ACC}/chart/seed", headers=h_a)
    h_b, _, _ = _setup(client, "audit-b@example.com")
    logs_b = client.get(AUDIT, headers=h_b).json()
    assert not any("chart/seed" in x["path"] for x in logs_b)


def test_no_delete_on_audit(client):
    h, _, _ = _setup(client, "audit4@example.com")
    r = client.delete(f"{AUDIT}/00000000-0000-0000-0000-000000000000", headers=h)
    assert r.status_code in (404, 405)
