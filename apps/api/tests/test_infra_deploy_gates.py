"""Двата предпазителя пред production.

Правилата на Ив от 23.08.2026: всеки деплой минава първо през тест, а деплой на
production се случва само след негово одобрение. Тестовата среда тук е `preprod`.

Тестът вдига истинско git хранилище с истински „origin" и пуска `deploy.sh`
наистина. `ssh` е подставен — интересува ни решението на скрипта (пуска ли,
отказва ли), не какво прави докер оттатък. Скриптът стига до проверката за
миграции и спира там; дотогава предпазителите вече са се произнесли.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

DEPLOY_SH = Path(__file__).resolve().parents[3] / "infra" / "deploy.sh"

SSH_STUB = "#!/bin/sh\ncat >/dev/null 2>&1 || true\nexit 0\n"

# `curl` подставен, но НЕ отговаря еднакво на всичко: DoD проверката пита
# `/api/v1/support/config` (и при слабото ниво `openapi.json`) на preprod. Стъб,
# който казва „ок" на всеки адрес, би направил проверката за функцията за
# докладване безсмислена — тоест би скрил точно повредата, която тя трябва да хване.
CURL_STUB = r"""#!/usr/bin/env python3
import os, sys

adres = next((a for a in sys.argv[1:] if a.startswith("http")), "")
if adres.endswith("/api/v1/support/config"):
    otgovor = os.environ.get("FAKE_CONFIG", '{"configured":true}')
    if otgovor == "NEDOSTAPNO":
        sys.exit(7)          # curl: Failed to connect
    print(otgovor)
    sys.exit(0)
if adres.endswith("/openapi.json"):
    marshruti = os.environ.get("FAKE_MARSHRUTI", "/api/v1/support/report").split()
    print('{"paths":{' + ",".join(f'"{m}":{{}}' for m in marshruti) + '}}')
    sys.exit(0)
