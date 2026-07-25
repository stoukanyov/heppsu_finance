"""Тестове за въвеждането на реален клиент: настройка, начални салда, миграция, здраве."""
import io

from tests.conftest import register_and_login

ACC = "/api/v1/accounting"
ON = "/api/v1/onboarding"


def _setup(client, email, **company):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    payload = {"name": "Акме ЕООД", **company}
    cid = client.post("/api/v1/companies", headers=auth, json=payload).json()["id"]
    return {**auth, "X-Company-Id": cid}


def _full_setup(client, email, **company):
    h = _setup(client, email, **company)
    acc = {a["code"]: a["id"] for a in client.post(f"{ACC}/chart/seed", headers=h).json()}
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    return h, acc


# ------------------------------------------------------------------ настройка
def test_status_lists_missing_steps_for_a_bare_company(client):
    h = _setup(client, "onb1@example.com")
    body = client.get(f"{ON}/status", headers=h).json()

    assert body["ready"] is False
    steps = {s["key"]: s for s in body["steps"]}
    assert steps["chart_of_accounts"]["done"] is False
    assert steps["fiscal_year"]["done"] is False
    assert "ЕИК" in steps["company_details"]["detail"]


def test_status_becomes_ready_after_required_steps(client):
    h, _ = _full_setup(client, "onb2@example.com",
                       eik="203123456", address_line="ул. Тест 1", address_city="София")
    body = client.get(f"{ON}/status", headers=h).json()
    assert body["ready"] is True, [s for s in body["steps"] if s["required"] and not s["done"]]


def test_vat_codes_required_only_for_vat_registered(client):
    h, _ = _full_setup(client, "onb3@example.com", eik="203123456",
                       address_line="ул. Тест 1", address_city="София")
    steps = {s["key"]: s for s in client.get(f"{ON}/status", headers=h).json()["steps"]}
    assert steps["vat_codes"]["required"] is False
    assert steps["vat_codes"]["done"] is True      # неприложимо = не блокира


# ------------------------------------------------------------------ начални салда
def test_opening_balances_preview_detects_imbalance(client):
    h, _ = _full_setup(client, "onb4@example.com")
    r = client.post(f"{ON}/opening-balances/preview", headers=h, json={"rows": [
        {"account_code": "501", "debit": "1000.00"},
        {"account_code": "401", "credit": "700.00"},
    ]})
    body = r.json()
    assert body["balanced"] is False
    assert body["difference"] == "300.00"
    assert body["can_post"] is False
    assert any("не балансират" in p for p in body["problems"])


def test_opening_balances_preview_accepts_balanced_rows(client):
    h, _ = _full_setup(client, "onb5@example.com")
    body = client.post(f"{ON}/opening-balances/preview", headers=h, json={"rows": [
        {"account_code": "501", "debit": "1000.00"},
        {"account_code": "401", "credit": "1000.00"},
    ]}).json()
    assert body["balanced"] is True
    assert body["can_post"] is True
    assert {r["code"] for r in body["rows"]} == {"501", "401"}


def test_unknown_account_is_reported(client):
    h, _ = _full_setup(client, "onb6@example.com")
    body = client.post(f"{ON}/opening-balances/preview", headers=h, json={"rows": [
        {"account_code": "9999", "debit": "10.00"},
    ]}).json()
    assert any("не съществува" in p for p in body["problems"])
    assert body["can_post"] is False


def test_account_with_both_sides_is_rejected(client):
    h, _ = _full_setup(client, "onb7@example.com")
    body = client.post(f"{ON}/opening-balances/preview", headers=h, json={"rows": [
        {"account_code": "501", "debit": "10.00", "credit": "5.00"},
    ]}).json()
    assert any("едновременно дебитно и кредитно" in p for p in body["problems"])


def test_posting_opening_balances_creates_a_posted_entry(client):
    h, _ = _full_setup(client, "onb8@example.com")
    r = client.post(f"{ON}/opening-balances", headers=h, json={
        "on_date": "2026-01-01",
        "rows": [{"account_code": "501", "debit": "1000.00"},
                 {"account_code": "401", "credit": "1000.00"}]})
    assert r.status_code == 200, r.text
    entry_id = r.json()["id"]

    entry = client.get(f"{ACC}/journal-entries/{entry_id}", headers=h).json()
    assert entry["status"] == "POSTED"
    assert entry["journal"] == "OPENING"
    assert sum(float(x["debit"]) for x in entry["lines"]) == 1000.0

    steps = {s["key"]: s for s in client.get(f"{ON}/status", headers=h).json()["steps"]}
    assert steps["opening_balances"]["done"] is True


def test_second_opening_balances_are_refused(client):
    h, _ = _full_setup(client, "onb9@example.com")
    rows = [{"account_code": "501", "debit": "10.00"}, {"account_code": "401", "credit": "10.00"}]
    assert client.post(f"{ON}/opening-balances", headers=h, json={"rows": rows}).status_code == 200
    r = client.post(f"{ON}/opening-balances", headers=h, json={"rows": rows})
    assert r.status_code == 409
    assert "Вече има осчетоводени начални салда" in r.json()["detail"]


def test_unbalanced_opening_balances_cannot_be_posted(client):
    h, _ = _full_setup(client, "onb10@example.com")
    r = client.post(f"{ON}/opening-balances", headers=h, json={"rows": [
        {"account_code": "501", "debit": "10.00"}, {"account_code": "401", "credit": "7.00"}]})
    assert r.status_code == 422


