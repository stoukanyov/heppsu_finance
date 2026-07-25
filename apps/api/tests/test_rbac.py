"""Тестове за гъвкавия RBAC модел и администраторския модул."""
from tests.conftest import register_and_login

RBAC = "/api/v1/rbac"
DOC = "/api/v1/documents"
MEM = "/api/v1/members"


def _setup(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    cid = client.post("/api/v1/companies", headers=auth, json={"name": "Хепсу ЕООД"}).json()["id"]
    h = {**auth, "X-Company-Id": cid}
    roles = client.post(f"{RBAC}/roles/seed", headers=h)
    assert roles.status_code == 201, roles.text
    return h, {r["code"]: r for r in roles.json()}


def _add_member(client, owner_h, email: str, role_id: str | None = None):
    """Регистрира втори потребител и го добавя в компанията на собственика."""
    token = register_and_login(client, email)
    r = client.post(MEM, headers=owner_h, json={"email": email, "role": "ACCOUNTANT"})
    assert r.status_code == 201, r.text
    membership_id = r.json()["id"]
    if role_id:
        assert client.post(
            f"{RBAC}/members/{membership_id}/role", headers=owner_h, json={"role_id": role_id}
        ).status_code == 200
    cid = owner_h["X-Company-Id"]
    return {"Authorization": f"Bearer {token}", "X-Company-Id": cid}, membership_id


# ============================ Каталог и предефинирани роли ============================
def test_permission_catalog_grouped(client):
    h, _ = _setup(client, "rbac1@example.com")
    groups = client.get(f"{RBAC}/permissions", headers=h).json()
    names = {g["group"] for g in groups}
    assert {"Счетоводство", "Данъци", "Администрация"} <= names
    codes = {p["code"] for g in groups for p in g["permissions"]}
    assert "vat.close_period" in codes and "payments.approve" in codes
    # всяко право има човешко описание
    assert all(p["label"] for g in groups for p in g["permissions"])


def test_seeded_roles_cover_expected_positions(client):
    h, roles = _setup(client, "rbac2@example.com")
    assert {"MANAGER", "CHIEF_ACCOUNTANT", "ACCOUNTANT", "CFO",
            "EXTERNAL_ACCOUNTANT", "EMPLOYEE", "APPROVER", "AUDITOR",
            "TAX_CONSULTANT", "READ_ONLY"} <= set(roles)
    # Управител = пълни права + администратор
    manager = roles["MANAGER"]
    assert manager["permissions"] == ["*"]
    assert manager["is_admin"] is True and manager["can_use_mobile"] is True
    # Счетоводителят няма право да приключва периоди
    acc = roles["ACCOUNTANT"]
    assert "accounting.post_entry" in acc["permissions"]
    assert "accounting.close_period" not in acc["permissions"]
    assert "payments.approve" not in acc["permissions"]
    # Одиторът е само за четене и БЕЗ мобилен достъп
    auditor = roles["AUDITOR"]
    assert auditor["can_use_mobile"] is False
    assert not any(p.endswith((".manage", ".create", ".post_entry")) for p in auditor["permissions"])


def test_seed_is_idempotent(client):
    h, roles = _setup(client, "rbac3@example.com")
    again = client.post(f"{RBAC}/roles/seed", headers=h).json()
    assert len(again) == len(roles)


def test_my_access_for_owner(client):
    h, _ = _setup(client, "rbac4@example.com")
    me = client.get(f"{RBAC}/my-access", headers=h).json()
    assert me["is_admin"] is True
    assert me["can_use_mobile"] is True
    assert "vat.close_period" in me["permissions"]   # `*` се разгъва до всички права


# ============================ Собствени роли ============================
def test_create_custom_role(client):
    h, _ = _setup(client, "rbac5@example.com")
    r = client.post(f"{RBAC}/roles", headers=h, json={
        "code": "CASHIER", "name": "Касиер",
        "description": "Работи само с каса и документи",
        "permissions": ["banking.view", "documents.view", "documents.upload"],
        "can_use_mobile": True,
    })
    assert r.status_code == 201, r.text
    role = r.json()
    assert role["is_system"] is False and role["can_use_mobile"] is True


def test_unknown_permission_rejected(client):
    h, _ = _setup(client, "rbac6@example.com")
    r = client.post(f"{RBAC}/roles", headers=h, json={
        "code": "BAD", "name": "Невалидна", "permissions": ["magic.do_everything"],
    })
    assert r.status_code == 422
    assert "Непознати права" in r.json()["detail"]


def test_duplicate_role_code_rejected(client):
    h, _ = _setup(client, "rbac7@example.com")
    body = {"code": "X1", "name": "Роля X", "permissions": ["reports.view"]}
    assert client.post(f"{RBAC}/roles", headers=h, json=body).status_code == 201
    assert client.post(f"{RBAC}/roles", headers=h, json=body).status_code == 409


def test_system_role_permissions_are_protected(client):
    """Системна роля не се преправя пряко — клонира се."""
    h, roles = _setup(client, "rbac8@example.com")
    rid = roles["ACCOUNTANT"]["id"]
    r = client.patch(f"{RBAC}/roles/{rid}", headers=h, json={"permissions": ["*"]})
    assert r.status_code == 409
    assert "клонирай" in r.json()["detail"]

    # клонирането дава редактируемо копие
    cl = client.post(f"{RBAC}/roles/{rid}/clone", headers=h,
                     json={"code": "ACC_PLUS", "name": "Счетоводител+"}).json()
    assert cl["is_system"] is False
    upd = client.patch(f"{RBAC}/roles/{cl['id']}", headers=h,
                       json={"permissions": ["accounting.view", "accounting.close_period"]})
    assert upd.status_code == 200
    assert "accounting.close_period" in upd.json()["permissions"]


def test_system_role_mobile_flag_is_editable(client):
    """Мобилният достъп е решение на администратора — сменя се и за системна роля."""
    h, roles = _setup(client, "rbac9@example.com")
    rid = roles["AUDITOR"]["id"]
    r = client.patch(f"{RBAC}/roles/{rid}", headers=h, json={"can_use_mobile": True})
    assert r.status_code == 200 and r.json()["can_use_mobile"] is True


def test_system_role_cannot_be_deleted(client):
    h, roles = _setup(client, "rbac10@example.com")
    r = client.delete(f"{RBAC}/roles/{roles['MANAGER']['id']}", headers=h)
    assert r.status_code == 409
    assert "не се изтрива" in r.json()["detail"]


def test_role_in_use_cannot_be_deleted(client):
    h, roles = _setup(client, "rbac11@example.com")
    custom = client.post(f"{RBAC}/roles", headers=h, json={
        "code": "TEMP", "name": "Временна", "permissions": ["reports.view"]}).json()
    _member_h, _mid = _add_member(client, h, "rbac11-m@example.com", role_id=custom["id"])
    r = client.delete(f"{RBAC}/roles/{custom['id']}", headers=h)
    assert r.status_code == 409
    assert "присвоена" in r.json()["detail"]


# ============================ Прилагане на правата ============================
def test_permissions_enforced_for_limited_role(client):
    """Роля без право „team.view" не вижда ролите."""
    h, roles = _setup(client, "rbac12@example.com")
    member_h, _ = _add_member(client, h, "rbac12-m@example.com", role_id=roles["EMPLOYEE"]["id"])
    me = client.get(f"{RBAC}/my-access", headers=member_h).json()
    assert me["role_code"] == "EMPLOYEE"
    assert me["is_admin"] is False
    r = client.get(f"{RBAC}/roles", headers=member_h)
    assert r.status_code == 403
    assert r.json()["code"] == "PERMISSION_DENIED"
    assert r.json()["contact_admin"] is True


def test_non_admin_cannot_manage_roles(client):
    h, roles = _setup(client, "rbac13@example.com")
    member_h, _ = _add_member(client, h, "rbac13-m@example.com", role_id=roles["ACCOUNTANT"]["id"])
    r = client.post(f"{RBAC}/roles", headers=member_h, json={
        "code": "HACK", "name": "Хак", "permissions": ["*"]})
    assert r.status_code == 403
    assert r.json()["code"] == "ADMIN_REQUIRED"


def test_last_admin_cannot_be_downgraded(client):
    h, roles = _setup(client, "rbac14@example.com")
    my = client.get(MEM, headers=h).json()
    own = next(m for m in my if m["email"] == "rbac14@example.com")
    r = client.post(f"{RBAC}/members/{own['id']}/role", headers=h,
                    json={"role_id": roles["READ_ONLY"]["id"]})
    assert r.status_code == 409
    assert "поне един администратор" in r.json()["detail"]


# ============================ Мобилен достъп ============================
def test_mobile_scan_allowed_for_employee(client):
    h, roles = _setup(client, "rbac15@example.com")
    member_h, _ = _add_member(client, h, "rbac15-m@example.com", role_id=roles["EMPLOYEE"]["id"])
    r = client.post(f"{DOC}/scan", headers=member_h,
                    files={"file": ("s.jpg", b"\xff\xd8\xff\xe0x", "image/jpeg")})
    assert r.status_code == 201, r.text


def test_mobile_scan_denied_with_clear_message(client):
    """Роля без мобилен достъп получава ясно съобщение да се обърне към администратор."""
    h, roles = _setup(client, "rbac16@example.com")
    member_h, _ = _add_member(client, h, "rbac16-m@example.com", role_id=roles["AUDITOR"]["id"])
    assert client.get(f"{RBAC}/my-access", headers=member_h).json()["can_use_mobile"] is False

    r = client.post(f"{DOC}/scan", headers=member_h,
                    files={"file": ("s.jpg", b"\xff\xd8\xff\xe0x", "image/jpeg")})
    assert r.status_code == 403
    body = r.json()
    assert body["code"] == "MOBILE_ACCESS_DENIED"
    assert body["contact_admin"] is True
    # `detail` е четим низ — показва се правилно и в уеб, и в мобилното
    assert isinstance(body["detail"], str)
    assert "мобилното приложение" in body["detail"]
    assert "администратор" in body["detail"]


def test_mobile_access_can_be_granted_by_admin(client):
    """Администраторът включва мобилния достъп и сканирането минава."""
    h, roles = _setup(client, "rbac17@example.com")
    member_h, _ = _add_member(client, h, "rbac17-m@example.com", role_id=roles["AUDITOR"]["id"])
    assert client.post(f"{DOC}/scan", headers=member_h,
                       files={"file": ("s.jpg", b"\xff\xd8\xff\xe0x", "image/jpeg")}).status_code == 403

    client.patch(f"{RBAC}/roles/{roles['AUDITOR']['id']}", headers=h,
                 json={"can_use_mobile": True, "permissions": None})
    # одиторът все още няма право да качва документи
    r = client.post(f"{DOC}/scan", headers=member_h,
                    files={"file": ("s2.jpg", b"\xff\xd8\xff\xe0y", "image/jpeg")})
    assert r.status_code == 403
    assert r.json()["required_permission"] == "documents.upload"


def test_inactive_role_blocks_everything(client):
    h, roles = _setup(client, "rbac18@example.com")
    custom = client.post(f"{RBAC}/roles", headers=h, json={
        "code": "TMP2", "name": "Временна", "permissions": ["documents.upload"],
        "can_use_mobile": True}).json()
    member_h, _ = _add_member(client, h, "rbac18-m@example.com", role_id=custom["id"])
    assert client.post(f"{DOC}/scan", headers=member_h,
                       files={"file": ("a.jpg", b"\xff\xd8\xff\xe0a", "image/jpeg")}).status_code == 201

    client.patch(f"{RBAC}/roles/{custom['id']}", headers=h, json={"is_active": False})
    r = client.post(f"{DOC}/scan", headers=member_h,
                    files={"file": ("b.jpg", b"\xff\xd8\xff\xe0b", "image/jpeg")})
    assert r.status_code == 403


def test_roles_tenant_isolated(client):
    h_a, _ = _setup(client, "rbac19a@example.com")
    client.post(f"{RBAC}/roles", headers=h_a, json={
        "code": "ONLY_A", "name": "Само в A", "permissions": ["reports.view"]})
    h_b, _ = _setup(client, "rbac19b@example.com")
    codes = {r["code"] for r in client.get(f"{RBAC}/roles", headers=h_b).json()}
    assert "ONLY_A" not in codes
