from tests.conftest import register_and_login

CO = "/api/v1/companies"
M = "/api/v1/members"


def _owner(client, email="owner@example.com"):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post(CO, headers=auth, json={"name": "Акме ЕООД"}).json()["id"]
    return {**auth, "X-Company-Id": company_id}, company_id


def _member_id(client, h, email):
    members = client.get(M, headers=h).json()
    return next(m["id"] for m in members if m["email"] == email)


def test_owner_is_listed(client):
    h, _ = _owner(client, "m-owner1@example.com")
    members = client.get(M, headers=h).json()
    assert len(members) == 1
    assert members[0]["email"] == "m-owner1@example.com" and members[0]["role"] == "OWNER"


def test_add_member_and_access(client):
    h, company_id = _owner(client, "m-owner2@example.com")
    token_b = register_and_login(client, "m-acc@example.com")

    r = client.post(M, headers=h, json={"email": "m-acc@example.com", "role": "ACCOUNTANT"})
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "ACCOUNTANT"
    assert len(client.get(M, headers=h).json()) == 2

    # B вече има достъп до компанията
    h_b = {"Authorization": f"Bearer {token_b}", "X-Company-Id": company_id}
    cur = client.get(f"{CO}/current", headers=h_b)
    assert cur.status_code == 200 and cur.json()["role"] == "ACCOUNTANT"


def test_non_manager_cannot_add(client):
    h, company_id = _owner(client, "m-owner3@example.com")
    token_b = register_and_login(client, "m-acc3@example.com")
    client.post(M, headers=h, json={"email": "m-acc3@example.com", "role": "ACCOUNTANT"})
    h_b = {"Authorization": f"Bearer {token_b}", "X-Company-Id": company_id}
    register_and_login(client, "m-x@example.com")
    r = client.post(M, headers=h_b, json={"email": "m-x@example.com", "role": "ACCOUNTANT"})
    assert r.status_code == 403


def test_update_role(client):
    h, _ = _owner(client, "m-owner4@example.com")
    register_and_login(client, "m-acc4@example.com")
    client.post(M, headers=h, json={"email": "m-acc4@example.com", "role": "ACCOUNTANT"})
    mid = _member_id(client, h, "m-acc4@example.com")
    r = client.patch(f"{M}/{mid}", headers=h, json={"role": "CHIEF_ACCOUNTANT"})
    assert r.status_code == 200 and r.json()["role"] == "CHIEF_ACCOUNTANT"


def test_cannot_demote_last_owner(client):
    h, _ = _owner(client, "m-owner5@example.com")
    mid = _member_id(client, h, "m-owner5@example.com")
    r = client.patch(f"{M}/{mid}", headers=h, json={"role": "ACCOUNTANT"})
    assert r.status_code == 409


def test_remove_member_and_last_owner_guard(client):
    h, _ = _owner(client, "m-owner6@example.com")
    register_and_login(client, "m-acc6@example.com")
    client.post(M, headers=h, json={"email": "m-acc6@example.com", "role": "ACCOUNTANT"})
    bid = _member_id(client, h, "m-acc6@example.com")
    assert client.delete(f"{M}/{bid}", headers=h).status_code == 204
    assert len(client.get(M, headers=h).json()) == 1
    # последният собственик не може да бъде премахнат
    oid = _member_id(client, h, "m-owner6@example.com")
    assert client.delete(f"{M}/{oid}", headers=h).status_code == 409


def test_add_unknown_and_duplicate(client):
    h, _ = _owner(client, "m-owner7@example.com")
    assert client.post(M, headers=h, json={"email": "nobody@example.com", "role": "ACCOUNTANT"}).status_code == 404
    register_and_login(client, "m-acc7@example.com")
    client.post(M, headers=h, json={"email": "m-acc7@example.com", "role": "ACCOUNTANT"})
    dup = client.post(M, headers=h, json={"email": "m-acc7@example.com", "role": "AUDITOR"})
    assert dup.status_code == 409
