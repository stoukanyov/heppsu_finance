"""Интеграционни тестове на модул ТРЗ: параметри, договори, ведомост, осчетоводяване."""
from tests.conftest import register_and_login

ACC = "/api/v1/accounting"
PR = "/api/v1/payroll"


def _setup(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post("/api/v1/companies", headers=auth, json={"name": "Акме ЕООД"}).json()["id"]
    h = {**auth, "X-Company-Id": company_id}
    acc = {a["code"]: a for a in client.post(f"{ACC}/chart/seed", headers=h).json()}
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    return h, acc


def _rate_set_payload(acc, with_accounts: bool = True):
    """Набор с два фонда. Процентите са примерни — идват от потребителя, не от кода."""
    payload = {
        "name": "2026",
        "valid_from": "2026-01-01",
        "income_tax_percent": "10.00",
        "default_min_insurance_income": "0.00",
        "contributions": [
            {
                "code": "DOO",
                "name": "Държавно обществено осигуряване",
                "employee_percent": "10.00",
                "employer_percent": "12.00",
                "sort_order": 1,
            },
            {
                "code": "ZO",
                "name": "Здравно осигуряване",
                "employee_percent": "3.20",
                "employer_percent": "4.80",
                "sort_order": 2,
            },
        ],
    }
    if with_accounts:
        payload["gl_salary_expense_account_id"] = acc["604"]["id"]
        payload["gl_salary_payable_account_id"] = acc["421"]["id"]
        payload["gl_income_tax_account_id"] = acc["454"]["id"]
        for row in payload["contributions"]:
            row["gl_expense_account_id"] = acc["605"]["id"]
            row["gl_liability_account_id"] = acc["461"]["id"]
    return payload


def _employee_with_contract(client, h, national_id="8001010101", salary="2000.00", number="TD-1"):
    emp = client.post(
        f"{PR}/employees",
        headers=h,
        json={"first_name": "Иван", "last_name": "Петров", "national_id": national_id},
    ).json()
    contract = client.post(
        f"{PR}/contracts",
        headers=h,
        json={
            "employee_id": emp["id"],
            "number": number,
            "position": "Програмист",
            "start_date": "2026-01-01",
            "base_salary": salary,
        },
    ).json()
    return emp, contract


# ------------------------------------------------------------------ параметри
def test_rate_set_crud(client):
    h, acc = _setup(client, "pay1@example.com")

    r = client.post(f"{PR}/rate-sets", headers=h, json=_rate_set_payload(acc))
    assert r.status_code == 201, r.text
    rate_set = r.json()
    assert len(rate_set["contributions"]) == 2
    assert rate_set["contributions"][0]["code"] == "DOO"

    r = client.patch(
        f"{PR}/rate-sets/{rate_set['id']}", headers=h, json={"income_tax_percent": "12.00"}
    )
    assert r.status_code == 200
    assert float(r.json()["income_tax_percent"]) == 12.0
    # Фондовете остават непроменени, когато не са подадени.
    assert len(r.json()["contributions"]) == 2

    assert client.get(f"{PR}/rate-sets", headers=h).json()[0]["id"] == rate_set["id"]
    assert client.delete(f"{PR}/rate-sets/{rate_set['id']}", headers=h).status_code == 204


def test_duplicate_fund_codes_are_rejected(client):
    h, acc = _setup(client, "pay2@example.com")
    payload = _rate_set_payload(acc)
    payload["contributions"][1]["code"] = "DOO"
    r = client.post(f"{PR}/rate-sets", headers=h, json=payload)
    assert r.status_code == 422
    assert "уникални" in r.json()["detail"]


def test_rate_set_replaces_contributions_when_list_given(client):
    h, acc = _setup(client, "pay3@example.com")
    rate_set = client.post(f"{PR}/rate-sets", headers=h, json=_rate_set_payload(acc)).json()

    r = client.patch(
        f"{PR}/rate-sets/{rate_set['id']}",
        headers=h,
        json={"contributions": [{"code": "NEW", "name": "Нов фонд", "employee_percent": "1.00"}]},
    )
    assert r.status_code == 200
    assert [c["code"] for c in r.json()["contributions"]] == ["NEW"]


# ------------------------------------------------------------------ хора
def test_employee_and_contract(client):
    h, _ = _setup(client, "pay4@example.com")
    emp, contract = _employee_with_contract(client, h)

    assert emp["full_name"] == "Иван Петров"
    assert contract["status"] == "ACTIVE"
    assert client.get(f"{PR}/contracts?employee_id={emp['id']}", headers=h).json()[0]["id"] == contract["id"]


def test_duplicate_national_id_is_rejected(client):
    h, _ = _setup(client, "pay5@example.com")
    _employee_with_contract(client, h, national_id="9001010101")
    r = client.post(
        f"{PR}/employees",
        headers=h,
        json={"first_name": "Друг", "last_name": "Човек", "national_id": "9001010101"},
    )
    assert r.status_code == 409


def test_terminate_contract(client):
    h, _ = _setup(client, "pay6@example.com")
    _, contract = _employee_with_contract(client, h)
    r = client.post(
        f"{PR}/contracts/{contract['id']}/terminate",
        headers=h,
        json={"termination_date": "2026-06-30"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "TERMINATED"
    # Второ прекратяване е конфликт.
    assert client.post(
        f"{PR}/contracts/{contract['id']}/terminate",
        headers=h,
        json={"termination_date": "2026-07-31"},
    ).status_code == 409


# ------------------------------------------------------------------ ведомост
def test_calculate_run_without_rate_set_fails_clearly(client):
    h, _ = _setup(client, "pay7@example.com")
    _employee_with_contract(client, h)
    r = client.post(f"{PR}/runs/calculate", headers=h, json={"year": 2026, "month": 3})
    assert r.status_code == 409
    assert "набор осигурителни параметри" in r.json()["detail"]


def test_calculate_run(client):
    h, acc = _setup(client, "pay8@example.com")
    client.post(f"{PR}/rate-sets", headers=h, json=_rate_set_payload(acc))
    _employee_with_contract(client, h)

    r = client.post(f"{PR}/runs/calculate", headers=h, json={"year": 2026, "month": 3})
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] == "CALCULATED"
    assert len(run["lines"]) == 1

    line = run["lines"][0]
    assert line["employee_name"] == "Иван Петров"
    assert float(line["gross_amount"]) == 2000.0
    assert float(line["employee_contributions"]) == 264.0
    assert float(line["employer_contributions"]) == 336.0
    assert float(line["income_tax"]) == 173.6
    assert float(line["net_amount"]) == 1562.4
    assert {c["code"] for c in line["contributions"]} == {"DOO", "ZO"}

    assert float(run["total_gross"]) == 2000.0
    assert float(run["total_net"]) == 1562.4


def test_recalculation_replaces_lines(client):
    h, acc = _setup(client, "pay9@example.com")
    client.post(f"{PR}/rate-sets", headers=h, json=_rate_set_payload(acc))
    _employee_with_contract(client, h)
    client.post(f"{PR}/runs/calculate", headers=h, json={"year": 2026, "month": 3})

    _employee_with_contract(client, h, national_id="8502020202", salary="1000.00", number="TD-2")
    run = client.post(f"{PR}/runs/calculate", headers=h, json={"year": 2026, "month": 3}).json()

    assert len(run["lines"]) == 2
    assert float(run["total_gross"]) == 3000.0


def test_absence_reduces_pay(client):
    h, acc = _setup(client, "pay10@example.com")
    client.post(f"{PR}/rate-sets", headers=h, json=_rate_set_payload(acc))
    _, contract = _employee_with_contract(client, h)

    r = client.post(
        f"{PR}/absences",
        headers=h,
        json={
            "contract_id": contract["id"],
            "absence_type": "UNPAID_LEAVE",
            "date_from": "2026-03-02",
            "date_to": "2026-03-06",
        },
    )
    assert r.status_code == 201

    run = client.post(f"{PR}/runs/calculate", headers=h, json={"year": 2026, "month": 3}).json()
    line = run["lines"][0]
    # 2–6 март е понеделник–петък, но 3 март е официален празник → 4 работни дни.
    assert line["unpaid_leave_days"] == 4
    assert float(line["gross_amount"]) < 2000.0


def test_contract_starting_mid_month_is_prorated(client):
    h, acc = _setup(client, "pay11@example.com")
    client.post(f"{PR}/rate-sets", headers=h, json=_rate_set_payload(acc))
    emp = client.post(
        f"{PR}/employees",
        headers=h,
        json={"first_name": "Нов", "last_name": "Служител", "national_id": "9505050505"},
    ).json()
    client.post(
        f"{PR}/contracts",
        headers=h,
        json={
            "employee_id": emp["id"],
            "number": "TD-NEW",
            "position": "Стажант",
            "start_date": "2026-03-16",
            "base_salary": "2000.00",
        },
    )

    run = client.post(f"{PR}/runs/calculate", headers=h, json={"year": 2026, "month": 3}).json()
    line = run["lines"][0]
    assert line["unpaid_leave_days"] > 0        # дните преди постъпването
    assert 0 < float(line["gross_amount"]) < 2000.0


def test_terminated_contract_is_excluded_from_later_months(client):
    h, acc = _setup(client, "pay12@example.com")
    client.post(f"{PR}/rate-sets", headers=h, json=_rate_set_payload(acc))
    _, contract = _employee_with_contract(client, h)
    client.post(
        f"{PR}/contracts/{contract['id']}/terminate",
        headers=h,
        json={"termination_date": "2026-02-28"},
    )

    run = client.post(f"{PR}/runs/calculate", headers=h, json={"year": 2026, "month": 3}).json()
    assert run["lines"] == []
    assert float(run["total_gross"]) == 0.0


# ------------------------------------------------------------------ одобряване и осчетоводяване
def test_approve_and_post_creates_balanced_entry(client):
    h, acc = _setup(client, "pay13@example.com")
    client.post(f"{PR}/rate-sets", headers=h, json=_rate_set_payload(acc))
    _employee_with_contract(client, h)
    run = client.post(f"{PR}/runs/calculate", headers=h, json={"year": 2026, "month": 3}).json()

    r = client.post(f"{PR}/runs/{run['id']}/approve", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "APPROVED"

    r = client.post(f"{PR}/runs/{run['id']}/post", headers=h)
    assert r.status_code == 200, r.text
    posted = r.json()
    assert posted["status"] == "POSTED"
    assert posted["journal_entry_id"]

    entry = client.get(f"{ACC}/journal-entries/{posted['journal_entry_id']}", headers=h).json()
    debit = sum(float(line["debit"]) for line in entry["lines"])
    credit = sum(float(line["credit"]) for line in entry["lines"])
    assert debit == credit
    # Dr заплати 2000 + Dr осигуровки на работодателя 336
    assert debit == 2336.0


def test_posting_without_accounts_lists_what_is_missing(client):
    h, acc = _setup(client, "pay14@example.com")
    client.post(f"{PR}/rate-sets", headers=h, json=_rate_set_payload(acc, with_accounts=False))
    _employee_with_contract(client, h)
    run = client.post(f"{PR}/runs/calculate", headers=h, json={"year": 2026, "month": 3}).json()
    client.post(f"{PR}/runs/{run['id']}/approve", headers=h)

    r = client.post(f"{PR}/runs/{run['id']}/post", headers=h)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "Липсват сметки" in detail
    assert "разход за заплати" in detail


def test_approved_run_cannot_be_recalculated(client):
    h, acc = _setup(client, "pay15@example.com")
    client.post(f"{PR}/rate-sets", headers=h, json=_rate_set_payload(acc))
    _employee_with_contract(client, h)
    run = client.post(f"{PR}/runs/calculate", headers=h, json={"year": 2026, "month": 3}).json()
    client.post(f"{PR}/runs/{run['id']}/approve", headers=h)

    r = client.post(f"{PR}/runs/calculate", headers=h, json={"year": 2026, "month": 3})
    assert r.status_code == 409
    assert "не се преизчислява" in r.json()["detail"]


def test_cancel_returns_run_to_calculated(client):
    h, acc = _setup(client, "pay16@example.com")
    client.post(f"{PR}/rate-sets", headers=h, json=_rate_set_payload(acc))
    _employee_with_contract(client, h)
    run = client.post(f"{PR}/runs/calculate", headers=h, json={"year": 2026, "month": 3}).json()
    client.post(f"{PR}/runs/{run['id']}/approve", headers=h)

    r = client.post(f"{PR}/runs/{run['id']}/cancel", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "CALCULATED"
    # Вече може да се преизчисли.
    assert client.post(f"{PR}/runs/calculate", headers=h, json={"year": 2026, "month": 3}).status_code == 200


def test_posted_run_cannot_be_cancelled(client):
    h, acc = _setup(client, "pay17@example.com")
    client.post(f"{PR}/rate-sets", headers=h, json=_rate_set_payload(acc))
    _employee_with_contract(client, h)
    run = client.post(f"{PR}/runs/calculate", headers=h, json={"year": 2026, "month": 3}).json()
    client.post(f"{PR}/runs/{run['id']}/approve", headers=h)
    client.post(f"{PR}/runs/{run['id']}/post", headers=h)

    r = client.post(f"{PR}/runs/{run['id']}/cancel", headers=h)
    assert r.status_code == 409


def test_rate_set_used_by_approved_run_is_locked(client):
    h, acc = _setup(client, "pay18@example.com")
    rate_set = client.post(f"{PR}/rate-sets", headers=h, json=_rate_set_payload(acc)).json()
    _employee_with_contract(client, h)
    run = client.post(f"{PR}/runs/calculate", headers=h, json={"year": 2026, "month": 3}).json()
    client.post(f"{PR}/runs/{run['id']}/approve", headers=h)

    r = client.patch(f"{PR}/rate-sets/{rate_set['id']}", headers=h, json={"income_tax_percent": "20.00"})
    assert r.status_code == 409
    assert "нов набор" in r.json()["detail"]


# ------------------------------------------------------------------ изолация
def test_payroll_is_scoped_to_company(client):
    h1, acc1 = _setup(client, "pay19@example.com")
    client.post(f"{PR}/rate-sets", headers=h1, json=_rate_set_payload(acc1))
    _employee_with_contract(client, h1)

    h2, _ = _setup(client, "pay20@example.com")
    assert client.get(f"{PR}/employees", headers=h2).json() == []
    assert client.get(f"{PR}/rate-sets", headers=h2).json() == []