print("ok")
sys.exit(0)
"""


def git(*args, cwd, **kw):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, **kw
    ).stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(origin)], check=True)

    work = tmp_path / "work"
    work.mkdir()
    env_git = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(work)], check=True)
    (work / "infra").mkdir()
    (work / "infra" / "deploy.sh").write_text(DEPLOY_SH.read_text())
    (work / "infra" / "deploy.sh").chmod(0o755)
    # DoD списъкът влиза ПРЕДИ първия комит: иначе остава некомитнат и скриптът
    # отказва още на „работната директория е мръсна", вместо да стигне до
    # проверката, която тестваме.
    (work / "infra" / "dod.yml").write_text((DEPLOY_SH.parent / "dod.yml").read_text())

    def commit(message):
        (work / "file.txt").write_text(message)
        git("add", "-A", cwd=work, env=env_git)
        git("commit", "--quiet", "-m", message, cwd=work, env=env_git)
        return git("rev-parse", "--short", "HEAD", cwd=work)

    commit("първи")
    git("remote", "add", "origin", str(origin), cwd=work)
    git("push", "--quiet", "origin", "main", cwd=work, env=env_git)
    second = commit("нова функция, непроверена")
    git("push", "--quiet", "origin", "main", cwd=work, env=env_git)

    binn = tmp_path / "bin"
    binn.mkdir()
    for ime, tyalo in (("ssh", SSH_STUB), ("curl", CURL_STUB)):
        f = binn / ime
        f.write_text(tyalo)
        f.chmod(0o755)

    env = {**env_git, "PATH": f"{binn}:{os.environ['PATH']}", "AIFOS_HOST": "test-host"}
    return work, env, second


def deploy(repo, *args):
    work, env, _ = repo
    return subprocess.run(
        ["bash", "infra/deploy.sh", *args],
        cwd=work, env=env, capture_output=True, text=True,
    )


def mark_tested(repo, sha):
    work, env, _ = repo
    git("tag", "-f", f"tested/{sha}", sha, cwd=work, env=env)
    git("push", "--quiet", "--force", "origin", f"tested/{sha}", cwd=work, env=env)


def mark_dod(repo, sha):
    """Каквото слагат сесиите Security Officer и Legal Officer."""
    work, env, _ = repo
    for etiket in ("security", "legal"):
        git("tag", "-f", f"{etiket}/{sha}", sha, cwd=work, env=env)
        git("push", "--quiet", "--force", "origin", f"{etiket}/{sha}", cwd=work, env=env)


def test_neproveren_komit_ne_stiga_do_schetovodnite_danni(repo):
    """Production на AI Finance OS носи счетоводни данни на клиенти."""
    result = deploy(repo, "prod", "main", "ignored")

    assert result.returncode == 1
    assert "НЕ е минавал през preprod" in result.stderr


def test_bez_odobrenie_production_ne_trugva(repo):
    _, _, second = repo
    mark_tested(repo, second)
    mark_dod(repo, second)

    result = deploy(repo, "prod", "main")

    assert result.returncode == 1
    assert "иска одобрението на Ив" in result.stderr
    assert second in result.stderr, "трябва да покаже КОЙ комит се одобрява"


def test_odobrenie_za_drug_komit_ne_vazhi(repo):
    """Рефът се е придвижил между показването и пускането."""
    work, env, second = repo
    mark_tested(repo, second)
    mark_dod(repo, second)
    star = git("rev-parse", "--short", "HEAD~1", cwd=work)

    result = deploy(repo, "prod", "main", star)

    assert result.returncode == 1
    assert "придвижил след одобрението" in result.stderr


def test_odobrenie_za_verniya_komit_puska_napred(repo):
    """След двата предпазителя скриптът продължава към проверката за миграции."""
    _, _, second = repo
    mark_tested(repo, second)
    mark_dod(repo, second)

    result = deploy(repo, "prod", "main", second)

    assert "се съдържа в tested/" in result.stdout, result.stderr
    assert f"одобрение: {second}" in result.stdout
    assert "разрушителни миграции" in result.stdout


def test_preprod_ne_iska_nito_test_nito_odobrenie(repo):
    result = deploy(repo, "preprod", "main")

    assert "НЕ е минавал" not in result.stderr
    assert "одобрението на Ив" not in result.stderr
    assert "разрушителни миграции" in result.stdout


# ── Definition of Done ────────────────────────────────────────────────────


def test_bez_etiketi_ot_security_i_legal_production_ne_trugva(repo):
    """Ив, 23–24.08.2026: без security scan и правно ревю — няма продукция."""
    _, _, second = repo
    mark_tested(repo, second)

    result = deploy(repo, "prod", "main", second)

    assert result.returncode == 1
    assert "НЕ отговаря на Definition of Done" in result.stderr
    assert "Security Officer" in result.stderr
    assert "Legal Officer" in result.stderr


@pytest.mark.parametrize(
    "otgovor",
    [
        '{"configured":false}',     # функцията е в кода, но токенът липсва в средата
        "NEDOSTAPNO",               # preprod не отговаря — не е доказателство за нищо
        "ok",                       # чужд отговор (напр. страница по подразбиране)
    ],
)
def test_nenastroeno_dokladvane_spira_production(repo, otgovor):
    """DoD т. 1 мери НАСТРОЕНО, не „в кода“: `GET /api/v1/support/config` на preprod.

    На macOS (BSD sed) старият израз за `ochakva` даваше празен низ и
    `grep -q ""` пускаше и `{"configured":false}` — този тест не минаваше там.
    """
    work, env, second = repo
    mark_tested(repo, second)
    mark_dod(repo, second)

    result = subprocess.run(
        ["bash", "infra/deploy.sh", "prod", "main", second],
        cwd=work, env={**env, "FAKE_CONFIG": otgovor},
        capture_output=True, text=True,
    )

    assert result.returncode == 1
    assert "НЕ отговаря на Definition of Done" in result.stderr
    assert '/api/v1/support/config не върна "configured":true' in result.stderr


def test_dod_yml_se_chete_tochno_ot_deploy_sh():
    """Редовете на `deploy.sh`, които четат `dod.yml`, пуснати върху истинския файл.

    Изразите се вадят от самия скрипт, не се преписват — иначе тестът проверява
    копие, а не това, което върви. Пускат се със `sed` на машината: на macOS това
    е BSD sed, в CI — GNU; и двата трябва да прочетат едно и също.
    """
    redove = [
        line.strip()
        for line in DEPLOY_SH.read_text().splitlines()
        if line.strip().startswith(("MARSHRUT=", "CONFIG_URL=", "OCHAKVA="))
    ]
    assert len(redove) == 3, redove
    skript = "\n".join(
        ['DOD="$1"', *redove, 'printf "%s\\n%s\\n%s\\n" "$MARSHRUT" "$CONFIG_URL" "$OCHAKVA"']
    )
    out = subprocess.run(
        ["bash", "-c", skript, "dod", str(DEPLOY_SH.parent / "dod.yml")],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    assert out == ["/api/v1/support/report", "/api/v1/support/config", '"configured":true']


def test_propuskaneto_e_shumno_i_iska_tochniya_komit(repo):
    """Пропуснат DoD трябва да СЕ ВИЖДА, и да назовава комита."""
    work, env, second = repo
    mark_tested(repo, second)

    grешен = subprocess.run(
        ["bash", "infra/deploy.sh", "prod", "main", second],
        cwd=work, env={**env, "AIFOS_DOD_PROPUSNI": "0000000:друг комит"},
        capture_output=True, text=True,
    )
    assert grешен.returncode != 0
    assert "пропускането е за" in grешен.stderr

    veren = subprocess.run(
        ["bash", "infra/deploy.sh", "prod", "main", second],
        cwd=work, env={**env, "AIFOS_DOD_PROPUSNI": f"{second}:правен документ чака подпис"},
        capture_output=True, text=True,
    )
    assert "DoD Е ПРОПУСНАТ по изрично нареждане на Ив" in veren.stdout
    assert "правен документ чака подпис" in veren.stdout
