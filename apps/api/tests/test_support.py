"""Докладване от потребителя → Control Center: запис, опашка, договор.

Навън не излиза нищо: транспортът на httpx е подменен (`httpx.MockTransport`) и
всеки тест сам решава какво „отговаря“ Control Center. Тестовете викат
`forward_due` директно, вместо да чакат фоновия цикъл.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel, Field

from tests.conftest import register_and_login

URL = "https://cockpit.example.test"
TOKEN = "app-token-for-tests-only"


# ── Договорът: копие на схемата на получателя ────────────────────────────────
# Дословно от Control Center, `app/api/tickets.py`, класът `TicketIn`,
# origin/main 6b4ec2d598e6 (11.10.2026). Копие, не импорт: двете репа не се
# виждат в CI. Ако Control Center смени схемата, тук се сменя ръчно — и тестът
# на договора по-долу казва къде се разминаваме.
class TicketIn(BaseModel):
    category: Literal["bug", "incident", "recommendation"]
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    contact: str | None = Field(default=None, max_length=320)


class FakeCockpit:
    """Control Center на ужким: записва заявките, отговаря както му кажем."""

    def __init__(self, *responses):
        self.requests: list[httpx.Request] = []
        self._responses = list(responses) or [(201, {"reference": "T-000001", "status": "new"})]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        spec = self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        if isinstance(spec, Exception):
            raise spec
        code, body, *rest = spec
        headers = rest[0] if rest else {}
        # Истинският Control Center валидира тялото — и ужкимният трябва.
        if code == 201:
            TicketIn.model_validate_json(request.content)
        return httpx.Response(code, json=body, headers=headers)


@pytest.fixture()
def cockpit(monkeypatch):
    """Включва препращането и подменя транспорта. Връща фабрика за FakeCockpit."""
    from app.core.config import settings
    from app.modules.support import forwarder

    monkeypatch.setattr(settings, "COCKPIT_URL", URL)
    monkeypatch.setattr(settings, "COCKPIT_APP_TOKEN", TOKEN)

    def install(*responses) -> FakeCockpit:
        fake = FakeCockpit(*responses)
        monkeypatch.setattr(forwarder, "_transport", httpx.MockTransport(fake))
        return fake

    return install


@pytest.fixture()
def no_network(monkeypatch):
    """При НЕнастроено препращане никой не бива да пипа мрежата."""
    from app.modules.support import forwarder

    def boom(request):
        raise AssertionError(f"заявка навън при ненастроено препращане: {request.url}")

    monkeypatch.setattr(forwarder, "_transport", httpx.MockTransport(boom))


def _auth(client, email="report@example.com"):
    return {"Authorization": f"Bearer {register_and_login(client, email)}"}


def _report(**over):
    data = {
        "category": "bug",
        "subject": "Дневникът не се отваря",
        "message": "Натискам „Дневник“ и екранът остава бял.",
        "page": "accounting",
    }
    data.update(over)
    return data


def _row(report_id):
    from app.core.database import SessionLocal
    from app.modules.support.models import SupportReport

    with SessionLocal() as db:
        row = db.get(SupportReport, uuid.UUID(str(report_id)))
        db.expunge(row)
        return row


def _count_rows():
    from sqlalchemy import func, select

    from app.core.database import SessionLocal
    from app.modules.support.models import SupportReport

    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(SupportReport))


# ── GET /support/config ──────────────────────────────────────────────────────


def test_config_bez_vhod_kazva_ne_e_nastroeno(client):
    r = client.get("/api/v1/support/config")
    assert r.status_code == 200
    # Точно низът, който `deploy.sh` търси с grep — компактен JSON, без интервали.
    assert r.text == '{"configured":false}'


def test_config_nastroeno_ne_izdava_adres_i_token(client, cockpit):
    cockpit()
    r = client.get("/api/v1/support/config")
    assert r.status_code == 200
    assert '"configured":true' in r.text
    assert TOKEN not in r.text and "cockpit" not in r.text


def test_samo_adres_ili_samo_token_ne_e_nastroeno(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "COCKPIT_URL", URL)
    assert client.get("/api/v1/support/config").json() == {"configured": False}
    monkeypatch.setattr(settings, "COCKPIT_URL", "")
    monkeypatch.setattr(settings, "COCKPIT_APP_TOKEN", TOKEN)
    assert client.get("/api/v1/support/config").json() == {"configured": False}


@pytest.mark.parametrize(
    ("env", "url", "expected"),
    [
        ("staging", "http://cockpit.example.test", False),   # токен по чист HTTP навън
        ("production", "http://cockpit.example.test", False),
        ("staging", "https://cockpit.example.test", True),
        ("local", "http://localhost:8000", True),            # dev срещу локален Control Center
        ("local", "ftp://cockpit.example.test", False),
    ],
)
def test_http_извън_локалната_среда_не_е_настроено(env, url, expected):
    from app.core.config import Settings

    s = Settings(ENVIRONMENT=env, SECRET_KEY="k" * 48, COCKPIT_URL=url, COCKPIT_APP_TOKEN=TOKEN)
    assert s.support_forwarding_configured is expected


# ── POST /support/report: вход и валидация ───────────────────────────────────


def test_doklad_iska_vhod(client, no_network):
    r = client.post("/api/v1/support/report", json=_report())
    assert r.status_code in (401, 403)
    assert _count_rows() == 0


@pytest.mark.parametrize(
    ("over", "field"),
    [
        ({"category": "praise"}, "category"),
        ({"subject": "аб"}, "subject"),
        ({"subject": "   а   "}, "subject"),        # дълго с интервалите, късо без тях
        ({"message": "    "}, "message"),
        ({"message": "х" * 3501}, "message"),
        ({"subject": "т" * 201}, "subject"),
        ({"page": "p" * 201}, "page"),
    ],
)
def test_nevaliden_doklad_e_422_i_ne_se_zapisva(client, no_network, over, field):
    r = client.post("/api/v1/support/report", json=_report(**over), headers=_auth(client))
    assert r.status_code == 422
    # Уебът превежда грешката по `loc` и `type` — полето трябва да е назовано.
    assert any(field in e["loc"] for e in r.json()["detail"])
    assert _count_rows() == 0


# ── Записът е първи, препращането — второ ────────────────────────────────────


def test_nenastroeno_dokladat_ostava_v_bazata_bez_zayavka_navan(client, no_network):
    r = client.post("/api/v1/support/report", json=_report(), headers=_auth(client))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["forwarded"] is False
    assert body["status"] == "pending"
    assert body["reference"] is None

    row = _row(body["id"])
    assert row.forward_status == "pending"
    assert row.attempts == 0
    assert row.category == "bug"
    assert row.subject == "Дневникът не се отваря"
    assert row.user_id is not None
    assert row.created_at is not None


def test_uspeh_vrashta_nomera_na_tiketa_i_dogovorat_e_spazen(client, cockpit):
    fake = cockpit((201, {"reference": "T-000042", "status": "new"}))
    r = client.post("/api/v1/support/report", json=_report(), headers=_auth(client, "ana@example.com"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body == {"id": body["id"], "forwarded": True, "status": "sent", "reference": "T-000042"}

    assert len(fake.requests) == 1
    req = fake.requests[0]
    assert req.method == "POST"
    assert str(req.url) == f"{URL}/api/tickets"
    assert req.headers["x-app-token"] == TOKEN
    assert req.headers["x-submitter-ip"]           # адресът на подателя, не празно
    ticket = TicketIn.model_validate_json(req.content)  # точно схемата на получателя
    assert ticket.category == "bug"
    assert ticket.title == "Дневникът не се отваря"
    assert "екранът остава бял" in ticket.body
    assert f"AIFOS доклад: {body['id']}" in ticket.body
    assert "Екран: accounting" in ticket.body
    assert ticket.contact == "ana@example.com"

    row = _row(body["id"])
    assert row.forward_status == "sent"
    assert row.reference == "T-000042"
    assert row.attempts == 1
    assert row.sent_at is not None


def test_429_ostava_za_povtorenie_i_ne_kazva_izprateno(client, cockpit):
    """Control Center отказа по квота → потребителят НЕ получава „изпратено“."""
    fake = cockpit((429, {"detail": "Твърде много сигнали"}, {"Retry-After": "600"}))
    r = client.post("/api/v1/support/report", json=_report(), headers=_auth(client))
    assert r.status_code == 201
    body = r.json()
    assert body["forwarded"] is False
    assert body["status"] == "pending"
    assert body["reference"] is None
    assert len(fake.requests) == 1

    row = _row(body["id"])
    assert row.forward_status == "pending"
    assert row.attempts == 1
    assert "429" in row.last_error
    assert row.claimed_until is None
    # Retry-After е спазено: следващият опит е след ~10 минути, не след минута.
    next_at = row.next_attempt_at.replace(tzinfo=dt.UTC) if row.next_attempt_at.tzinfo is None \
        else row.next_attempt_at
    assert next_at - dt.datetime.now(dt.UTC) > dt.timedelta(minutes=9)


@pytest.mark.parametrize(
    "failure",
    [
        (503, {"detail": "maintenance"}),
        (500, {"detail": "boom"}),
        (401, {"detail": "Непознат токен"}),     # грешна настройка — поправя се и тръгва
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
    ],
)
def test_vremenen_otkaz_se_povtarya_ot_opashkata_i_dava_edin_tiket(client, cockpit, failure):
    from app.modules.support import forwarder

    fake = cockpit(failure, (201, {"reference": "T-000007", "status": "new"}))
    r = client.post("/api/v1/support/report", json=_report(), headers=_auth(client))
    report_id = r.json()["id"]
    assert r.json()["forwarded"] is False
    assert _row(report_id).forward_status == "pending"

    # Редът още не е дошъл (изчакване) → цикълът не праща.
    assert forwarder.forward_due() == 0
    assert len(fake.requests) == 1

    _make_due(report_id)
    assert forwarder.forward_due() == 1
    row = _row(report_id)
    assert row.forward_status == "sent"
    assert row.reference == "T-000007"
    assert row.attempts == 2
    assert row.last_error is None

    # Идемпотентност: пратеното не се праща пак, колкото и обороти да минат.
    _make_due(report_id)
    assert forwarder.forward_due() == 0
    assert len(fake.requests) == 2


def test_422_ot_control_center_e_okonchatelen_otkaz(client, cockpit):
    from app.modules.support import forwarder

    fake = cockpit((422, {"detail": [{"msg": "bad"}]}))
    r = client.post("/api/v1/support/report", json=_report(), headers=_auth(client))
    report_id = r.json()["id"]
    assert r.json() == {"id": report_id, "forwarded": False, "status": "rejected", "reference": None}

    _make_due(report_id)
    assert forwarder.forward_due() == 0
    assert len(fake.requests) == 1          # не се повтаря
    assert _row(report_id).forward_status == "rejected"


def test_chakashtite_tragvat_shtom_se_nastroi(client, no_network, cockpit):
    """Доклад от среда без токен не се губи: тръгва при първия оборот след настройката."""
    from app.core.config import settings
    from app.modules.support import forwarder

    url, token = settings.COCKPIT_URL, settings.COCKPIT_APP_TOKEN
    settings.COCKPIT_URL = settings.COCKPIT_APP_TOKEN = ""
    try:
        r = client.post("/api/v1/support/report", json=_report(), headers=_auth(client))
        assert r.json()["forwarded"] is False
        assert forwarder.forward_due() == 0
    finally:
        settings.COCKPIT_URL, settings.COCKPIT_APP_TOKEN = url, token

    fake = cockpit((201, {"reference": "T-000100", "status": "new"}))
    assert forwarder.forward_due() == 1
    assert len(fake.requests) == 1
    assert _row(r.json()["id"]).reference == "T-000100"


def test_zaet_red_ne_se_vzima_ot_vtori_proces(client, no_network):
    """Няколко uvicorn работника = няколко цикъла. Един ред — един изпращач."""
    from app.core.database import SessionLocal
    from app.modules.support import forwarder

    r = client.post("/api/v1/support/report", json=_report(), headers=_auth(client))
    report_id = uuid.UUID(r.json()["id"])
    now = dt.datetime.now(dt.UTC)
    with SessionLocal() as a, SessionLocal() as b:
        assert forwarder._claim(a, report_id, now) is True
        assert forwarder._claim(b, report_id, now) is False
        # След изтичането на заемането (процесът е умрял по средата) редът е свободен.
        later = now + dt.timedelta(minutes=10)
        assert forwarder._claim(b, report_id, later) is True


def test_drujestvoto_se_zakacha_samo_za_chlen(client, cockpit):
    fake = cockpit()
    headers = _auth(client, "owner@example.com")
    company = client.post("/api/v1/companies", headers=headers, json={"name": "Акме ЕООД"}).json()
    r = client.post(
        "/api/v1/support/report", json=_report(),
        headers={**headers, "X-Company-Id": company["id"]},
    )
    assert str(_row(r.json()["id"]).company_id) == company["id"]
    assert "Дружество: Акме ЕООД" in TicketIn.model_validate_json(fake.requests[-1].content).body

    stranger = _auth(client, "stranger@example.com")
    r = client.post(
        "/api/v1/support/report", json=_report(),
        headers={**stranger, "X-Company-Id": company["id"]},
    )
    assert r.status_code == 201
    assert _row(r.json()["id"]).company_id is None
    assert "Акме" not in TicketIn.model_validate_json(fake.requests[-1].content).body


def test_x_submitter_ip_e_adresat_ot_nginx(client, cockpit, monkeypatch):
    """Същият адрес, който ползва ограничението на входа (`rate_limit.client_ip`)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_PROXY_HEADER", True)
    fake = cockpit()
    headers = _auth(client)
    r = client.post(
        "/api/v1/support/report", json=_report(),
        headers={**headers, "X-Real-IP": "203.0.113.7"},
    )
    assert fake.requests[-1].headers["x-submitter-ip"] == "203.0.113.7"
    assert _row(r.json()["id"]).submitter_ip == "203.0.113.7"


