#!/usr/bin/env python3
"""Smoke тестове срещу РАЗГЪРНАТА среда.

Модулните тестове доказват, че кодът е правилен. Тези тестове доказват, че точно
този контейнер, с точно тази база и точно този nginx, върши реална работа —
хващат счупен .env, недостъпна база, объркан reverse proxy, липсваща миграция.

    python infra/ci/smoke.py http://127.0.0.1:8080              # пълни
    python infra/ci/smoke.py https://... --read-only            # само четящи

ВАЖНО за production: пълните проверки СЪЗДАВАТ дружество, сметкоплан и
счетоводни операции. В production това означава фиктивни записи в реална
счетоводна база — недопустимо. Затова там се пуска `--read-only`, който само
чете и проверява, че защитата работи.

Изход: 0 = всичко минава, 1 = има провал.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []

# `urlopen` отваря и `file:`, и `ftp:`, и всяка друга схема, която Python познава.
# Скриптът се вика от deploy потока с адрес, който идва отвън (аргумент, променлива
# в CI, копи-пейст). Адрес без схема или с `file:` не дава грешка „няма връзка“, а
# се ЧЕТЕ от диска — и smoke тестът минава срещу файл, докато разгърнатата среда е
# счупена. Затова схемата се проверява веднъж, на входа.
_ALLOWED_SCHEMES = ("http", "https")


def require_http_url(base: str) -> str:
    """Приема само http(s) адрес. Всичко друго спира скрипта с ясно съобщение."""
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.netloc:
        raise SystemExit(
            f"невалиден адрес {base!r}: очаква се http:// или https:// с име на машина"
        )
    return base


def call(base: str, path: str, *, method: str = "GET", body=None,
         token: str | None = None, company: str | None = None, expect: int | None = None):
    # S310: схемата на `base` е проверена на входа (`require_http_url`), а `path`
    # се задава от проверките в този файл.
    req = urllib.request.Request(base + path, method=method)  # noqa: S310
    req.add_header("Accept", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if company:
        req.add_header("X-Company-Id", company)
    data = None
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, data, timeout=30) as r:  # nosec B310  # noqa: S310
            status, payload = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, payload = e.code, e.read()
    if expect is not None and status != expect:
        raise AssertionError(f"{method} {path} → {status}, очаквах {expect}: {payload[:200]!r}")
    try:
        return status, json.loads(payload or b"null")
    except json.JSONDecodeError:
        return status, payload.decode(errors="replace")


def check(name: str):
    """Декоратор: изпълнява проверка и записва резултата, без да спира останалите."""
    def wrap(fn):
        try:
            fn()
            PASSED.append(name)
            print(f"\033[1;32m  ✓\033[0m {name}")
        except Exception as exc:                       # noqa: BLE001 — искаме всички провали
            FAILED.append((name, str(exc)))
            print(f"\033[1;31m  ✗\033[0m {name}\n      {exc}")
        return fn
    return wrap


def main(base: str, read_only: bool = False) -> int:
    base = require_http_url(base).rstrip("/")
    api = base + "/api/v1"
    stamp = int(time.time())
    email = f"smoke-{stamp}@example.com"
    password = "smoke-test-password-1"
    state: dict = {}

    mode = "само четящи" if read_only else "пълни"
    print(f"\n\033[1;36m▸ Smoke тестове срещу {base} ({mode})\033[0m\n")

    @check("приложението отговаря (/health)")
    def _():
        _, d = call(api, "/health", expect=200)
        assert d["status"] == "ok", d
        state["environment"] = d.get("environment")

    @check("базата е достъпна (/health/db)")
    def _():
        _, d = call(api, "/health/db", expect=200)
        assert d["status"] == "ok", d

    @check("уеб приложението се сервира (/app/)")
    def _():
        req = urllib.request.Request(base + "/app/")  # noqa: S310 — виж `require_http_url`
        with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310  # noqa: S310
            html = r.read().decode("utf-8", "replace")
        assert r.status == 200, r.status
        assert "AI Finance OS" in html, "липсва заглавието"
        assert "id=\"shell\"" in html, "липсва приложната обвивка"

    @check("защитен endpoint отказва достъп без токен")
    def _():
        call(api, "/companies", expect=401)

    @check("несъществуващ потребител не влиза")
    def _():
        call(api, "/auth/login", method="POST",
             body={"email": f"nobody-{stamp}@example.com", "password": "каквото и да е"},
             expect=401)

    # Регистрацията създава запис — в production се прескача.
    if not read_only:
        @check("регистрация и вход")
        def _():
            call(api, "/auth/register", method="POST",
                 body={"email": email, "password": password, "full_name": "Smoke Тест"},
                 expect=201)
            _, d = call(api, "/auth/login", method="POST",
                        body={"email": email, "password": password}, expect=200)
            assert d.get("access_token"), d
            state["token"] = d["access_token"]

        @check("грешна парола не пуска")
        def _():
            call(api, "/auth/login", method="POST",
                 body={"email": email, "password": "грешна"}, expect=401)

    if read_only:
        print()
        if FAILED:
            print(f"\033[1;31m✗ {len(FAILED)} от {len(PASSED) + len(FAILED)} проверки се провалиха\033[0m")
            for name, err in FAILED:
                print(f"   · {name}: {err}")
            return 1
        print(f"\033[1;32m✓ всички {len(PASSED)} четящи проверки минаха "
              f"(среда: {state.get('environment')})\033[0m")
        return 0

    @check("създаване на дружество")
    def _():
        _, d = call(api, "/companies", method="POST",
                    body={"name": f"Smoke ЕООД {stamp}", "eik": "208418861"},
                    token=state["token"], expect=201)
        state["company"] = d["id"]

    @check("зареждане на сметкоплан")
    def _():
        _, d = call(api, "/accounting/chart/seed", method="POST", body={},
                    token=state["token"], company=state["company"], expect=201)
        assert len(d) > 20, f"само {len(d)} сметки"
        state["accounts"] = {a["code"]: a["id"] for a in d}

    @check("създаване на фискална година")
    def _():
        call(api, "/accounting/fiscal-years", method="POST", body={"year": 2026},
             token=state["token"], company=state["company"], expect=201)

    @check("осчетоводяване на операция")
    def _():
        acc = state["accounts"]
        _, e = call(api, "/accounting/journal-entries", method="POST", body={
            "document_date": "2026-07-15", "document_number": "SMOKE-1",
            "description": "Smoke тест",
            "lines": [{"account_id": acc["501"], "debit": "1234.56", "credit": "0"},
                      {"account_id": acc["703"], "debit": "0", "credit": "1234.56"}],
        }, token=state["token"], company=state["company"], expect=201)
        call(api, f"/accounting/journal-entries/{e['id']}/post", method="POST", body={},
             token=state["token"], company=state["company"], expect=200)

    @check("небалансирана операция се отказва")
    def _():
        acc = state["accounts"]
        call(api, "/accounting/journal-entries", method="POST", body={
            "document_date": "2026-07-15", "document_number": "SMOKE-BAD",
            "lines": [{"account_id": acc["501"], "debit": "100.00", "credit": "0"},
                      {"account_id": acc["703"], "debit": "0", "credit": "99.00"}],
        }, token=state["token"], company=state["company"], expect=422)

    @check("оборотната ведомост е балансирана")
    def _():
        _, d = call(api, "/reports/trial-balance",
                    token=state["token"], company=state["company"], expect=200)
        assert d["is_balanced"], d
        assert float(d["total_debit_turnover"]) == 1234.56, d["total_debit_turnover"]

    @check("ОПР отразява прихода")
    def _():
        _, d = call(api, "/reports/profit-and-loss?date_from=2026-07-01&date_to=2026-07-31",
                    token=state["token"], company=state["company"], expect=200)
        assert float(d["revenue"]["total"]) == 1234.56, d["revenue"]

    @check("времевият ред за таблото работи")
    def _():
        _, d = call(api, "/reports/kpi-series?months=6&end=2026-07-31",
                    token=state["token"], company=state["company"], expect=200)
        assert len(d["points"]) == 6, len(d["points"])
        assert float(d["points"][-1]["revenue"]) == 1234.56, d["points"][-1]

    @check("сроковете към НАП се изчисляват")
    def _():
        _, d = call(api, "/deadlines/upcoming?days_ahead=60",
                    token=state["token"], company=state["company"], expect=200)
        assert isinstance(d, list), d

    @check("чуждо дружество е недостъпно")
    def _():
        call(api, "/reports/trial-balance", token=state["token"],
             company="00000000-0000-0000-0000-000000000000", expect=403)

    @check("SAF-T експортът се генерира")
    def _():
        _, d = call(api, "/submissions/saft/preview?date_from=2026-07-01&date_to=2026-07-31",
                    token=state["token"], company=state["company"], expect=200)
        assert d["size_bytes"] > 0, d

    print()
    if FAILED:
        print(f"\033[1;31m✗ {len(FAILED)} от {len(PASSED) + len(FAILED)} проверки се провалиха\033[0m")
        for name, err in FAILED:
            print(f"   · {name}: {err}")
        return 1
    print(f"\033[1;32m✓ всички {len(PASSED)} проверки минаха "
          f"(среда: {state.get('environment')})\033[0m")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        print("употреба: smoke.py <base-url> [--read-only]", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(args[0], read_only="--read-only" in sys.argv))