def test_opening_balances_from_csv(client):
    h, _ = _full_setup(client, "onb11@example.com")
    csv_text = "Сметка;Дебит;Кредит\r\n501;1 234,56;\r\n401;;1 234,56\r\n"
    r = client.post(f"{ON}/opening-balances/parse-csv", headers=h,
                    files={"file": ("ob.csv", io.BytesIO(csv_text.encode("cp1251")), "text/csv")},
                    data={"delimiter": ";", "decimal_comma": "true"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["balanced"] is True
    assert body["total_debit"] == "1234.56"


def test_csv_without_recognisable_columns_is_reported(client):
    h, _ = _full_setup(client, "onb12@example.com")
    r = client.post(f"{ON}/opening-balances/parse-csv", headers=h,
                    files={"file": ("x.csv", io.BytesIO(b"a;b;c\r\n1;2;3\r\n"), "text/csv")},
                    data={"delimiter": ";"})
    assert r.status_code == 422
    assert "колона за сметка" in r.json()["detail"]


# ------------------------------------------------------------------ миграция
def test_counterparty_import(client):
    h, _ = _full_setup(client, "onb13@example.com")
    csv_text = ("Име;ЕИК;ДДС;Адрес\r\n"
                "Първи Клиент ООД;111222333;BG111222333;София\r\n"
                "Втори Доставчик ЕООД;444555666;;Пловдив\r\n")
    r = client.post(f"{ON}/counterparties/import-csv", headers=h,
                    files={"file": ("cp.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")},
                    data={"name_column": "Име", "eik_column": "ЕИК",
                          "vat_column": "ДДС", "address_column": "Адрес", "delimiter": ";"})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 2

    names = {c["name"] for c in client.get("/api/v1/counterparties", headers=h).json()}
    assert "Първи Клиент ООД" in names


def test_counterparty_import_skips_duplicates_without_overwriting(client):
    h, _ = _full_setup(client, "onb14@example.com")
    client.post("/api/v1/counterparties", headers=h,
                json={"name": "Оригинално име ООД", "type": "CUSTOMER", "eik": "111222333"})

    csv_text = "Име;ЕИК\r\nПроменено име ООД;111222333\r\nНов Клиент ООД;999888777\r\n"
    body = client.post(f"{ON}/counterparties/import-csv", headers=h,
                       files={"file": ("cp.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")},
                       data={"name_column": "Име", "eik_column": "ЕИК", "delimiter": ";"}).json()
    assert body["created"] == 1
    assert body["skipped"] == 1

    names = {c["name"] for c in client.get("/api/v1/counterparties", headers=h).json()}
    assert "Оригинално име ООД" in names        # не е презаписан
    assert "Променено име ООД" not in names


def test_duplicate_inside_the_same_file_is_skipped(client):
    h, _ = _full_setup(client, "onb15@example.com")
    csv_text = "Име;ЕИК\r\nА ООД;111222333\r\nБ ООД;111222333\r\n"
    body = client.post(f"{ON}/counterparties/import-csv", headers=h,
                       files={"file": ("cp.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")},
                       data={"name_column": "Име", "eik_column": "ЕИК", "delimiter": ";"}).json()
    assert body["created"] == 1
    assert body["skipped"] == 1


def test_missing_name_column_is_reported(client):
    h, _ = _full_setup(client, "onb16@example.com")
    r = client.post(f"{ON}/counterparties/import-csv", headers=h,
                    files={"file": ("cp.csv", io.BytesIO(b"a;b\r\n1;2\r\n"), "text/csv")},
                    data={"name_column": "Име", "delimiter": ";"})
    assert r.status_code == 422


# ------------------------------------------------------------------ здраве
def test_health_flags_missing_company_details(client):
    h, _ = _full_setup(client, "onb17@example.com")
    body = client.get(f"{ON}/health", headers=h).json()
    assert body["healthy"] is False
    codes = {i["code"] for i in body["issues"]}
    assert "COMPANY_DETAILS" in codes


def test_health_is_clean_for_a_complete_company(client):
    h, _ = _full_setup(client, "onb18@example.com", eik="203123456",
                       address_line="ул. Тест 1", address_city="София")
    body = client.get(f"{ON}/health", headers=h).json()
    assert body["healthy"] is True
    assert body["errors"] == 0


def test_health_warns_about_drafts(client):
    h, acc = _full_setup(client, "onb19@example.com", eik="203123456",
                         address_line="ул. Тест 1", address_city="София")
    client.post(f"{ACC}/journal-entries", headers=h, json={
        "document_date": "2026-03-10", "journal": "GENERAL", "description": "Чернова",
        "lines": [{"account_id": acc["501"], "debit": "10.00", "credit": "0.00"},
                  {"account_id": acc["411"], "debit": "0.00", "credit": "10.00"}]})

    body = client.get(f"{ON}/health", headers=h).json()
    draft = next(i for i in body["issues"] if i["code"] == "DRAFT_ENTRIES")
    assert draft["count"] == 1
    assert draft["level"] == "WARNING"
    assert body["healthy"] is True      # предупреждение не значи нездраво


def test_health_warns_about_counterparties_without_identifier(client):
    h, _ = _full_setup(client, "onb20@example.com", eik="203123456",
                       address_line="ул. Тест 1", address_city="София")
    client.post("/api/v1/counterparties", headers=h, json={"name": "Без ЕИК ООД", "type": "CUSTOMER"})

    body = client.get(f"{ON}/health", headers=h).json()
    issue = next(i for i in body["issues"] if i["code"] == "COUNTERPARTIES_NO_ID")
    assert issue["count"] == 1
