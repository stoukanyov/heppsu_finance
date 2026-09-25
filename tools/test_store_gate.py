#!/usr/bin/env python3
"""Тестове на гейта: пада ли там, където трябва, и мълчи ли, където не трябва.

    python3 tools/test_store_gate.py

Гейтът е механизмът зад правилата от STORE-REJECTIONS.md; ако той сгреши,
грешката минава в магазина. Двата случая, които го хванаха на 25.09.2026:
ARB в `l10n/` вместо `lib/` (казваше „няма ARB" на локализирано приложение)
и искане на връзка за отказване на абонамент в приложение без абонаменти.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store_gate


def build_repo(root: Path, *, arb_dir: str, l10n_yaml: bool, dart: str, pubspec_iap: bool = True) -> Path:
    (root / arb_dir).mkdir(parents=True, exist_ok=True)
    for lang, title in (("en", "Settings"), ("bg", "Настройки")):
        (root / arb_dir / f"app_{lang}.arb").write_text(
            json.dumps({"@@locale": lang, "settingsTitle": title}, ensure_ascii=False),
            encoding="utf-8")
    if l10n_yaml:
        (root / "l10n.yaml").write_text(f"arb-dir: {arb_dir}\n", encoding="utf-8")
    (root / "lib").mkdir(exist_ok=True)
    (root / "lib/app.dart").write_text(dart, encoding="utf-8")
    (root / "pubspec.yaml").write_text(
        "dependencies:\n  url_launcher: ^6.0.0\n" + ("  in_app_purchase: ^3.2.0\n" if pubspec_iap else ""),
        encoding="utf-8")
    return root


def run(repo: Path) -> dict[str, tuple[str, str]]:
    store_gate.rows.clear()
    arbs = store_gate.arb_files(repo)
    store_gate.check_arb(repo, arbs)
    store_gate.check_links(repo, online=False)
    return {what: (state, detail) for state, what, detail in store_gate.rows}


LEGAL_DART = """
const kPrivacy = 'https://example.com/app-privacy.html';
const kTerms = 'https://example.com/app-terms.html';
"""


def case(name: str, cond: bool, detail: str = "") -> bool:
    print(f"{'OK  ' if cond else 'НЕ  '}{name}{'' if cond else '  ← ' + detail}")
    return cond


def main() -> int:
    passed = []
    with tempfile.TemporaryDirectory() as tmp:
        # 1. ARB в l10n/ на корена, обявено в l10n.yaml — гейтът трябва да ги намери.
        repo = build_repo(Path(tmp) / "a", arb_dir="l10n", l10n_yaml=True, dart=LEGAL_DART)
        r = run(repo)
        passed.append(case("намира ARB през arb-dir от l10n.yaml",
                           r.get("езици в ARB", ("", ""))[0] == "OK", str(r.get("ARB файлове"))))

        # 2. Без l10n.yaml — пак трябва да ги намери по подразбиране в l10n/.
        repo = build_repo(Path(tmp) / "b", arb_dir="l10n", l10n_yaml=False, dart=LEGAL_DART)
        r = run(repo)
        passed.append(case("намира ARB в l10n/ и без l10n.yaml",
                           r.get("езици в ARB", ("", ""))[0] == "OK", str(r.get("ARB файлове"))))

        # 3. Класическото място lib/l10n не бива да се счупи от промяната.
        repo = build_repo(Path(tmp) / "c", arb_dir="lib/l10n", l10n_yaml=False, dart=LEGAL_DART)
        r = run(repo)
        passed.append(case("намира ARB в lib/l10n (както досега)",
                           r.get("езици в ARB", ("", ""))[0] == "OK", str(r.get("ARB файлове"))))

        # 4. Еднократни покупки: не се иска връзка за отказване на абонамент.
        repo = build_repo(Path(tmp) / "d", arb_dir="l10n", l10n_yaml=True, dart=LEGAL_DART)
        r = run(repo)
        passed.append(case("без абонамент не иска връзка за отказване",
                           "връзка за управление/спиране на абонамента" not in r, str(r)))
        passed.append(case("но отбелязва, че покупките са еднократни",
                           r.get("покупки", ("", ""))[0] == "OK", str(r.get("покупки"))))

        # 5. Абонамент без връзка за отказване — гейтът пада (правилото остава).
        repo = build_repo(Path(tmp) / "e", arb_dir="l10n", l10n_yaml=True,
                          dart=LEGAL_DART + "\nconst plan = 'subscription monthly';\n")
        r = run(repo)
        passed.append(case("абонамент без връзка за отказване пада",
                           r.get("връзка за управление/спиране на абонамента", ("", ""))[0] == "NO", str(r)))

        # 6. Абонамент СЪС връзка за отказване — минава.
        repo = build_repo(Path(tmp) / "f", arb_dir="l10n", l10n_yaml=True,
                          dart=LEGAL_DART + "\nconst plan = 'subscription';\n"
                          "const manage = 'https://apps.apple.com/account/subscriptions';\n")
        r = run(repo)
        passed.append(case("абонамент с връзка за отказване минава",
                           r.get("връзка за управление/спиране на абонамента", ("", ""))[0] == "OK", str(r)))

        # 7. Написана цена в ARB пак пада (A6) — проверката вече вижда ARB-ите.
        repo = build_repo(Path(tmp) / "g", arb_dir="l10n", l10n_yaml=True, dart=LEGAL_DART)
        (repo / "l10n/app_en.arb").write_text(
            json.dumps({"@@locale": "en", "buy": "Unlock everything — 14.99 EUR"}), encoding="utf-8")
        r = run(repo)
        passed.append(case("написана цена в ARB пада (A6)",
                           r.get("написана цена в ARB", ("", ""))[0] == "NO", str(r)))

    print(f"\n{sum(passed)}/{len(passed)} минаха")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
