#!/usr/bin/env python3
"""Генератор на демо данни — изцяло измислени, никога копие на production.

    python infra/demo/seed_demo.py http://127.0.0.1:8081

По GDPR демонстрация пред клиент с данни на действащо дружество е разкриване на
лични данни без основание. Затова демо средата НЕ се пълни със „замъглено" копие
на production, а се генерира от нула.

Две твърди гаранции:

1. **ЕИК-то на демо дружеството е невалидно по контролна сума.** Изчислява се
   верният контролен разряд и се използва различен. Така номерът не може да
   съвпадне с реално дружество в Търговския регистър.
2. **Изричен списък със забранени низове** (реални ЕИК-та, имена, имейли) се
   проверява върху всичко генерирано, преди да тръгне към сървъра.

Данните са детерминирани (`random.seed`), за да изглежда демото еднакво при
всяко пресъздаване.
"""
from __future__ import annotations

import json
import random
import sys
import urllib.error
import urllib.request

# ─────────────────────────── Контролна сума на ЕИК ────────────────────────────
_W1 = (1, 2, 3, 4, 5, 6, 7, 8)
_W2 = (3, 4, 5, 6, 7, 8, 9, 10)


def eik_check_digit(first8: str) -> int:
    """Контролният разряд на 9-значен ЕИК по алгоритъма на БУЛСТАТ."""
    digits = [int(c) for c in first8]
    total = sum(d * w for d, w in zip(digits, _W1, strict=True)) % 11
    if total != 10:
        return total
    total = sum(d * w for d, w in zip(digits, _W2, strict=True)) % 11
    return 0 if total == 10 else total


def invalid_eik(first8: str) -> str:
    """ЕИК с ГАРАНТИРАНО грешен контролен разряд — не може да е реално дружество."""
    valid = eik_check_digit(first8)
    return first8 + str((valid + 5) % 10 if (valid + 5) % 10 != valid else (valid + 1) % 10)


# ───────────────── Забранени низове: нищо реално да не изтече ─────────────────
FORBIDDEN = (
    "208418861", "BG208418861",          # реалният ЕИК на Хепсу
    "стуканьов", "stoukanyov",
    "хепсу", "heppsu",
    "георгиева-стуканьова",
    "@gmail.com", "@heppsu",
)


def assert_clean(payload) -> None:
    text = json.dumps(payload, ensure_ascii=False).lower()
    for bad in FORBIDDEN:
        if bad.lower() in text:
            raise SystemExit(f"СПРЯНО: демо данните съдържат реален низ {bad!r}")


# ────────────────────────────────── HTTP ──────────────────────────────────────
class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/") + "/api/v1"
        self.token: str | None = None
        self.company: str | None = None

    def __call__(self, path, body=None, *, method=None, expect=(200, 201)):
        if body is not None:
            assert_clean(body)
        req = urllib.request.Request(
            self.base + path, method=method or ("POST" if body is not None else "GET")
        )
        req.add_header("Accept", "application/json")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        if self.company:
            req.add_header("X-Company-Id", self.company)
        data = json.dumps(body).encode() if body is not None else None
        try:
            with urllib.request.urlopen(req, data, timeout=60) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        if status not in expect:
            raise SystemExit(f"{path} → {status}: {raw[:300].decode(errors='replace')}")
        return json.loads(raw or b"null")


# ─────────────────────────────── Демо съдържание ──────────────────────────────
DEMO_EIK = invalid_eik("30112233")

USERS = [
    ("upravitel@demo.aifos.local", "Мария Демирова", "MANAGER", "demo-upravitel-2026"),
    ("schetovoditel@demo.aifos.local", "Петър Ковачев", "CHIEF_ACCOUNTANT", "demo-schetovoditel-2026"),
    ("sluzhitel@demo.aifos.local", "Ана Тодорова", "EMPLOYEE", "demo-sluzhitel-2026"),
]

