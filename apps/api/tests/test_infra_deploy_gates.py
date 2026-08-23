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
    ssh = binn / "ssh"
    ssh.write_text(SSH_STUB)
    ssh.chmod(0o755)

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


def test_neproveren_komit_ne_stiga_do_schetovodnite_danni(repo):
    """Production на AI Finance OS носи счетоводни данни на клиенти."""
    result = deploy(repo, "prod", "main", "ignored")

    assert result.returncode == 1
    assert "НЕ е минавал през preprod" in result.stderr


def test_bez_odobrenie_production_ne_trugva(repo):
    _, _, second = repo
    mark_tested(repo, second)

    result = deploy(repo, "prod", "main")

    assert result.returncode == 1
    assert "иска одобрението на Ив" in result.stderr
    assert second in result.stderr, "трябва да покаже КОЙ комит се одобрява"


def test_odobrenie_za_drug_komit_ne_vazhi(repo):
    """Рефът се е придвижил между показването и пускането."""
    work, env, second = repo
    mark_tested(repo, second)
    star = git("rev-parse", "--short", "HEAD~1", cwd=work)

    result = deploy(repo, "prod", "main", star)

    assert result.returncode == 1
    assert "придвижил след одобрението" in result.stderr


def test_odobrenie_za_verniya_komit_puska_napred(repo):
    """След двата предпазителя скриптът продължава към проверката за миграции."""
    _, _, second = repo
    mark_tested(repo, second)

    result = deploy(repo, "prod", "main", second)

    assert "се съдържа в tested/" in result.stdout, result.stderr
    assert f"одобрение: {second}" in result.stdout
    assert "разрушителни миграции" in result.stdout


def test_preprod_ne_iska_nito_test_nito_odobrenie(repo):
    result = deploy(repo, "preprod", "main")

    assert "НЕ е минавал" not in result.stderr
    assert "одобрението на Ив" not in result.stderr
    assert "разрушителни миграции" in result.stdout
