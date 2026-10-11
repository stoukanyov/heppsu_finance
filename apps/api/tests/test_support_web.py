"""„Съобщи проблем“ в уеб интерфейса: входът, текстовете, честността на резултата.

Логиката без DOM (`SUPPORT:BEGIN … SUPPORT:END` в `app/web/index.html`) се
пуска в node — същият код, който върви в браузъра, не копие. Грешките от
валидацията идват от истинския API (TestClient), не са написани на ръка: така
тестът хваща и промяна в `type`/`loc` на Pydantic, която би върнала английски
текст на потребителя.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import register_and_login

INDEX = Path(__file__).resolve().parents[1] / "app" / "web" / "index.html"
NODE = shutil.which("node")


def _html() -> str:
    return INDEX.read_text(encoding="utf-8")


def _support_js() -> str:
    m = re.search(r"/\* SUPPORT:BEGIN.*?\*/(.*?)/\* SUPPORT:END \*/", _html(), re.S)
    assert m, "блокът SUPPORT:BEGIN … SUPPORT:END липсва в index.html"
    return m.group(1)


def _node(expr: str):
    """Изпълнява JS израз след блока и връща резултата като JSON."""
    if NODE is None:
        if os.environ.get("CI"):
            # В CI node има (ubuntu-latest); липсата му е повреда, не причина за пропуск.
            raise RuntimeError("CI без node — тестовете на уеб формата не могат да се пуснат")
        pytest.skip("няма node локално; върви в CI")
    script = _support_js() + f"\nprocess.stdout.write(JSON.stringify({expr}));\n"
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# ── Входът ───────────────────────────────────────────────────────────────────


def test_vhodat_e_v_ramkata_sled_vhod_ne_v_ekrana_za_vhod():
    html = _html()
    shell, entry = html.index('<div id="shell">'), html.index('id="nav-report"')
    assert shell < entry < html.index('id="userchip"'), "входът трябва да е в страничната лента на рамката"
    assert "openSupportReport()" in html
    assert ">Съобщи проблем<" in html


def test_formata_pishe_v_pravilniya_marshrut():
    assert "api('/support/report',{method:'POST'" in _html()


# ── Езиците ──────────────────────────────────────────────────────────────────


def test_vseki_ezik_ima_vsichki_tekstove():
    """Нов език в SUPPORT_T без някой текст (или грешка) = ред на английски/празно в UI."""
    result = _node(
        "Object.fromEntries(Object.entries(SUPPORT_T).map(([k,v])=>"
        "[k, Object.keys(SUPPORT_T.bg).filter(x=>!(x in v) || !String(v[x]).trim())]))"
    )
    assert "bg" in result
    assert result == {lang: [] for lang in result}
    # Езиците на уеба = езиците в <html lang> на страницата (засега само bg).
    assert re.search(r'<html lang="bg">', _html())


# ── Честният резултат ────────────────────────────────────────────────────────


def test_izprateno_samo_pri_forwarded_true():
    ok = _node("supportResult({forwarded:true,status:'sent',reference:'T-000042'}, supportT('bg'))")
    assert ok["kind"] == "ok"
    assert "Изпратено" in ok["text"] and "T-000042" in ok["text"]

    for resp in ("{forwarded:false,status:'pending',reference:null}",
                 "{forwarded:false,status:'rejected',reference:null}"):
        r = _node(f"supportResult({resp}, supportT('bg'))")
        assert r["kind"] == "wait"
        assert "Изпратено" not in r["text"] and "изпратено" not in r["text"]
        assert "Приехме" in r["text"]


def test_429_i_mrezha_kazvat_che_ne_e_prieto():
    too_many = _node("supportErrors({status:429, detail:'x'}, supportT('bg'))")
    assert "Твърде много доклада" in too_many["_form"]
    offline = _node("supportErrors(new TypeError('Failed to fetch'), supportT('bg'))")
    assert "НЕ е приет" in offline["_form"]


@pytest.mark.parametrize(
    ("over", "field", "expected"),
    [
        ({"subject": "аб"}, "subject", "поне 3 знака"),
        ({"subject": "   а   "}, "subject", "поне 3 знака"),
        ({"subject": "т" * 201}, "subject", "до 200 знака"),
        ({"message": "   "}, "message", "Опиши какво се случи"),
        ({"message": "х" * 3501}, "message", "до 3500 знака"),
        ({"category": "praise"}, "category", "Избери вид"),
    ],
)
def test_422_ot_istinskiya_api_se_prevezhda_po_pole(client, over, field, expected):
    token = register_and_login(client, "web@example.com")
    body = {"category": "bug", "subject": "Тема на доклада", "message": "Текст", **over}
    r = client.post("/api/v1/support/report", json=body, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 422

    err = json.dumps({"status": 422, "detail": r.json()["detail"]}, ensure_ascii=False)
    shown = _node(f"supportErrors({err}, supportT('bg'))")
    assert expected in shown[field]
    # Нищо от английския текст на Pydantic не стига до потребителя.
    assert not re.search(r"[A-Za-z]{4,}", " ".join(shown.values()))


def test_proverkata_v_brauzara_e_sashtata_kato_na_servara():
    from app.modules.support import schemas

    limits = _node("SUPPORT_LIMITS")
    assert limits == {
        "subject_min": schemas.SUBJECT_MIN,
        "subject_max": schemas.SUBJECT_MAX,
        "message_max": schemas.MESSAGE_MAX,
        "page_max": schemas.PAGE_MAX,
    }
    errs = _node("supportValidate({category:'bug',subject:'  аб ',message:'  '}, supportT('bg'))")
    assert set(errs) == {"subject", "message"}
    assert _node("supportValidate({category:'incident',subject:'Тема',message:'x'}, supportT('bg'))") == {}
