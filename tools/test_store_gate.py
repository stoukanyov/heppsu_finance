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


def run(repo: Path, allow_same_version: bool = False) -> dict[str, tuple[str, str]]:
    store_gate.rows.clear()
    arbs = store_gate.arb_files(repo)
    store_gate.check_version(repo, allow_same_version)
    store_gate.check_arb(repo, arbs)
    store_gate.check_links(repo, online=False)
    return {what: (state, detail) for state, what, detail in store_gate.rows}


# Както изглежда истински абонамент в кода (Beagle Owner: plus_monthly).
SUBSCRIPTION_DART = """
const String productId = 'plus_monthly';
"""

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
                          dart=LEGAL_DART + SUBSCRIPTION_DART)
        r = run(repo)
        passed.append(case("абонамент без връзка за отказване пада",
                           r.get("връзка за управление/спиране на абонамента", ("", ""))[0] == "NO", str(r)))

        # 6. Абонамент СЪС връзка за отказване — минава.
        repo = build_repo(Path(tmp) / "f", arb_dir="l10n", l10n_yaml=True,
                          dart=LEGAL_DART + SUBSCRIPTION_DART +
                          "const manage = 'https://apps.apple.com/account/subscriptions';\n")
        r = run(repo)
        passed.append(case("абонамент с връзка за отказване минава",
                           r.get("връзка за управление/спиране на абонамента", ("", ""))[0] == "OK", str(r)))

        # 6б. Абонаментът може да живее в СЪСЕДЕН пакет (pub workspace):
        # Dog Journey държи идентификаторите на продуктите в `dog_core`, а
        # гейтът четеше само `lib/` на приложението и обяви абонамента за
        # еднократна покупка — тоест мълчаливо пропусна правилото (25.09.2026).
        repo = build_repo(Path(tmp) / "ws", arb_dir="l10n", l10n_yaml=True, dart=LEGAL_DART)
        shared = Path(tmp) / "ws_shared"
        (shared / "lib").mkdir(parents=True, exist_ok=True)
        (shared / "lib/products.dart").write_text(
            "const ids = {'plus_monthly': 'com.heppsu.dogJourney.plus.monthly'};\n", encoding="utf-8")
        pubspec = repo / "pubspec.yaml"
        pubspec.write_text(
            pubspec.read_text(encoding="utf-8") + f"  dog_core:\n    path: {shared}\n", encoding="utf-8")
        r = run(repo)
        passed.append(case("абонамент в съседен пакет се вижда",
                           r.get("връзка за управление/спиране на абонамента", ("", ""))[0] == "NO", str(r)))

        # 6в. Абонамент, който не отключва нищо (Dog Journey до 25.09.2026):
        # `isPlus` беше пресметнат и не се ползваше никъде — App Review пита
        # точно „какво отключва абонаментът", а човекът плаща за нищо.
        repo = build_repo(Path(tmp) / "h", arb_dir="l10n", l10n_yaml=True,
                          dart=LEGAL_DART + SUBSCRIPTION_DART +
                          "const manage = 'https://apps.apple.com/account/subscriptions';\n")
        r = run(repo)
        passed.append(case("абонамент, който не отключва нищо, пада",
                           r.get("абонаментът отключва нещо", ("", ""))[0] == "NO", str(r)))

        # 6г. Същото приложение с врата пред функция — минава.
        repo = build_repo(Path(tmp) / "i", arb_dir="l10n", l10n_yaml=True,
                          dart=LEGAL_DART + SUBSCRIPTION_DART +
                          "const manage = 'https://apps.apple.com/account/subscriptions';\n")
        (repo / "lib/pack_screen.dart").write_text(
            "Widget build(c) => billing.isPlus ? const Pack() : const PlusWall();\n", encoding="utf-8")
        r = run(repo)
        passed.append(case("врата пред функция минава",
                           r.get("абонаментът отключва нещо", ("", ""))[0] == "OK", str(r)))

        # 6д. Версията расте заедно с билда (Ив, 06.09.2026; напомнено
        # 01.10.2026, след като Beagle Owner излезе два пъти подред с вдигнат
        # само билд: 1.2.8+79 → +80 → +81).
        import subprocess as sp

        def git_repo(path: Path, versions: list[str]) -> Path:
            repo = build_repo(path, arb_dir="l10n", l10n_yaml=True, dart=LEGAL_DART)
            sp.run(["git", "init", "-q"], cwd=repo, check=True)
            sp.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
            sp.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
            pubspec = repo / "pubspec.yaml"
            base = pubspec.read_text(encoding="utf-8")
            for v in versions:
                pubspec.write_text(f"version: {v}\n" + base, encoding="utf-8")
                sp.run(["git", "add", "-A"], cwd=repo, check=True)
                sp.run(["git", "commit", "-q", "-m", v], cwd=repo, check=True)
            return repo

        repo = git_repo(Path(tmp) / "v1", ["1.2.8+80", "1.2.8+81"])
        r = run(repo)
        passed.append(case("вдигнат само билд пада",
                           r.get("версия расте с билда", ("", ""))[0] == "NO", str(r.get("версия расте с билда"))))

        repo = git_repo(Path(tmp) / "v2", ["1.2.8+80", "1.2.9+81"])
        r = run(repo)
        passed.append(case("вдигнат PATCH минава",
                           r.get("версия расте с билда", ("", ""))[0] == "OK", str(r.get("версия расте с билда"))))

        repo = git_repo(Path(tmp) / "v3", ["1.2.8+80", "1.2.8+81"])
        r = run(repo, allow_same_version=True)
        passed.append(case("същата версия минава само с изричен флаг",
                           r.get("версия", ("", ""))[0] == "ASK", str(r.get("версия"))))

        repo = git_repo(Path(tmp) / "v4", ["1.0.0+3", "0.2.0+3"])
        r = run(repo)
        passed.append(case("същият билд с друга версия е преномериране, не нарушение",
                           r.get("версия", ("", ""))[0] == "OK", str(r.get("версия"))))

        repo = git_repo(Path(tmp) / "v5", ["1.0.0+3", "0.9.0+4"])
        r = run(repo)
        passed.append(case("по-малка версия при нов билд пада",
                           r.get("версия расте с билда", ("", ""))[0] == "NO",
                           str(r.get("версия расте с билда"))))

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
