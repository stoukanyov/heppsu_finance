"""Подставените данни не са резервен вариант — нито за банките, нито за AI.

На 26.10.2026 production работеше с подставен банков конектор („УниКредит
Булбанк (демо)“ и движения по 120,50 EUR на 5-о, 15-о и 25-о число) и с
подставен AI (измислени данъчна основа, ДДС, сметка по ЗКПО и право на данъчен
кредит). И двете бяха резервният вариант при липсващи ключове: `live if
available else stub` и `anthropic if key else stub`. Банковите движения влизат
в дневника и в съпоставянето, а разпознатите полета — в document_extractions;
после нищо не ги отличава от истински данни.

Тези тестове държат вратата затворена: „няма ключове“ дава ясна грешка, а
подставеното иска изрично искане и е забранено в production.
"""
import pytest

from app.core.config import Settings
from tests.conftest import register_and_login

ACC = "/api/v1/accounting"
AI = "/api/v1/ai"
BANK = "/api/v1/banking"
DOC = "/api/v1/documents"
PDF = b"%PDF-1.4\n%faktura\n"


def _nastroiki(**kw) -> Settings:
    bazovi = {"SECRET_KEY": "x" * 40, "ENVIRONMENT": "test"}
    return Settings(**{**bazovi, **kw})


