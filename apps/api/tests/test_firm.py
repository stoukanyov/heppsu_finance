"""Тестове на таблото за счетоводна кантора (много клиенти наведнъж)."""
from tests.conftest import register_and_login

FIRM = "/api/v1/firm"
ACC = "/api/v1/accounting"


def _accountant(client, email="firm@example.com", companies=("Клиент 1", "Клиент 2")):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    ids = []
    for name in companies:
        ids.append(client.post("/api/v1/companies", headers=auth, json={"name": name}).json()["id"])
    return auth, ids


def test_clients_lists_only_own_companies(client):
    auth_a, ids_a = _accountant(client, "firm1@example.com", ("Алфа ЕООД",))
    auth_b, ids_b = _accountant(client, "firm2@example.com", ("Бета ЕООД",))

    names_a = {c["name"] for c in client.get(f"{FIRM}/clients", headers=auth_a).json()}
    names_b = {c["name"] for c in client.get(f"{FIRM}/clients", headers=auth_b).json()}
    assert names_a == {"Алфа ЕООД"}
    assert names_b == {"Бета ЕООД"}


def test_overview_counts_pending_work(client):
    auth, ids = _accountant(client, "firm3@example.com", ("Гама ЕООД",))
    cid = ids[0]
    h = {**auth, "X-Company-Id": cid}
    acc = {a["code"]: a["id"] for a in client.post(f"{ACC}/chart/seed", headers=h).json()}
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})

    # Черновата се брои като чакаща работа.
    client.post(f"{ACC}/journal-entries", headers=h, json={
        "document_date": "2026-03-10", "journal": "GENERAL", "description": "Чернова",
        "lines": [{"account_id": acc["501"], "debit": "10.00", "credit": "0.00"},
                  {"account_id": acc["411"], "debit": "0.00", "credit": "10.00"}]})

    row = next(c for c in client.get(f"{FIRM}/clients", headers=auth).json() if c["company_id"] == cid)
    assert row["totals"]["draft_entries"] == 1
    assert row["needs_attention"] is True


def test_posted_entries_are_not_counted_as_pending(client):
    auth, ids = _accountant(client, "firm4@example.com", ("Делта ЕООД",))
    cid = ids[0]
    h = {**auth, "X-Company-Id": cid}
    acc = {a["code"]: a["id"] for a in client.post(f"{ACC}/chart/seed", headers=h).json()}
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    e = client.post(f"{ACC}/journal-entries", headers=h, json={
        "document_date": "2026-03-10", "journal": "GENERAL", "description": "Осчетоводена",
        "lines": [{"account_id": acc["501"], "debit": "10.00", "credit": "0.00"},
                  {"account_id": acc["411"], "debit": "0.00", "credit": "10.00"}]}).json()
    client.post(f"{ACC}/journal-entries/{e['id']}/post", headers=h)

    row = next(c for c in client.get(f"{FIRM}/clients", headers=auth).json() if c["company_id"] == cid)
    assert row["totals"]["draft_entries"] == 0


def test_next_deadline_is_present_for_vat_registered_client(client):
    token = register_and_login(client, "firm5@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    cid = client.post("/api/v1/companies", headers=auth,
                      json={"name": "Ипсилон ЕООД", "is_vat_registered": True}).json()["id"]

    rows = client.get(f"{FIRM}/clients", headers=auth, params={"reference_date": "2026-03-01"}).json()
    row = next(c for c in rows if c["company_id"] == cid)
    assert row["next_deadline"] is not None
    assert row["next_deadline"]["days_remaining"] >= 0
    assert row["next_deadline"]["authority"]


# ------------------------------------------------------------------ задачи
def test_task_lifecycle(client):
    auth, ids = _accountant(client, "firm6@example.com", ("Зета ЕООД",))
    cid = ids[0]

    r = client.post(f"{FIRM}/tasks", headers=auth, json={
        "company_id": cid, "title": "Обработи банковото извлечение", "due_date": "2026-04-10"})
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["status"] == "OPEN"
    assert task["completed_at"] is None

    r = client.patch(f"{FIRM}/tasks/{task['id']}", headers=auth, json={"status": "DONE"})
    assert r.status_code == 200
    assert r.json()["status"] == "DONE"
    assert r.json()["completed_at"] is not None

    # Връщането в работа изчиства датата на приключване.
    r = client.patch(f"{FIRM}/tasks/{task['id']}", headers=auth, json={"status": "IN_PROGRESS"})
    assert r.json()["completed_at"] is None

    assert client.delete(f"{FIRM}/tasks/{task['id']}", headers=auth).status_code == 204