def test_tavan_na_dokladite_ot_edin_potrebitel(client, no_network, monkeypatch):
    from app.core.config import settings
    from app.core.rate_limit import reset_all_limiters

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "SUPPORT_REPORT_RATE_LIMIT", 2)
    reset_all_limiters()
    try:
        headers = _auth(client)
        for _ in range(2):
            assert client.post("/api/v1/support/report", json=_report(), headers=headers).status_code == 201
        r = client.post("/api/v1/support/report", json=_report(), headers=headers)
        assert r.status_code == 429
        assert "Твърде много доклада" in r.json()["detail"]
        assert _count_rows() == 2
    finally:
        reset_all_limiters()


# ── Сглобяването на тикета ───────────────────────────────────────────────────


def test_naj_dalgiyat_doklad_se_pobira_v_tiketa():
    from app.modules.support.forwarder import build_ticket
    from app.modules.support.models import SupportReport

    report = SupportReport(
        id=uuid.uuid4(), category="incident", subject="т" * 200, message="х" * 3500, page="p" * 200,
    )
    ticket = build_ticket(report, contact="a@b.bg", company_name="Д" * 255, environment="production")
    parsed = TicketIn.model_validate(ticket)
    assert len(parsed.body) <= 4000
    assert parsed.body.endswith("Среда: production")
    assert f"AIFOS доклад: {report.id}" in parsed.body


