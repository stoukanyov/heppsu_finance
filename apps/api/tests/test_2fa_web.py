"""Екранът за 2FA в `app/web/index.html` — без DOM, по съдържанието на файла.

Уебът е един файл без стъпка на сглобяване, тоест няма компилатор, който да
хване изпусната връзка между бутон и крайна точка. Проверките тук са за
нещата, които мълчаливо чупят потока и се виждат само в браузъра — два от тях
бяха намерени точно така и са записани отдолу поименно.
"""
from pathlib import Path

import pytest

INDEX = Path(__file__).resolve().parents[1] / "app" / "web" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return INDEX.read_text(encoding="utf-8")


def test_vtorata_stapka_e_otdelna_karta_v_ekrana_za_vhod(html):
    assert '<div class="card" id="au-2fa"' in html
    assert 'id="au-code"' in html and 'id="au-code-submit"' in html
    # Паролата и кодът не стоят едновременно на екрана.
    assert "function showAuthStep(step)" in html


def test_vhodat_cheke_mfa_required(html):
    """Първата стъпка се различава по `mfa_required`, не по липсващ access токен."""
    assert "if(r.mfa_required){ mfaToken=r.mfa_token; showAuthStep('code'); return; }" in html


def test_mezhdinniyat_token_ne_se_pazi_v_localstorage(html):
    """Той живее 5 минути и не отваря нищо — няма какво да остава след таба."""
    start = html.index("let mfaToken=null;")
    end = html.index("/* ---------- shell:", start)
    assert "localStorage" not in html[start:end]


def test_greshen_kod_ne_izhvurlya_obratno_pri_parolata(html):
    """Намерено в браузъра: 401 от втората стъпка минаваше през общия `logout()`.

    Всяка печатна грешка в кода връщаше екрана за парола и човек трябваше да
    влиза отначало.
    """
    assert "path!=='/auth/login' && path!=='/auth/login/2fa'" in html


def test_izklyuchvaneto_iska_parola_i_kod(html):
    assert "id=\"sd-pass\"" in html and "id=\"sd-code\"" in html
    assert "'/auth/2fa/disable'" in html


def test_qr_kodat_idva_ot_survara(html):
    """Тайната не минава през чужда услуга за рисуване на QR кодове."""
    assert "document.getElementById('sec-qr').innerHTML=setup.qr_svg;" in html
    for foreign in ("chart.googleapis.com", "qrserver.com", "api.qrcode"):
        assert foreign not in html


def test_rezervnite_kodove_se_pokazvat_i_svalyat(html):
    assert "function secShowRecoveryCodes(codes)" in html
    assert "aifos-rezervni-kodove.txt" in html
    assert "Няма да бъдат показани отново." in html


def test_ekranat_raboti_bez_izbrano_druzhestvo(html):
    """Нов акаунт още няма дружество, а трябва да може да си включи 2FA."""
    assert "if(!companyId && view!=='firm' && view!=='security'){" in html
    assert "v==='security'" in html  # и при смяна на адреса (hashchange)


def test_ekranat_e_v_menyuto_bez_pravo_ot_rbac(html):
    """Защитата е на потребителя, не на дружеството — не зависи от роля."""
    assert "['security','Защита на профила','shield']," in html
    assert "security:viewSecurity" in html


def test_izhodat_vrushta_parvata_stapka(html):
    """Иначе следващият вход започва направо от полето за код, без междинен токен."""
    assert "mfaToken=null; showAuthStep('password');" in html