def test_task_for_foreign_company_is_refused(client):
    auth_a, ids_a = _accountant(client, "firm7@example.com", ("Тета ЕООД",))
    auth_b, ids_b = _accountant(client, "firm8@example.com", ("Йота ЕООД",))

    r = client.post(f"{FIRM}/tasks", headers=auth_b,
                    json={"company_id": ids_a[0], "title": "Чужда задача"})
    assert r.status_code == 403


def test_tasks_of_other_accountants_are_not_listed(client):
    auth_a, ids_a = _accountant(client, "firm9@example.com", ("Капа ЕООД",))
    client.post(f"{FIRM}/tasks", headers=auth_a, json={"company_id": ids_a[0], "title": "Моя"})

    auth_b, _ = _accountant(client, "firm10@example.com", ("Ламбда ЕООД",))
    assert client.get(f"{FIRM}/tasks", headers=auth_b).json() == []


def test_assignee_must_have_access_to_the_company(client):
    auth_a, ids_a = _accountant(client, "firm11@example.com", ("Мю ЕООД",))
    token_b = register_and_login(client, "firm12@example.com")
    me_b = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_b}"}).json()

    r = client.post(f"{FIRM}/tasks", headers=auth_a, json={
        "company_id": ids_a[0], "title": "Възложена на чужд човек", "assignee_id": me_b["id"]})
    assert r.status_code == 422
    assert "няма достъп" in r.json()["detail"]


def test_generate_tasks_from_deadlines_is_idempotent(client):
    token = register_and_login(client, "firm13@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    cid = client.post("/api/v1/companies", headers=auth,
                      json={"name": "Ню ЕООД", "is_vat_registered": True}).json()["id"]

    first = client.post(f"{FIRM}/tasks/from-deadlines", headers=auth,
                        json={"company_id": cid, "days_ahead": 60}).json()
    assert len(first) > 0

    second = client.post(f"{FIRM}/tasks/from-deadlines", headers=auth,
                         json={"company_id": cid, "days_ahead": 60}).json()
    assert second == []          # нищо не се дублира

    total = client.get(f"{FIRM}/tasks", headers=auth, params={"company_id": cid}).json()
    assert len(total) == len(first)


def test_duplicate_deadline_task_is_refused(client):
    auth, ids = _accountant(client, "firm14@example.com", ("Кси ЕООД",))
    body = {"company_id": ids[0], "title": "ДДС", "deadline_key": "vat-return:2026-03"}
    assert client.post(f"{FIRM}/tasks", headers=auth, json=body).status_code == 201
    r = client.post(f"{FIRM}/tasks", headers=auth, json=body)
    assert r.status_code == 409


def test_overdue_tasks_are_counted_and_client_flagged(client):
    auth, ids = _accountant(client, "firm15@example.com", ("Омикрон ЕООД",))
    cid = ids[0]
    client.post(f"{FIRM}/tasks", headers=auth,
                json={"company_id": cid, "title": "Просрочена", "due_date": "2020-01-01"})

    row = next(c for c in client.get(f"{FIRM}/clients", headers=auth).json() if c["company_id"] == cid)
    assert row["totals"]["overdue_tasks"] == 1
    assert row["totals"]["open_tasks"] == 1
    assert row["needs_attention"] is True


def test_only_open_filter(client):
    auth, ids = _accountant(client, "firm16@example.com", ("Пи ЕООД",))
    cid = ids[0]
    t1 = client.post(f"{FIRM}/tasks", headers=auth, json={"company_id": cid, "title": "Отворена"}).json()
    t2 = client.post(f"{FIRM}/tasks", headers=auth, json={"company_id": cid, "title": "Готова"}).json()
    client.patch(f"{FIRM}/tasks/{t2['id']}", headers=auth, json={"status": "DONE"})

    open_ids = {t["id"] for t in client.get(f"{FIRM}/tasks", headers=auth, params={"only_open": True}).json()}
    assert open_ids == {t1["id"]}