# ── Фоновият цикъл ───────────────────────────────────────────────────────────


def test_ciklat_vika_forward_due_i_spira(monkeypatch):
    from app.core.config import settings
    from app.modules.support import forwarder

    monkeypatch.setattr(settings, "SUPPORT_FORWARD_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(forwarder, "_MIN_INTERVAL_SECONDS", 0)   # без 5 s чакане между оборотите
    calls = []

    async def scenario():
        stop = asyncio.Event()

        def fake_due():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("един лош оборот")   # не бива да спре цикъла
            stop.set()
            return 0

        monkeypatch.setattr(forwarder, "forward_due", fake_due)
        await asyncio.wait_for(forwarder.run_forwarder_loop(stop), timeout=5)

    asyncio.run(scenario())
    assert len(calls) == 2


def test_prilozhenieto_puska_cikala_pri_start(monkeypatch):
    """Опашката без runner е опашка, която никой не изпразва."""
    from fastapi.testclient import TestClient

    from app.core.config import settings
    from app.main import create_app
    from app.modules.support import forwarder

    started, stopped = [], []

    async def fake_loop(stop):
        started.append(1)
        await stop.wait()
        stopped.append(1)

    monkeypatch.setattr(settings, "SUPPORT_FORWARDER_ENABLED", True)
    monkeypatch.setattr(forwarder, "run_forwarder_loop", fake_loop)
    with TestClient(create_app()) as c:
        assert c.get("/api/v1/support/config").status_code == 200
    assert started == [1]
    assert stopped == [1]


def _make_due(report_id):
    """Премества следващия опит в миналото — вместо да чакаме изчакването."""
    from sqlalchemy import update

    from app.core.database import SessionLocal
    from app.modules.support.models import SupportReport

    with SessionLocal() as db:
        db.execute(
            update(SupportReport)
            .where(SupportReport.id == uuid.UUID(str(report_id)))
            .values(next_attempt_at=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1))
        )
        db.commit()
