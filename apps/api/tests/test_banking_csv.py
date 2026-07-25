from tests.conftest import register_and_login

BANK = "/api/v1/banking"


def _setup(client, email):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    cid = client.post("/api/v1/companies", headers=auth, json={"name": "Акме ЕООД"}).json()["id"]
    h = {**auth, "X-Company-Id": cid}
    acc_id = client.post(f"{BANK}/accounts", headers=h, json={"name": "Разпл."}).json()["id"]
    return h, acc_id


def _import_csv(client, h, acc_id, csv_text, **form):
    return client.post(
        f"{BANK}/accounts/{acc_id}/import-csv",
        headers=h,
        files={"file": ("stmt.csv", csv_text.encode("utf-8"), "text/csv")},
        data=form,
    )


def test_csv_import_and_dedup(client):
    h, acc_id = _setup(client, "csv1@example.com")
    csv_text = "date,amount,ref\n2026-07-15,1000.00,INV-1\n2026-07-16,-250.00,SUP-1\n"
    form = {"date_column": "date", "amount_column": "amount", "reference_column": "ref", "date_format": "%Y-%m-%d"}
    r = _import_csv(client, h, acc_id, csv_text, **form)
    assert r.status_code == 201, r.text
    assert r.json() == {"imported": 2, "duplicates": 0}

    txs = client.get(f"{BANK}/transactions", headers=h).json()
    assert len(txs) == 2
    amounts = sorted(float(t["amount"]) for t in txs)
    assert amounts == [-250.0, 1000.0]

    # повторен импорт → дубликати
    assert _import_csv(client, h, acc_id, csv_text, **form).json() == {"imported": 0, "duplicates": 2}


def test_csv_decimal_comma(client):
    h, acc_id = _setup(client, "csv2@example.com")
    csv_text = 'date;amount;ref\n15.07.2026;"1 234,56";X\n'
    form = {"date_column": "date", "amount_column": "amount", "reference_column": "ref",
            "delimiter": ";", "date_format": "%d.%m.%Y", "decimal_comma": "true"}
    r = _import_csv(client, h, acc_id, csv_text, **form)
    assert r.status_code == 201, r.text
    tx = client.get(f"{BANK}/transactions", headers=h).json()[0]
    assert float(tx["amount"]) == 1234.56


def test_csv_missing_column(client):
    h, acc_id = _setup(client, "csv3@example.com")
    r = _import_csv(client, h, acc_id, "date,x\n2026-07-15,5\n",
                    date_column="date", amount_column="amount")
    assert r.status_code == 422


def test_csv_invalid_row(client):
    h, acc_id = _setup(client, "csv4@example.com")
    r = _import_csv(client, h, acc_id, "date,amount\nНЕДАТА,abc\n",
                    date_column="date", amount_column="amount")
    assert r.status_code == 422
