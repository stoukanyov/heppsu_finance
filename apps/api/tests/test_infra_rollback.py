"""Връщането назад, когато деплоят откаже.

На 26.10.2026 production беше недостъпен, защото здравната проверка на деплоя
обяви живо приложение за мъртво. Връщането назад трябваше да го спаси и не го
спаси — в него имаше две повреди, които никой тест не покриваше, защото тялото
му живееше като heredoc вътре в `deploy.sh`:

1. Дневникът на отказа се вземаше с `docker compose logs` без `AIFOS_IMAGE`.
   `docker-compose.yml` иска променливата със `:?`, compose отказва да прочете
   файла и единствената следа защо е паднал деплоят изчезва.

2. Вдигането беше `up -d --no-build` — със зависимостите, тоест и `migrate`.
   Базата обаче вече е мигрирана НАПРЕД, а старият код не познава новата
   ревизия: `alembic upgrade head` излиза с 255 и връщането се проваля.

Тестовете тук пускат `infra/rollback.sh` наистина, с подставен `docker`, който
записва всяко извикване и стойността на `AIFOS_IMAGE`.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROLLBACK_SH = Path(__file__).resolve().parents[3] / "infra" / "rollback.sh"

# Подставен `docker`: записва аргументите и дали AIFOS_IMAGE е бил зададен.
# `image inspect` връща 0, за да има към какво да се връща.
DOCKER_STUB = r"""#!/usr/bin/env python3
import os, sys

with open(os.environ["DOCKER_LOG"], "a", encoding="utf-8") as f:
    f.write(repr(os.environ.get("AIFOS_IMAGE")) + "\t" + " ".join(sys.argv[1:]) + "\n")
sys.exit(0)
"""


@pytest.fixture()
def sreda(tmp_path):
    """Машина в състоянието, в което я заварва провалил се деплой."""
    remote = tmp_path / "srv"
    (remote / "release" / "infra").mkdir(parents=True)
    (remote / "release" / "infra" / "docker-compose.yml").write_text("# нов\n")
    (remote / "release.old" / "infra").mkdir(parents=True)
    (remote / "release.old" / "infra" / "docker-compose.yml").write_text("# стар\n")
    (remote / ".env").write_text("POSTGRES_USER=aifos\n")

    binn = tmp_path / "bin"
    binn.mkdir()
    docker = binn / "docker"
    docker.write_text(DOCKER_STUB)
    docker.chmod(0o755)

    log = tmp_path / "docker.log"
    env = {
        **os.environ,
        "PATH": f"{binn}:{os.environ['PATH']}",
        "DOCKER_LOG": str(log),
        "PROJECT": "aifos-prod",
        "REMOTE_DIR": str(remote),
    }
    return remote, env, log


def _run(env):
    return subprocess.run(
        ["bash", str(ROLLBACK_SH)], env=env, capture_output=True, text=True
    )


def _povikvaniya(log: Path) -> list[tuple[str, str]]:
    if not log.exists():
        return []
    redove = [r.split("\t", 1) for r in log.read_text(encoding="utf-8").splitlines() if r]
    return [(obraz, argumenti) for obraz, argumenti in redove]


def test_vrushtaneto_minava(sreda):
    remote, env, _ = sreda
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert "ВРЪЩАМ предишната версия" in result.stdout
    # Провалилото се издание се пази, старото се връща на мястото си.
    assert (remote / "release" / "infra" / "docker-compose.yml").read_text() == "# стар\n"
    assert (remote / "release.failed" / "infra" / "docker-compose.yml").read_text() == "# нов\n"


def test_dnevnikut_na_otkaza_se_vzema_s_aifos_image(sreda):
    """Без AIFOS_IMAGE compose отказва да прочете файла и следата се губи."""
    _, env, log = sreda
    _run(env)
    logs = [obraz for obraz, args in _povikvaniya(log) if " logs " in f" {args} "]
    assert logs, "дневникът на отказа изобщо не беше поискан"
    assert all(obraz != "None" for obraz in logs), (
        "`docker compose logs` е извикан без AIFOS_IMAGE — compose отказва да "
        "прочете docker-compose.yml и дневникът на отказа изчезва"
    )


def test_vrushtaneto_ne_pusca_migraciite_pak(sreda):
    """Старият код срещу мигрирала напред база излиза с 255."""
    _, env, log = sreda
    _run(env)
    up = [args for _, args in _povikvaniya(log) if " up " in f" {args} "]
    assert up, "стекът изобщо не беше вдигнат"
    for args in up:
        assert "--no-deps" in args, (
            f"вдигането е без --no-deps ({args}) — тръгва и `migrate`, а базата е "
            "вече мигрирана напред: alembic излиза с 255 и връщането се проваля"
        )
        assert "migrate" not in args.split(), "`migrate` не бива да се пуска при връщане"
        assert "api" in args.split() and "nginx" in args.split()


def test_bez_predishna_versiya_ne_pipa_nishto(sreda):
    """Първо пускане: няма release.old — нищо не се мести."""
    remote, env, _ = sreda
    import shutil

    shutil.rmtree(remote / "release.old")
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert "НЯМА към какво да се върна" in result.stdout
    assert (remote / "release" / "infra" / "docker-compose.yml").read_text() == "# нов\n"
    assert not (remote / "release.failed").exists()


def test_kazva_che_bazata_ne_e_vurnata(sreda):
    """Схемата остава напред — това трябва да се прочете, не да се предполага."""
    _, env, _ = sreda
    result = _run(env)
    assert "базата НЕ е върната назад" in result.stdout
    assert "pre-deploy-" in result.stdout


def test_deploy_sh_vika_imenno_tozi_fail(sreda):
    """Тялото да не се върне обратно като heredoc, без никой да го тества."""
    deploy_sh = (ROLLBACK_SH.parent / "deploy.sh").read_text(encoding="utf-8")
    assert "infra/rollback.sh" in deploy_sh
    assert "ВРЪЩАМ предишната версия" not in deploy_sh