def test_clients_needing_attention_come_first(client):
    token = register_and_login(client, "firm17@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    calm = client.post("/api/v1/companies", headers=auth, json={"name": "Спокоен ЕООД"}).json()["id"]
    busy = client.post("/api/v1/companies", headers=auth, json={"name": "Затрупан ЕООД"}).json()["id"]
    client.post(f"{FIRM}/tasks", headers=auth,
                json={"company_id": busy, "title": "Просрочена", "due_date": "2020-01-01"})

    rows = client.get(f"{FIRM}/clients", headers=auth).json()
    order = [c["company_id"] for c in rows]
    assert order.index(busy) < order.index(calm)


# ------------------------------------------------------------------ групови действия
def test_vat_readiness_lists_blockers(client):
    token = register_and_login(client, "firm18@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    vat_ok = client.post("/api/v1/companies", headers=auth,
                         json={"name": "С ДДС ЕООД", "is_vat_registered": True}).json()["id"]
    no_vat = client.post("/api/v1/companies", headers=auth,
                         json={"name": "Без ДДС ЕООД"}).json()["id"]
    for cid in (vat_ok, no_vat):
        client.post(f"{ACC}/fiscal-years", headers={**auth, "X-Company-Id": cid}, json={"year": 2026})

    r = client.get(f"{FIRM}/bulk/vat-readiness", headers=auth, params={"period_code": "2026-03"})
    assert r.status_code == 200, r.text
    body = r.json()
    rows = {c["company_id"]: c for c in body["clients"]}
    assert rows[vat_ok]["ready"] is True
    assert rows[no_vat]["ready"] is False
    assert any("не е регистрирано" in b for b in rows[no_vat]["blockers"])
    assert body["ready"] == 1


def test_vat_readiness_reports_missing_period(client):
    token = register_and_login(client, "firm19@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    client.post("/api/v1/companies", headers=auth,
                json={"name": "Без период ЕООД", "is_vat_registered": True})

    body = client.get(f"{FIRM}/bulk/vat-readiness", headers=auth,
                      params={"period_code": "2026-03"}).json()
    assert body["clients"][0]["ready"] is False
    assert "Няма счетоводен период" in body["clients"][0]["blockers"][0]


def test_bulk_nap_packages_returns_zip_per_client(client):
    import io
    import zipfile

    token = register_and_login(client, "firm20@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    ids = []
    for name in ("Първи ЕООД", "Втори ЕООД"):
        cid = client.post("/api/v1/companies", headers=auth,
                          json={"name": name, "eik": f"20312345{len(ids)}",
                                "is_vat_registered": True}).json()["id"]
        client.post(f"{ACC}/fiscal-years", headers={**auth, "X-Company-Id": cid}, json={"year": 2026})
        ids.append(cid)

    r = client.post(f"{FIRM}/bulk/nap-packages", headers=auth,
                    json={"company_ids": ids, "period_code": "2026-03"})
    assert r.status_code == 200, r.text
    assert r.headers["X-Packages-Included"] == "2"
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        folders = {n.split("/")[0] for n in zf.namelist()}
        assert len(folders) == 2


def test_bulk_packages_skip_inaccessible_clients(client):
    token_a = register_and_login(client, "firm21@example.com")
    auth_a = {"Authorization": f"Bearer {token_a}"}
    foreign = client.post("/api/v1/companies", headers=auth_a, json={"name": "Чужд ЕООД"}).json()["id"]

    token_b = register_and_login(client, "firm22@example.com")
    auth_b = {"Authorization": f"Bearer {token_b}"}
    mine = client.post("/api/v1/companies", headers=auth_b,
                       json={"name": "Мой ЕООД", "eik": "203999888", "is_vat_registered": True}).json()["id"]
    client.post(f"{ACC}/fiscal-years", headers={**auth_b, "X-Company-Id": mine}, json={"year": 2026})

    r = client.post(f"{FIRM}/bulk/nap-packages", headers=auth_b,
                    json={"company_ids": [mine, foreign], "period_code": "2026-03"})
    assert r.status_code == 200
    assert r.headers["X-Packages-Included"] == "1"
    assert r.headers["X-Packages-Skipped"] == "1"


def test_deadline_soon_is_separate_from_backlog(client):
    """Наближаващ срок не бива да се брои за натрупана работа — иначе маркерът светва навсякъде."""
    token = register_and_login(client, "firm23@example.com")
    auth = {"Authorization": f"Bearer {token}"}
    cid = client.post("/api/v1/companies", headers=auth,
                      json={"name": "Чист ЕООД", "is_vat_registered": True}).json()["id"]

    # 13-и: срокът за ДДС (14-о число) е след един ден, но нищо не е изостанало.
    rows = client.get(f"{FIRM}/clients", headers=auth, params={"reference_date": "2026-03-13"}).json()
    row = next(c for c in rows if c["company_id"] == cid)
    assert row["deadline_soon"] is True
    assert row["needs_attention"] is False