CUSTOMERS = [
    ("Северна Логистика ООД", "30144556"),
    ("Аквалайн Технолоджис ЕООД", "30155667"),
    ("Пирин Софтуер АД", "30166778"),
    ("Гларус Медия ЕООД", "30177889"),
]
SUPPLIERS = [
    ("Балкан Офис Сървисис ООД", "30188990"),
    ("Витоша Енергия ЕАД", "30199001"),
    ("Струма Транспорт ЕООД", "30100112"),
    ("Родопи Консултинг ООД", "30111223"),
]

REVENUE = {"703": "консултантски услуги", "702": "препродажба на лицензи"}
EXPENSE = {
    "601": "материали и консумативи",
    "602": "външни услуги",
    "604": "възнаграждения",
    "605": "осигуровки",
    "609": "други разходи",
}
# Сезонност: лятото е по-слабо, декември силен. Индекс по месец (1–12).
SEASON = {1: .85, 2: .9, 3: 1.05, 4: 1.0, 5: 1.1, 6: 1.05,
          7: .8, 8: .7, 9: 1.15, 10: 1.2, 11: 1.15, 12: 1.35}
MONTHS_BACK = 16


def month_window(end_year: int, end_month: int, count: int):
    y, m = end_year, end_month
    out = []
    for _ in range(count):
        out.append((y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return list(reversed(out))


def main(base: str) -> int:
    random.seed(20260726)
    api = Api(base)

    health = api("/health")
    env = health.get("environment")
    if env == "production":
        raise SystemExit("ОТКАЗ: това е production среда — демо данни там са недопустими")
    print(f"▸ Пълня демо среда ({base}, environment={env})")

    # ── Потребители ──────────────────────────────────────────────────────────
    for email, name, _role, password in USERS:
        api("/auth/register", {"email": email, "password": password, "full_name": name},
            expect=(201, 409))
    owner_email, _, _, owner_pass = USERS[0]
    api.token = api("/auth/login", {"email": owner_email, "password": owner_pass})["access_token"]
    print(f"  потребители: {len(USERS)} (домейн @demo.aifos.local)")

    # ── Дружество ────────────────────────────────────────────────────────────
    company = api("/companies", {
        "name": "ДЕМО КОНСУЛТ ЕООД",
        "name_latin": "Demo Consult ltd",
        "eik": DEMO_EIK,
        "vat_number": "BG" + DEMO_EIK,
        "is_vat_registered": True,
        "address_city": "гр. Демоград",
        "address_postcode": "1000",
        "address_line": "ул. Примерна 1",
        "manager_name": "Мария Демирова",
    })
    api.company = company["id"]
    print(f"  дружество: ДЕМО КОНСУЛТ ЕООД, ЕИК {DEMO_EIK} "
          f"(контролна сума нарочно грешна — верният разряд е {eik_check_digit(DEMO_EIK[:8])})")

    # ── Основа ───────────────────────────────────────────────────────────────
    accounts = {a["code"]: a["id"] for a in api("/accounting/chart/seed", {})}
    api("/rbac/roles/seed", {})
    vat_codes = {c["code"]: c["id"] for c in api("/vat/codes/seed", {})}

    window = month_window(2026, 7, MONTHS_BACK)
    for year in sorted({y for y, _ in window}):
        api("/accounting/fiscal-years", {"year": year}, expect=(201, 409, 422))
    print(f"  сметкоплан: {len(accounts)} сметки, фискални години: "
          f"{', '.join(str(y) for y in sorted({y for y, _ in window}))}")

    # ── Контрагенти ──────────────────────────────────────────────────────────
    parties: dict[str, str] = {}
    for typ, group in (("CUSTOMER", CUSTOMERS), ("SUPPLIER", SUPPLIERS)):
        for name, eik8 in group:
            eik = invalid_eik(eik8)
            parties[name] = api("/counterparties", {
                "type": typ, "name": name, "eik": eik, "vat_number": "BG" + eik,
                "address": "гр. Демоград", "country": "BG",
            })["id"]
    print(f"  контрагенти: {len(parties)} (всички с невалидни по контролна сума ЕИК)")

    # ── Операции по месеци, със сезонност и растеж ───────────────────────────
    def entry(date, num, pairs, desc):
        lines = []
        for dr, cr, amount in pairs:
            lines.append({"account_id": accounts[dr], "debit": f"{amount:.2f}", "credit": "0"})
            lines.append({"account_id": accounts[cr], "debit": "0", "credit": f"{amount:.2f}"})
        e = api("/accounting/journal-entries",
                {"document_date": date, "document_number": num,
                 "description": desc, "lines": lines})
        api(f"/accounting/journal-entries/{e['id']}/post", {})

    n = 0
    for i, (y, m) in enumerate(window):
        growth = 1 + i * 0.045                       # плавен ръст през периода
        season = SEASON[m]
        for code, what in REVENUE.items():
            n += 1
            amount = random.uniform(9_000, 24_000) * growth * season
            entry(f"{y}-{m:02d}-{random.randint(4, 26):02d}", f"DEMO-{n:04d}",
                  [("501", code, amount)], f"Приход от {what}")
        for code, what in EXPENSE.items():
            n += 1
            base_amount = {"604": 6_500, "605": 1_900}.get(code, random.uniform(700, 5_200))
            amount = base_amount * (1 + i * 0.02) * (1 if code in ("604", "605") else season)
            entry(f"{y}-{m:02d}-{random.randint(4, 26):02d}", f"DEMO-{n:04d}",
                  [(code, "501", amount)], f"Разход за {what}")
    print(f"  счетоводни операции: {n} за {MONTHS_BACK} месеца")

    # ── Фактури и покупки за последните месеци ───────────────────────────────
    issued = 0
    for i, (y, m) in enumerate(window[-4:]):
        for name, _ in CUSTOMERS[: 2 + (i % 3)]:
            inv = api("/invoices", {
                "counterparty_id": parties[name], "invoice_type": "INVOICE",
                "issue_date": f"{y}-{m:02d}-{random.randint(6, 25):02d}",
                "vat_code_id": vat_codes["S20"],
                "lines": [{"description": "Абонамент за консултантски услуги",
                           "quantity": "1",
                           "unit_price": f"{random.uniform(1200, 6800):.2f}"}],
            })
            api(f"/invoices/{inv['id']}/issue", {})
            issued += 1

    purchased = 0
    for i, (y, m) in enumerate(window[-4:]):
        for j, (name, _) in enumerate(SUPPLIERS[:3]):
            api("/purchase-invoices", {
                "counterparty_id": parties[name],
                "supplier_document_number": f"DOC-{y}{m:02d}-{j + 1:03d}",
                "document_date": f"{y}-{m:02d}-{random.randint(5, 24):02d}",
                "vat_code_id": vat_codes["P20"],
                "expense_account_id": accounts["602"],
                "lines": [{"description": "Периодична услуга", "quantity": "1",
                           "unit_price": f"{random.uniform(180, 2400):.2f}"}],
            })
            purchased += 1
    print(f"  фактури: {issued} издадени, {purchased} получени")

    # ── Проверка на резултата ────────────────────────────────────────────────
    tb = api("/reports/trial-balance")
    if not tb["is_balanced"]:
        raise SystemExit("ГРЕШКА: демо данните не са балансирани")
    series = api("/reports/kpi-series?months=12&end=2026-07-31")
    active = sum(1 for p in series["points"] if float(p["revenue"]) > 0)
    print(f"  оборотната ведомост е балансирана; {active} от 12 месеца с приходи")
    print("▸ ГОТОВО — демо средата е напълнена с изцяло измислени данни")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("употреба: seed_demo.py <base-url>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
