#!/usr/bin/env python3
"""Отпечатва head ревизията на миграциите в подадена директория.

    python3 infra/ci/alembic_head.py apps/api/alembic/versions

Прави същото като `alembic heads`, но чете само файловете и не иска нито
alembic, нито конфигурация, нито база. Причината: стойността трябва да се
изчисли от КОДА, който се пуска — на CI машина, в сървър без виртуална среда,
или от архив — а `alembic heads` изисква работещ `env.py` и настройки.

Използва се от `rehearse-migrations.sh`: след репетицията `alembic_version` в
копието на production базата трябва да е точно този head. Съвпадението значи, че
е пробван правилният код; разминаването значи стар образ.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REVISION = re.compile(r'^revision(?::\s*str)?\s*=\s*["\']([^"\']+)["\']', re.M)
DOWN = re.compile(r'^down_revision(?::\s*[^=]+)?\s*=\s*(.+)$', re.M)


def main(argv: list[str]) -> int:
    versions = Path(argv[1] if len(argv) > 1 else "apps/api/alembic/versions")
    if not versions.is_dir():
        print(f"няма такава директория: {versions}", file=sys.stderr)
        return 2

    revisions: set[str] = set()
    parents: set[str] = set()

    for path in versions.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        rev = REVISION.search(src)
        if not rev:
            continue
        revisions.add(rev.group(1))
        down = DOWN.search(src)
        if down:
            # down_revision може да е None, низ, или кортеж при сливане на клони.
            parents.update(re.findall(r'["\']([^"\']+)["\']', down.group(1)))

    heads = sorted(revisions - parents)
    if not heads:
        print("не намерих нито една миграция", file=sys.stderr)
        return 1
    if len(heads) > 1:
        # Две глави значи разклонена история — репетицията не може да реши коя е
        # правилната, а `alembic upgrade head` ще откаже. По-добре сега, отколкото
        # върху production.
        print(f"РАЗКЛОНЕНА история, {len(heads)} глави: {', '.join(heads)}", file=sys.stderr)
        return 1

    print(heads[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
