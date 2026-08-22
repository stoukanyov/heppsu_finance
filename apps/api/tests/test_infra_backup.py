"""Нощният бекъп — пуска се наистина, с подставен `docker`.

Тест, който чете текста на скрипта, минава и когато скриптът не работи. Тук
`docker` е подменен с малка програма, която връща правдоподобни отговори, а
скриптът не знае, че е в тест.

Проверява се клеймото `LAST_SUCCESS`: единственото, което провален бекъп не
може да напише. Control Center мери възрастта му и вдига тревога над 26 часа.
Преди 22.08.2026 този скрипт не го пишеше изобщо — бекъпът си вървеше всяка
нощ, но липсата му нямаше как да се забележи.
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

import pytest

# Скриптът се пуска САМО на сървърите (Ubuntu) и ползва GNU варианти на
# `stat -c%s`, `xargs -r` и `numfmt`. На macOS те са други или ги няма. Вместо
# да подставяме половината coreutils — което би направило теста проверка на
# заместителите, а не на скрипта — тестът върви там, където и оригиналът:
# в CI (ubuntu) и на Linux. Пропускането е шумно, не мълчаливо.
pytestmark = pytest.mark.skipif(
    platform.system() != "Linux",
    reason="`backup.sh` ползва GNU coreutils; върви на Linux, както и на сървъра",
)

BACKUP_SH = Path(__file__).resolve().parents[3] / "infra" / "backup.sh"

# Подставеният `docker`. Разбира само формите, които скриптът ползва — стъб,
# който приема всичко, би скрил сгрешена команда.
DOCKER_STUB = r'''#!/usr/bin/env python3
import os, sys

argv = sys.argv[1:]
if argv[0] != "compose":
    sys.exit(f"стъбът разбира само `docker compose`, не: {argv}")

# Изяждаме флаговете на compose до самата подкоманда.
i = 1
while i < len(argv) and argv[i].startswith("-"):
    i += 2 if argv[i] in ("-p", "-f", "--project-directory", "--env-file") else 1
cmd = argv[i:]

if cmd[0] == "ps":
    # „Базата върви" — освен ако тестът е поискал обратното.
    print("" if os.environ.get("FAKE_DB_DOWN") else "db")
    sys.exit(0)

if cmd[0] == "exec":
    if os.environ.get("FAKE_DUMP_FAILS"):
        print("pg_dump: грешка", file=sys.stderr)
        sys.exit(1)
    # Правдоподобен дъмп: скриптът го подава на gzip, проверява с `gzip -t` и
    # отказва всичко под 1 KB след компресия. Затова редовете са много и различни
    # — еднакви редове се свиват до нищо и тестът щеше да пада по грешна причина.
    sys.stdout.write("--\n-- PostgreSQL database dump\n--\n")
    for i in range(400):
        sys.stdout.write(f"INSERT INTO neshto (id, opis) VALUES ({i}, 'ред {i} с малко текст');\n")
    sys.exit(0)

sys.exit(f"стъбът не разбира: {cmd}")
'''


@pytest.fixture()
def stage(tmp_path):
    """Готова сцена: подставен `docker`, среда `prod` с нужните файлове."""
    env_dir = tmp_path / "srv" / "prod"
    (env_dir / "release" / "infra").mkdir(parents=True)
    (env_dir / "release" / "infra" / "docker-compose.yml").write_text("services: {}\n")
    (env_dir / ".env").write_text("POSTGRES_USER=aifos\nPOSTGRES_DB=aifos\n")
    (env_dir / "storage").mkdir()

    binn = tmp_path / "bin"
    binn.mkdir()
    stub = binn / "docker"
    stub.write_text(DOCKER_STUB)
    stub.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{binn}:{os.environ['PATH']}",
        "AIFOS_ENV_ROOT": str(tmp_path / "srv"),
    }
    return env_dir / "backups", env


def run(env):
    return subprocess.run(
        ["bash", str(BACKUP_SH), "prod"], env=env, capture_output=True, text=True
    )


def test_uspeshen_bekup_pishe_kleymo(stage):
    """Бекъп, минал докрай, оставя клеймо в `date -u +%s`."""
    backups, env = stage

    result = run(env)

    assert result.returncode == 0, result.stderr
    assert len(list((backups / "daily").glob("prod-*.sql.gz"))) == 1
    stamp = backups / "LAST_SUCCESS"
    assert stamp.exists(), "успешен бекъп без клеймо е бекъп, чиято липса няма да се види"
    assert stamp.read_text().strip().isdigit(), "форматът е `date -u +%s`, като при другите проекти"


def test_spryana_baza_ne_pishe_kleymo(stage):
    """Базата не върви — нощта не се брои за успешна."""
    backups, env = stage

    result = run({**env, "FAKE_DB_DOWN": "1"})

    assert result.returncode != 0
    assert not (backups / "LAST_SUCCESS").exists()


def test_provalen_dump_ne_pipa_starото_kleymo(stage):
    """Провалена нощ оставя вчерашното клеймо да остарява — това е сигналът."""
    backups, env = stage
    (backups / "daily").mkdir(parents=True)
    (backups / "LAST_SUCCESS").write_text("1700000000\n")

    run({**env, "FAKE_DUMP_FAILS": "1"})

    assert (backups / "LAST_SUCCESS").read_text().strip() == "1700000000"


def test_prazna_documents_ne_ubiva_skripta(stage):
    """Празна `documents/` не бива да прекъсва бекъпа.

    Пада върху стария скрипт. Там ротацията беше `ls -1t <шаблон> | …`; при
    несъвпаднал шаблон `ls` излиза с грешка, `pipefail` я вдига до конвейера и
    `set -e` убива скрипта — след записания дъмп, но преди края.

    На Phobos това се случваше ВСЯКА нощ: `documents/` е празна, докато
    `storage/` е празна. В `backup.log` от 26.07 до 22.08.2026 нямаше нито едно
    „готово“. Никой не забеляза, защото копието си беше на място, а изходният
    код на cron не се чете от никого.
    """
    backups, env = stage

    result = run(env)

    assert result.returncode == 0, result.stderr
    assert "готово" in result.stdout, "скриптът трябва да стига до последния си ред"
    assert (backups / "documents").is_dir()
    assert (backups / "LAST_SUCCESS").exists()


def test_rotaciyata_reje_starite(stage):
    """Пазят се 14 дневни копия, останалите се трият."""
    backups, env = stage
    daily = backups / "daily"
    daily.mkdir(parents=True)
    now = int(subprocess.run(["date", "+%s"], capture_output=True, text=True).stdout)
    for i in range(1, 21):
        old = daily / f"prod-old{i}.sql.gz"
        old.write_bytes(b"x")
        os.utime(old, (now - i * 86400, now - i * 86400))

    run(env)

    assert len(list(daily.glob("*.sql.gz"))) == 14
