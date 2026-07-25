"""Тестове за VAT Refund Procedure Engine (чл. 92 ЗДДС).

Покриват стандартната двумесечна процедура (клетки 60 → 70/71 → 80), ускореното
възстановяване по ал. 3 (клетка 81, с изрично потвърждение), режима по разрешение
(клетка 82) и решенията на НАП.
"""
from tests.conftest import register_and_login

ACC = "/api/v1/accounting"
VAT = "/api/v1/vat"
REF = "/api/v1/vat-refunds"


def _setup(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    cid = client.post(
        "/api/v1/companies", headers=auth,
        json={"name": "Хепсу Консултинг ЕООД", "eik": "208418861",
              "vat_number": "BG208418861", "is_vat_registered": True},
    ).json()["id"]
    h = {**auth, "X-Company-Id": cid}
    client.post(f"{ACC}/chart/seed", headers=h)
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    codes = {c["code"]: c for c in client.post(f"{VAT}/codes/seed", headers=h).json()}
    return h, codes


def _periods(client, h) -> dict[str, str]:
    year = client.get(f"{ACC}/fiscal-years", headers=h).json()[0]
    return {p["code"]: p["id"] for p in year["periods"]}


def _entry(client, h, code_id, base, date, doc, vat_no=None):
    payload = {"vat_code_id": code_id, "document_date": date, "document_number": doc,
               "counterparty_name": "Контрагент", "tax_base": base}
    if vat_no:
        payload["counterparty_vat_number"] = vat_no
    r = client.post(f"{VAT}/entries", headers=h, json=payload)
    assert r.status_code == 201, r.text


def _make_refund_month(client, h, codes, month="2026-01", sale="1000.00", purchase="20000.00"):
    """Създава месец с ДДС за възстановяване (кредитът е по-голям от начисления данък)."""
    date = f"{month}-10"
    _entry(client, h, codes["S20"]["id"], sale, date, f"S-{month}")
    _entry(client, h, codes["P20"]["id"], purchase, date, f"P-{month}")


def _make_payable_month(client, h, codes, month, sale="10000.00", purchase="1000.00"):
    """Месец с ДДС за внасяне."""
    date = f"{month}-10"
    _entry(client, h, codes["S20"]["id"], sale, date, f"S-{month}")
    _entry(client, h, codes["P20"]["id"], purchase, date, f"P-{month}")


# ============================ Възникване (клетка 60) ============================
def test_refund_arises_and_opens_procedure(client):
    h, codes = _setup(client, "ref1@example.com")
    p = _periods(client, h)
    _make_refund_month(client, h, codes, "2026-01")   # начислен 200, кредит 4000 → 3800 за възстановяване

    r = client.post(f"{REF}/evaluate/{p['2026-01']}", headers=h)
    assert r.status_code == 200, r.text
    ov = r.json()
    proc = ov["procedure"]
    assert float(proc["original_refund_amount"]) == 3800.0
    assert float(proc["remaining_refund"]) == 3800.0
    assert proc["status"] == "CALCULATED"
    assert proc["declaration_cell"] == "60"           # първи месец → клетка 60, НЕ 80
    assert proc["procedure_type"] == "STANDARD"
    assert "92, ал. 1" in proc["legal_basis"]
    # двата последващи периода са определени
    assert ov["first_offset_period_code"] == "2026-02"
    assert ov["second_offset_period_code"] == "2026-03"
    # срок за подаване: до 14-о число на следващия месец
    assert proc["submission_deadline"] == "2026-02-14"


def test_no_procedure_when_vat_payable(client):
    h, codes = _setup(client, "ref2@example.com")
    p = _periods(client, h)
    _make_payable_month(client, h, codes, "2026-01")
    r = client.post(f"{REF}/evaluate/{p['2026-01']}", headers=h)
    assert r.status_code == 200
    assert r.json() is None      # няма ДДС за възстановяване → няма процедура


def test_evaluate_is_idempotent(client):
    h, codes = _setup(client, "ref3@example.com")
    p = _periods(client, h)
    _make_refund_month(client, h, codes, "2026-01")
    first = client.post(f"{REF}/evaluate/{p['2026-01']}", headers=h).json()["procedure"]["id"]
    second = client.post(f"{REF}/evaluate/{p['2026-01']}", headers=h).json()["procedure"]["id"]
    assert first == second       # не се създава втора процедура за същия период


# ============================ Стандартна процедура (клетки 70/71/80) ============================
def test_standard_two_month_offset_to_cell_80(client):
    """Пълният път по чл. 92, ал. 1: остатъкът стига до клетка 80 след два периода."""
    h, codes = _setup(client, "ref4@example.com")
    p = _periods(client, h)
    _make_refund_month(client, h, codes, "2026-01")                    # 3800 за възстановяване
    _make_payable_month(client, h, codes, "2026-02", sale="5000.00", purchase="0.00")   # 1000 за внасяне
    _make_payable_month(client, h, codes, "2026-03", sale="2500.00", purchase="0.00")   # 500 за внасяне

    proc_id = client.post(f"{REF}/evaluate/{p['2026-01']}", headers=h).json()["procedure"]["id"]
    client.post(f"{REF}/{proc_id}/validate-credit", headers=h)
    client.post(f"{REF}/{proc_id}/declare-cell-60", headers=h)

    # Първи последващ период: приспадат се 1000 (клетка 70), остават 2800
    ov = client.post(f"{REF}/{proc_id}/offset/{p['2026-02']}", headers=h).json()
    proc = ov["procedure"]
    assert proc["status"] == "OFFSET_PERIOD_1"
    off1 = proc["offsets"][0]
    assert float(off1["vat_payable_in_period"]) == 1000.0
    assert float(off1["amount"]) == 1000.0            # клетка 70
    assert float(off1["payable_remaining"]) == 0.0    # клетка 71
    assert float(proc["remaining_refund"]) == 2800.0

    # Втори последващ период: приспадат се 500, остават 2300 → клетка 80
    ov = client.post(f"{REF}/{proc_id}/offset/{p['2026-03']}", headers=h).json()
    proc = ov["procedure"]
    assert proc["status"] == "READY_FOR_CELL_80"
    assert proc["declaration_cell"] == "80"
    assert float(proc["amount_offset"]) == 1500.0
    assert float(proc["remaining_refund"]) == 2300.0
    assert proc["submission_deadline"] == "2026-04-14"
    assert "клетка 80" in ov["next_action"]


def test_offset_wrong_period_rejected(client):
    h, codes = _setup(client, "ref5@example.com")
    p = _periods(client, h)
    _make_refund_month(client, h, codes, "2026-01")
    proc_id = client.post(f"{REF}/evaluate/{p['2026-01']}", headers=h).json()["procedure"]["id"]
    client.post(f"{REF}/{proc_id}/validate-credit", headers=h)
    client.post(f"{REF}/{proc_id}/declare-cell-60", headers=h)
    # 2026-05 не е един от двата последващи периода
    r = client.post(f"{REF}/{proc_id}/offset/{p['2026-05']}", headers=h)
    assert r.status_code == 422
    assert "последващ" in r.json()["detail"]


def test_offset_closes_procedure_when_fully_absorbed(client):
    """Ако приспадането покрие целия остатък, няма какво да се възстановява."""
    h, codes = _setup(client, "ref6@example.com")
    p = _periods(client, h)
    _make_refund_month(client, h, codes, "2026-01", sale="1000.00", purchase="2000.00")  # 200 за възст.
    _make_payable_month(client, h, codes, "2026-02", sale="10000.00", purchase="0.00")   # 2000 за внасяне

    proc_id = client.post(f"{REF}/evaluate/{p['2026-01']}", headers=h).json()["procedure"]["id"]
    client.post(f"{REF}/{proc_id}/validate-credit", headers=h)
    client.post(f"{REF}/{proc_id}/declare-cell-60", headers=h)
    proc = client.post(f"{REF}/{proc_id}/offset/{p['2026-02']}", headers=h).json()["procedure"]
    assert proc["status"] == "CLOSED"
    assert float(proc["remaining_refund"]) == 0.0
    assert proc["declaration_cell"] is None
    off = proc["offsets"][0]
    assert float(off["amount"]) == 200.0               # клетка 70 = приспаднатото
    assert float(off["payable_remaining"]) == 1800.0   # клетка 71 = остава за внасяне


def test_duplicate_offset_rejected(client):
    h, codes = _setup(client, "ref7@example.com")
    p = _periods(client, h)
    _make_refund_month(client, h, codes, "2026-01")
    _make_payable_month(client, h, codes, "2026-02", sale="500.00", purchase="0.00")
    proc_id = client.post(f"{REF}/evaluate/{p['2026-01']}", headers=h).json()["procedure"]["id"]
    client.post(f"{REF}/{proc_id}/validate-credit", headers=h)
    client.post(f"{REF}/{proc_id}/declare-cell-60", headers=h)
    assert client.post(f"{REF}/{proc_id}/offset/{p['2026-02']}", headers=h).status_code == 200
    r = client.post(f"{REF}/{proc_id}/offset/{p['2026-02']}", headers=h)
    assert r.status_code == 409


# ============================ Ускорена процедура (клетка 81) ============================
def test_accelerated_check_below_threshold(client):
    """Само продажби с 20% → критерият за нулева ставка не е изпълнен."""
    h, codes = _setup(client, "ref8@example.com")
    p = _periods(client, h)
    # исторически облагаеми доставки през 2026-02..2026-05 (преди периода на възникване)
    for m in ("2026-02", "2026-03", "2026-04"):
        _entry(client, h, codes["S20"]["id"], "10000.00", f"{m}-10", f"H-{m}")
    _make_refund_month(client, h, codes, "2026-06")

    proc_id = client.post(f"{REF}/evaluate/{p['2026-06']}", headers=h).json()["procedure"]["id"]
    chk = client.get(f"{REF}/{proc_id}/accelerated-check", headers=h).json()
    assert chk["eligible"] is False
    assert float(chk["threshold_percent"]) == 30.0
    assert chk["requires_user_approval"] is True


def test_accelerated_check_above_threshold(client):
    """Над 30% ВОД (нулева ставка) → условието е изпълнено."""
    h, codes = _setup(client, "ref9@example.com")
    p = _periods(client, h)
    for m in ("2026-02", "2026-03", "2026-04"):
        _entry(client, h, codes["S20"]["id"], "1000.00", f"{m}-10", f"D-{m}")
        _entry(client, h, codes["SICS"]["id"], "4000.00", f"{m}-11", f"V-{m}", vat_no="DE111222333")
    _make_refund_month(client, h, codes, "2026-06")

    proc_id = client.post(f"{REF}/evaluate/{p['2026-06']}", headers=h).json()["procedure"]["id"]
    chk = client.get(f"{REF}/{proc_id}/accelerated-check", headers=h).json()
    assert chk["eligible"] is True
    assert float(chk["ratio_percent"]) == 80.0        # 12000 от 15000
    assert "92, ал. 3" in chk["legal_basis"]


def test_accelerated_requires_explicit_confirmation(client):
    """Ускорената процедура НЕ се прилага автоматично."""
    h, codes = _setup(client, "ref10@example.com")
    p = _periods(client, h)
    for m in ("2026-02", "2026-03"):
        _entry(client, h, codes["SICS"]["id"], "5000.00", f"{m}-10", f"V-{m}", vat_no="DE111222333")
    _make_refund_month(client, h, codes, "2026-06")
    proc_id = client.post(f"{REF}/evaluate/{p['2026-06']}", headers=h).json()["procedure"]["id"]

    # проверката сама по себе си не сменя процедурата
    client.get(f"{REF}/{proc_id}/accelerated-check", headers=h)
    proc = client.get(f"{REF}/{proc_id}", headers=h).json()["procedure"]
    assert proc["procedure_type"] == "STANDARD"
    assert proc["declaration_cell"] == "60"

    # без потвърждение → отказ
    r = client.post(f"{REF}/{proc_id}/elect-accelerated", headers=h, json={"confirm": False})
    assert r.status_code == 422

    # с потвърждение → клетка 81
    ov = client.post(f"{REF}/{proc_id}/elect-accelerated", headers=h, json={"confirm": True}).json()
    proc = ov["procedure"]
    assert proc["procedure_type"] == "ACCELERATED"
    assert proc["declaration_cell"] == "81"
    assert proc["status"] == "DECLARED_IN_CELL_81"
    assert "92, ал. 3" in proc["legal_basis"]
    # ускорената процедура пропуска двумесечното приспадане
    assert proc["first_offset_period_id"] is None


def test_accelerated_rejected_when_not_eligible(client):
    h, codes = _setup(client, "ref11@example.com")
    p = _periods(client, h)
    _entry(client, h, codes["S20"]["id"], "10000.00", "2026-02-10", "H-1")
    _make_refund_month(client, h, codes, "2026-06")
    proc_id = client.post(f"{REF}/evaluate/{p['2026-06']}", headers=h).json()["procedure"]["id"]
    r = client.post(f"{REF}/{proc_id}/elect-accelerated", headers=h, json={"confirm": True})
    assert r.status_code == 422
    assert "не са изпълнени" in r.json()["detail"]


def test_investment_permit_uses_cell_82(client):
    """Разрешение по чл. 166 → клетка 82 (чл. 92, ал. 4), без 30% критерий."""
    h, codes = _setup(client, "ref12@example.com")
    p = _periods(client, h)
    _make_refund_month(client, h, codes, "2026-01")
    proc_id = client.post(f"{REF}/evaluate/{p['2026-01']}", headers=h).json()["procedure"]["id"]
    ov = client.post(
        f"{REF}/{proc_id}/elect-accelerated", headers=h,
        json={"confirm": True, "investment_permit_number": "РАЗР-2026-007"},
    ).json()
    proc = ov["procedure"]
    assert proc["procedure_type"] == "INVESTMENT_PERMIT"
    assert proc["declaration_cell"] == "82"
    assert "166" in proc["legal_basis"]
    assert proc["nra_act_reference"] == "РАЗР-2026-007"


# ============================ Подаване, проверка, решение ============================
def test_submit_starts_30_day_deadline(client):
    h, codes = _setup(client, "ref13@example.com")
    p = _periods(client, h)
    for m in ("2026-02", "2026-03"):
        _entry(client, h, codes["SICS"]["id"], "5000.00", f"{m}-10", f"V-{m}", vat_no="DE111222333")
    _make_refund_month(client, h, codes, "2026-06")
    proc_id = client.post(f"{REF}/evaluate/{p['2026-06']}", headers=h).json()["procedure"]["id"]
    client.post(f"{REF}/{proc_id}/elect-accelerated", headers=h, json={"confirm": True})

    proc = client.post(f"{REF}/{proc_id}/submit?submitted_on=2026-07-10", headers=h).json()["procedure"]
    assert proc["status"] == "SUBMITTED_FOR_REFUND"
    assert proc["submission_date"] == "2026-07-10"
    assert proc["expected_refund_deadline"] == "2026-08-09"   # +30 дни


def test_submit_before_cell_80_rejected(client):
    """Не се подава заявление за възстановяване, докато сумата е още в клетка 60."""
    h, codes = _setup(client, "ref14@example.com")
    p = _periods(client, h)
    _make_refund_month(client, h, codes, "2026-01")
    proc_id = client.post(f"{REF}/evaluate/{p['2026-01']}", headers=h).json()["procedure"]["id"]
    r = client.post(f"{REF}/{proc_id}/submit", headers=h)
    assert r.status_code == 422
    assert "80, 81 или 82" in r.json()["detail"]


def test_full_lifecycle_to_paid(client):
    h, codes = _setup(client, "ref15@example.com")
    p = _periods(client, h)
    _make_refund_month(client, h, codes, "2026-01")                                    # 3800
    _make_payable_month(client, h, codes, "2026-02", sale="5000.00", purchase="0.00")   # 1000
    _make_payable_month(client, h, codes, "2026-03", sale="2500.00", purchase="0.00")   # 500

    proc_id = client.post(f"{REF}/evaluate/{p['2026-01']}", headers=h).json()["procedure"]["id"]
    client.post(f"{REF}/{proc_id}/validate-credit", headers=h)
    client.post(f"{REF}/{proc_id}/declare-cell-60", headers=h)
    client.post(f"{REF}/{proc_id}/offset/{p['2026-02']}", headers=h)
    client.post(f"{REF}/{proc_id}/offset/{p['2026-03']}", headers=h)
    client.post(f"{REF}/{proc_id}/submit?submitted_on=2026-04-10", headers=h)
    proc = client.post(f"{REF}/{proc_id}/nra-check", headers=h).json()["procedure"]
    assert proc["status"] == "UNDER_NRA_CHECK"
    assert proc["nra_check_status"] == "CHECK"

    proc = client.post(
        f"{REF}/{proc_id}/decision", headers=h,
        json={"approved_amount": "2300.00", "nra_act_reference": "АПВ-123"},
    ).json()["procedure"]
    assert proc["status"] == "APPROVED"

    proc = client.post(
        f"{REF}/{proc_id}/payment", headers=h,
        json={"amount_paid": "2300.00", "nra_act_reference": "АПВ-123"},
    ).json()["procedure"]
    assert proc["status"] == "PAID"
    assert float(proc["amount_paid"]) == 2300.0
    assert proc["nra_check_status"] == "COMPLETED"


def test_partial_approval_and_offset_by_nra(client):
    h, codes = _setup(client, "ref16@example.com")
    p = _periods(client, h)
    for m in ("2026-02", "2026-03"):
        _entry(client, h, codes["SICS"]["id"], "5000.00", f"{m}-10", f"V-{m}", vat_no="DE111222333")
    _make_refund_month(client, h, codes, "2026-06")
    proc_id = client.post(f"{REF}/evaluate/{p['2026-06']}", headers=h).json()["procedure"]["id"]
    client.post(f"{REF}/{proc_id}/elect-accelerated", headers=h, json={"confirm": True})
    client.post(f"{REF}/{proc_id}/submit", headers=h)
    client.post(f"{REF}/{proc_id}/nra-check", headers=h, params={"audit": True})

    proc = client.post(
        f"{REF}/{proc_id}/decision", headers=h,
        json={"approved_amount": "1000.00", "offset_against_public_liabilities": "500.00"},
    ).json()["procedure"]
    assert proc["status"] == "PARTIALLY_APPROVED"
    assert float(proc["offset_against_public_liabilities"]) == 500.0


def test_invalid_transition_rejected(client):
    """Процедурата не може да прескача етапи."""
    h, codes = _setup(client, "ref17@example.com")
    p = _periods(client, h)
    _make_refund_month(client, h, codes, "2026-01")
    proc_id = client.post(f"{REF}/evaluate/{p['2026-01']}", headers=h).json()["procedure"]["id"]
    # директно към решение на НАП, без подаване
    r = client.post(f"{REF}/{proc_id}/nra-check", headers=h)
    assert r.status_code == 409
    assert "Недопустим преход" in r.json()["detail"]


# ============================ Валидации и изолация ============================
def test_validations_present_in_overview(client):
    h, codes = _setup(client, "ref18@example.com")
    p = _periods(client, h)
    _make_refund_month(client, h, codes, "2026-01")
    ov = client.post(f"{REF}/evaluate/{p['2026-01']}", headers=h).json()
    codes_found = {v["code"] for v in ov["validations"]}
    assert codes_found  # има поне един резултат от проверките
    assert all(v["level"] in ("ERROR", "WARNING", "INFO") for v in ov["validations"])


def test_procedures_tenant_isolated(client):
    h_a, codes_a = _setup(client, "ref19a@example.com")
    p_a = _periods(client, h_a)
    _make_refund_month(client, h_a, codes_a, "2026-01")
    client.post(f"{REF}/evaluate/{p_a['2026-01']}", headers=h_a)

    h_b, _ = _setup(client, "ref19b@example.com")
    assert client.get(REF, headers=h_b).json() == []