def _setup(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    cid = client.post("/api/v1/companies", headers=auth, json={"name": "Акме ЕООД"}).json()["id"]
    return {**auth, "X-Company-Id": cid}


def _bez_banka(monkeypatch):
    """Среда без банкови ключове и без изрично искане за демо."""
    from app.modules.banking.connectors import factory

    monkeypatch.setattr(factory.settings, "BANK_PROVIDER", "auto", raising=False)
    monkeypatch.setattr(factory.settings, "GOCARDLESS_SECRET_ID", "", raising=False)
    monkeypatch.setattr(factory.settings, "GOCARDLESS_SECRET_KEY", "", raising=False)


def _bez_ai(monkeypatch):
    """Среда без ключ за Anthropic и без изрично искане за подставен AI."""
    from app.modules.ai import llm

    monkeypatch.setattr(llm.settings, "AI_PROVIDER", "auto", raising=False)
    monkeypatch.setattr(llm.settings, "ANTHROPIC_API_KEY", "", raising=False)


# --------------------------------------------------------------------------
# Банки
# --------------------------------------------------------------------------
def test_auto_bez_klyuchove_ne_vrushta_demo_banka():
    """„auto“ значи „реален доставчик, ако има ключове“ — не „покажи демо банки“."""
    assert _nastroiki(BANK_PROVIDER="auto").bank_provider == "off"
    assert _nastroiki(
        BANK_PROVIDER="auto", GOCARDLESS_SECRET_ID="id", GOCARDLESS_SECRET_KEY="key"
    ).bank_provider == "live"


def test_izrichno_izkluchen_dostavchik_ostava_izkluchen():
    """`off` е решение, не „auto“ — ключовете не го надделяват."""
    s = _nastroiki(
        BANK_PROVIDER="off", GOCARDLESS_SECRET_ID="id", GOCARDLESS_SECRET_KEY="key"
    )
    assert s.bank_provider == "off"
    assert _nastroiki(AI_PROVIDER="off", ANTHROPIC_API_KEY="sk-x").ai_provider == "off"
    assert _nastroiki(
        STORE_PROVIDER="off", APPLE_ISSUER_ID="i", APPLE_KEY_ID="k",
        APPLE_PRIVATE_KEY_PATH="/tmp/k.p8",
    ).store_provider_for("APP_STORE") == "off"


def test_production_ne_dava_demo_banka_dori_izrichno():
    """В production `BANK_PROVIDER=stub` не включва демото; в демо средата — да."""
    assert _nastroiki(BANK_PROVIDER="stub", ENVIRONMENT="production").bank_provider == "off"
    assert _nastroiki(BANK_PROVIDER="stub", ENVIRONMENT="staging").bank_provider == "stub"


def test_nesvurzana_banka_dava_greshka_a_ne_konektor(monkeypatch):
    from app.modules.banking.connectors.factory import BankNotConnected, get_bank_connector

    _bez_banka(monkeypatch)
    with pytest.raises(BankNotConnected) as exc:
        get_bank_connector()
    # Съобщението казва КАКВО да се зададе и какво да се прави дотогава.
    assert "GOCARDLESS_SECRET_ID" in str(exc.value)
    assert "GOCARDLESS_SECRET_KEY" in str(exc.value)
    assert "MT940" in str(exc.value)


def test_izrichniyat_provider_stub_ne_e_zadna_vrata(monkeypatch):
    """`provider=STUB` от заявката не заобикаля режима на средата."""
    from app.modules.banking.connectors.factory import BankNotConnected, get_bank_connector

    _bez_banka(monkeypatch)
    with pytest.raises(BankNotConnected):
        get_bank_connector("STUB")


def test_spisykut_s_dostavchici_ne_predlaga_demo_izvan_demo_sredata(monkeypatch):
    from app.modules.banking.connectors.factory import available_bank_connectors

    _bez_banka(monkeypatch)
    assert "STUB" not in {c.code for c in available_bank_connectors()}


def test_bankovite_dostavchici_kazvat_rezhima(client, monkeypatch):
    """Екранът получава режима, за да каже „не е свързана“ вместо да предложи демо."""
    h = _setup(client, "ns-bank-mode@example.com")
    _bez_banka(monkeypatch)
    body = client.get(f"{BANK}/providers", headers=h).json()
    assert body["mode"] == "off"
    assert body["active"] == ""
    assert "STUB" not in {p["code"] for p in body["providers"]}


def test_bankite_na_nesvurzan_dostavchik_sa_409(client, monkeypatch):
    """Списъкът с банки връща причината, не три демо банки."""
    h = _setup(client, "ns-bank-409@example.com")
    _bez_banka(monkeypatch)
    r = client.get(f"{BANK}/institutions?country=BG", headers=h)
    assert r.status_code == 409, r.text
    assert "GOCARDLESS_SECRET_ID" in r.json()["detail"]


def test_saglasieto_ne_zapochva_bez_dostavchik(client, monkeypatch):
    """Няма демо съгласие: иначе в базата остава връзка към банка, която я няма."""
    h = _setup(client, "ns-bank-consent@example.com")
    _bez_banka(monkeypatch)
    r = client.post(f"{BANK}/connections", headers=h, json={
        "institution_id": "STUB_DSK", "redirect_url": "https://app.example.bg/return"})
    assert r.status_code == 409, r.text
    assert client.get(f"{BANK}/connections", headers=h).json() == []


# --------------------------------------------------------------------------
# AI
# --------------------------------------------------------------------------
def test_auto_bez_klyuch_ne_dava_podstaven_ai():
    """Без ANTHROPIC_API_KEY „auto“ е изключено, не подставено."""
    assert _nastroiki(AI_PROVIDER="auto").ai_provider == "off"
    assert _nastroiki(AI_PROVIDER="auto", ANTHROPIC_API_KEY="sk-x").ai_provider == "anthropic"


def test_production_ne_dava_podstaven_ai_dori_izrichno():
    assert _nastroiki(AI_PROVIDER="stub", ENVIRONMENT="production").ai_provider == "off"
    assert _nastroiki(AI_PROVIDER="stub", ENVIRONMENT="staging").ai_provider == "stub"


def test_nenastroeniyat_ai_vdiga_greshka_a_ne_izmislya(monkeypatch):
    from app.modules.ai.llm import AiNotConfigured, get_llm_client

    _bez_ai(monkeypatch)
    with pytest.raises(AiNotConfigured) as exc:
        get_llm_client()
    assert "ANTHROPIC_API_KEY" in str(exc.value)


def test_razpoznavaneto_bez_ai_e_409_i_ne_pishe_nishto(client, monkeypatch):
    """Документът остава неразпознат, вместо да получи измислени полета."""
    h = _setup(client, "ns-ai-extract@example.com")
    doc_id = client.post(
        DOC, headers=h, files={"file": ("faktura.pdf", PDF, "application/pdf")}
    ).json()["id"]
    _bez_ai(monkeypatch)
    r = client.post(f"{AI}/documents/{doc_id}/extract", headers=h)
    assert r.status_code == 409, r.text
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_vuprosut_kum_cfo_bez_ai_e_409(client, monkeypatch):
    h = _setup(client, "ns-ai-cfo@example.com")
    _bez_ai(monkeypatch)
    r = client.post(f"{AI}/cfo/ask", headers=h, json={"question": "Как сме с парите?"})
    assert r.status_code == 409, r.text


def test_komandniyat_centar_pazi_chislata_i_kazva_che_ai_lipsva(client, monkeypatch):
    """Числата са от базата и важат без AI; анализът липсва ЯВНО."""
    h = _setup(client, "ns-ai-cc@example.com")
    _bez_ai(monkeypatch)
    r = client.get(f"{AI}/command-center", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currency"] == "EUR"
    assert body["ai_available"] is False
    assert "ANTHROPIC_API_KEY" in body["ai_note"]
    # Нищо измислено на мястото на анализа.
    assert body["summary"] == ""
    assert body["recommendations"] == [] and body["risks"] == []


def test_klasifikaciyata_bez_ai_ne_izmislya_smetka(client, monkeypatch):
    """Без AI предложението минава без класификация и казва защо.

    Подставеният клиент връщаше сметка 602, „признат разход“ и ПЪЛЕН данъчен
    кредит за всеки документ — три данъчни твърдения, изчислени от нищо.
    """
    from app.modules.ai.models import ExpenseClassification

    h = _setup(client, "ns-ai-class@example.com")
    client.post(f"{ACC}/chart/seed", headers=h)
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    doc_id = client.post(
        DOC, headers=h, files={"file": ("faktura.pdf", PDF, "application/pdf")}
    ).json()["id"]
    # Разпознаването минава с подставения AI (средата на тестовете), за да има полета.
    assert client.post(f"{AI}/documents/{doc_id}/extract", headers=h).status_code == 201

    _bez_ai(monkeypatch)
    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    assert any("ANTHROPIC_API_KEY" in w for w in body["warnings"]), body["warnings"]

    from app.core.database import SessionLocal

    with SessionLocal() as db:
        assert db.query(ExpenseClassification).count() == 0
