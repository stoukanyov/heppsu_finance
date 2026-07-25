#!/usr/bin/env python3
"""Пазач срещу разрушителни миграции.

Счетоводните данни имат 10-годишен срок на съхранение по ЗСч. Една миграция с
`drop_column` може да изтрие безвъзвратно данни, които после трябва да покажем на
ревизия. Затова разрушителните операции НЕ минават автоматично — искат изричен
подпис в самия файл:

    # ALLOW-DESTRUCTIVE: колоната е дублирана от `x`, мигрирана е в 2026-07-01

Използване:
    python infra/ci/check_migrations.py                # всички миграции
    python infra/ci/check_migrations.py --since main   # само новите спрямо main

Изход: 0 = чисто, 1 = намерени неподписани разрушителни операции.
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import re
import subprocess
import sys

VERSIONS_DIR = pathlib.Path("apps/api/alembic/versions")
MARKER = "ALLOW-DESTRUCTIVE"

# Извикване по име → защо е опасно. Проверява се със `ast`, а не с регулярни
# изрази: `sa.Column(..., nullable=False)` вътре в `create_table` е напълно
# безопасно (нова таблица, няма редове), докато `alter_column(nullable=False)`
# върху съществуваща таблица гърми при първия NULL.
DESTRUCTIVE_CALLS = {
    "drop_table": "изтрива цяла таблица заедно с данните",
    "drop_column": "изтрива колона — данните в нея изчезват",
    "drop_constraint": "маха ограничение — може да пусне невалидни данни",
    "rename_table": "преименува таблица — стари справки спират да я намират",
}
# Разрушителен суров SQL в op.execute(...)
RAW_SQL_DANGER = re.compile(r"\b(DELETE\s+FROM|TRUNCATE|DROP\s+TABLE|DROP\s+COLUMN)\b", re.I)


def changed_files(since: str) -> set[pathlib.Path]:
    """Миграциите, добавени спрямо даден git ref."""
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=A", f"{since}...HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        print(f"не мога да сравня с {since!r}: {exc.stderr.strip()}", file=sys.stderr)
        raise SystemExit(2) from exc
    return {
        pathlib.Path(line) for line in out.splitlines()
        if line.startswith(str(VERSIONS_DIR)) and line.endswith(".py")
    }


def _kwarg(call: ast.Call, name: str):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def scan(path: pathlib.Path) -> list[tuple[int, str, str]]:
    """Връща [(ред, израз, обяснение)] за разрушителните операции в `upgrade()`.

    Проверява се само `upgrade()` — `downgrade()` по природа е разрушителен и се
    пуска съзнателно.
    """
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        return []                                    # подписано съзнателно
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [(exc.lineno or 0, "", f"файлът не се компилира: {exc.msg}")]

    upgrade = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade"), None
    )
    if upgrade is None:
        return []

    findings: list[tuple[int, str, str]] = []
    for node in ast.walk(upgrade):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        fn = node.func.attr
        snippet = ast.unparse(node)[:100]

        if fn in DESTRUCTIVE_CALLS:
            findings.append((node.lineno, snippet, DESTRUCTIVE_CALLS[fn]))

        elif fn == "alter_column":
            nullable = _kwarg(node, "nullable")
            if isinstance(nullable, ast.Constant) and nullable.value is False:
                findings.append((node.lineno, snippet,
                                 "прави колона задължителна — гърми при съществуващи NULL"))
            if _kwarg(node, "type_") is not None:
                findings.append((node.lineno, snippet,
                                 "смяна на тип — възможна загуба на точност или данни"))
            if _kwarg(node, "new_column_name") is not None:
                findings.append((node.lineno, snippet,
                                 "преименува колона — кодът, който още ползва старото име, гърми"))

        elif fn == "execute":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                        and RAW_SQL_DANGER.search(arg.value):
                    findings.append((node.lineno, snippet, "суров разрушителен SQL"))

    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="git ref — проверява само новите миграции спрямо него")
    args = ap.parse_args()

    if not VERSIONS_DIR.is_dir():
        print(f"не намирам {VERSIONS_DIR} — пусни скрипта от корена на репото", file=sys.stderr)
        return 2

    files = changed_files(args.since) if args.since else set(VERSIONS_DIR.glob("*.py"))
    files = {f for f in sorted(files) if f.name != "__init__.py"}
    if not files:
        print("няма нови миграции за проверка")
        return 0

    print(f"проверявам {len(files)} миграции")
    problems = 0
    for path in sorted(files):
        findings = scan(path)
        if not findings:
            continue
        problems += len(findings)
        print(f"\n\033[1;31m✗ {path}\033[0m")
        for line_no, snippet, why in findings:
            print(f"   ред {line_no}: {snippet}")
            print(f"            └─ {why}")

    if problems:
        print(
            f"\n\033[1;31mСПРЯНО: {problems} разрушителни операции без изрично разрешение.\033[0m\n"
            f"Ако са наистина нужни, добави ред в миграцията:\n"
            f"    # {MARKER}: <защо е безопасно и как са запазени данните>\n"
            f"и се увери, че има пресен бекъп."
        )
        return 1

    print("\033[1;32m✓ няма неподписани разрушителни операции\033[0m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
