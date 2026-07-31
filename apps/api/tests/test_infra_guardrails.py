"""Тестове, кръстени на повредите, които пазят.

Всеки тест тук съществува заради конкретен намерен дефект, а не за пълнота. Ако
някой падне, съобщението му казва какво е боляло и защо поправката е била нужна —
за да не бъде „оправена“ обратно от следващия, който мине оттук.

Източникът на находките е статичният анализ (`ruff` с правилата S/DTZ/ASYNC и
`bandit`), пуснат върху цялото хранилище на 31.07.2026.
"""
from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import logging
import pathlib
from zoneinfo import ZoneInfo

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[3]
_API = _REPO / "apps" / "api"


def _load_script(path: pathlib.Path, name: str):
    """Зарежда самостоятелен скрипт от `infra/` като модул (той не е пакет)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ─────────────────────────────────────────────────────────────────────────────
# DTZ011 — „днес“ по часовника на сървъра вместо по часовника на фирмата
# ─────────────────────────────────────────────────────────────────────────────
def test_dtz011_dneshnata_data_e_po_sofiysko_vreme_a_ne_po_utc():
    """`business_today()` брои дните в Europe/Sofia, не в зоната на машината.

    Повредата: production сървърът работи в UTC. `date.today()` там между 00:00 и
    03:00 софийско време връща ВЧЕРАШНАТА дата. Сторно, осчетоводено в 00:30 на
    1 август, получава дата 31 юли и влиза в юлския ДДС дневник — период, чиято
    декларация вече може да е подадена в НАП.
    """
    from app.core.clock import business_today

    assert business_today() == dt.datetime.now(tz=ZoneInfo("Europe/Sofia")).date()


def test_dtz011_polunosht_v_sofia_i_v_utc_sa_razlichni_dni():
    """Доказва, че разликата е реална, а не теоретична.

    Ако този тест някога стане безсмислен (нулево отместване), значи е сменена
    часовата зона на фирмата — и всичко останало в модула трябва да се преразгледа.
    """
    from app.core.clock import business_now

    # 1 август 2026, 00:30 софийско време — това е 31 юли, 21:30 UTC.
    sofia = dt.datetime(2026, 8, 1, 0, 30, tzinfo=ZoneInfo("Europe/Sofia"))
    assert sofia.date() != sofia.astimezone(dt.UTC).date(), (
        "в този момент датата по София и датата по UTC съвпадат — "
        "проверката вече не доказва нищо"
    )
    assert business_now().utcoffset() != dt.timedelta(0), (
        "часовата зона на фирмата е UTC — тогава `business_today()` не пази от нищо"
    )


def test_dtz011_niama_date_today_v_prilozhenieto():
    """Никъде в кода на приложението не се вика `date.today()`.

    Повредата: една забравена употреба е достатъчна, за да се появи документ с
    дата от предходния данъчен период. Затова правилото се проверява върху целия
    изходен код, а не само там, където беше поправено.
    """
    # Търсенето е по синтактично дърво, а не по текст: коментарите и docstring-овете
    # в `clock.py` обясняват точно тази повреда и биха дали лъжливи попадения.
    offenders = []
    for path in list((_API / "app").rglob("*.py")) + list((_API / "scripts").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "today":
                continue
            owner = func.value
            owner_name = owner.attr if isinstance(owner, ast.Attribute) else getattr(owner, "id", "")
            if owner_name == "date":
                offenders.append(f"{path.relative_to(_REPO)}:{node.lineno}")
    assert not offenders, (
        "`date.today()` връща деня по часовника на сървъра (UTC), не по часовника "
        "на фирмата (Europe/Sofia). Ползвай `app.core.clock.business_today()`. "
        f"Намерено в: {', '.join(offenders)}"
    )


def test_dtz011_nevalidna_chasova_zona_ne_chupi_prilozhenieto():
    """Грешно име на зона дава българско време, а не срив при стартиране.

    Часовата зона не е тайна — по-добре е сгрешена настройка да върне разумна
    стойност, отколкото приложението да не тръгне и цялата фирма да остане без
    достъп до счетоводството си.
    """
    from app.core import clock
    from app.core.config import settings

    original = settings.BUSINESS_TIMEZONE
    try:
        settings.BUSINESS_TIMEZONE = "Europe/Несъществуваща"
        assert clock.business_timezone().key == "Europe/Sofia"
    finally:
        settings.BUSINESS_TIMEZONE = original


# ─────────────────────────────────────────────────────────────────────────────
# S110 — одитният журнал мълчеше, когато записът се проваля
# ─────────────────────────────────────────────────────────────────────────────
def test_s110_provalen_odit_se_zapisva_v_dnevnika_a_ne_se_premalchava(
    client, monkeypatch, caplog
):
    """Провалът на одитен запис оставя следа в лога.

    Повредата: `except Exception: pass` в `AuditMiddleware`. Журналът може да е с
    дупки — пълна база, заключена таблица, изтекла връзка — и никой не разбира,
    докато някой не поиска одитната следа за спорен период. Заявката пак не бива да
    се чупи заради одита; затова изключението се поглъща, но се ЗАПИСВА.
    """
    from app.modules.audit import middleware

    def _explode(*args, **kwargs):
        raise RuntimeError("одитната таблица е недостъпна")

    monkeypatch.setattr(middleware, "_record", _explode)

    with caplog.at_level(logging.ERROR, logger=middleware.__name__):
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "odit-provall@example.com", "password": "supersecret1",
                  "full_name": "Тест"},
        )

    assert response.status_code == 201, "одитът счупи заявката — това е по-лошо от дупка в журнала"
    assert any("одитният запис" in r.message.lower() for r in caplog.records), (
        "провалът на одита не е записан никъде — журналът може да е с дупки, "
        "без никой да разбере"
    )


# ─────────────────────────────────────────────────────────────────────────────
# S310 — скриптовете отваряха всякаква схема, включително `file:`
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "script, name",
    [
        (_REPO / "infra" / "ci" / "smoke.py", "smoke"),
        (_REPO / "infra" / "demo" / "seed_demo.py", "seed_demo"),
    ],
)
@pytest.mark.parametrize("bad", ["file:///etc/passwd", "127.0.0.1:8080", "ftp://x/y", ""])
def test_s310_skriptovete_otkazvat_adres_koyto_ne_e_http(script, name, bad):
    """`urlopen` отваря и `file:` — тоест smoke тест може да „мине“ срещу файл.

    Повредата: адресът идва отвън (аргумент, променлива в CI, копи-пейст). Ако
    схемата не е проверена, `file:///…` се чете от диска и проверката минава,
    докато разгърнатата среда е счупена. `seed_demo.py` при това и ПИШЕ данни.
    """
    module = _load_script(script, f"_guardrail_{name}")
    with pytest.raises(SystemExit):
        module.require_http_url(bad)


@pytest.mark.parametrize(
    "script, name",
    [
        (_REPO / "infra" / "ci" / "smoke.py", "smoke_ok"),
        (_REPO / "infra" / "demo" / "seed_demo.py", "seed_demo_ok"),
    ],
)
def test_s310_normalen_adres_minava(script, name):
    """Проверката не бива да е толкова строга, че да спре обичайната употреба."""
    module = _load_script(script, f"_guardrail_{name}")
    assert module.require_http_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    assert module.require_http_url("https://aifos.example.com") == "https://aifos.example.com"


# ─────────────────────────────────────────────────────────────────────────────
# Самата порта: CI трябва да ПУСКА проверките, не само да ги има в хранилището
# ─────────────────────────────────────────────────────────────────────────────
def test_ci_pusca_statichen_analiz():
    """Конфигурация без задача, която я пуска, е документация, не защита."""
    workflows = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (_REPO / ".github" / "workflows").glob("*.yml")
    )
    assert "ruff check" in workflows, "CI не пуска ruff"
    assert "bandit" in workflows, "CI не пуска bandit"
    assert "--severity-level medium" in workflows, (
        "bandit е пуснат без праг — тогава минава с предупреждения, които никой не чете"
    )


def test_ci_pusca_dinamichen_analiz():
    """Статичният анализ не хваща защита, която не е закачена за маршрута.

    Повредата, която динамичната задача пази: код, който ИЗГЛЕЖДА правилно при
    четене — има проверка за достъп, има маршрут — но при пускане маршрутът не се
    регистрира или проверката не се прилага. Затова приложението се вдига наистина
    и се пита на живо.
    """
    workflows = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (_REPO / ".github" / "workflows").glob("*.yml")
    )
    assert "Динамичен анализ" in workflows, "CI няма задача за динамичен анализ"
    assert "openapi.json" in workflows, "CI не проверява, че маршрутите изобщо се закачат"
    assert "401" in workflows, "CI не проверява на живо, че непознат не влиза"
