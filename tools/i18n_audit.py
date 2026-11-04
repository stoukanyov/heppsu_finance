#!/usr/bin/env python3
"""Пълнота на превода: какво може да се докаже, без да четеш езика.

    python3 tools/i18n_audit.py <репо-на-приложението> [--json изход.json]

Ив, 02.10.2026: „провери дали има език, на който преводът не е пълен, или
секция, която не е преведена". Част от отговора е механична и затова е тук —
машината я дава за секунди и ще я дава пак догодина. Другата част (звучи ли
естествено, смесена ли е терминологията) иска носител на езика; този скрипт
подготвя точния списък за него, вместо да го праща да чете 700 низа.

Какво проверява:

1. **Покритие на повърхностите** — ARB, purpose strings (`*.lproj`), описания
   за магазините. Липсващ ФАЙЛ е по-тежък от липсващ низ: цял екран или цял
   системен диалог остава на чужд език.
2. **Липсващи и празни ключове** спрямо английския.
3. **Кандидати за непреведено** — низове, идентични с английския. Част са
   законни („OK", „Plus", имена); решава носител на езика, затова излизат
   като списък, не като присъда.
4. **Твърдо закодиран текст** в екраните — той няма превод на НИТО един език.
   Интерполациите (`'${a} · ${b}'`) се пропускат: там частите идват от l10n.

Какво НЕ проверява: качеството на превода. За него виж доклада от езиковата
проверка (по един носител на език).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

#: Низове, които съвпадат с английския законно на всеки език.
ALWAYS_OK = {
    "OK", "Email", "Plus", "QR", "PDF", "GPS", "ID", "URL", "Wi-Fi", "SMS",
    "Beagle Owner", "Dog Journey", "Heppsu",
}

#: Технически низове, които не са човешки текст.
TECH = re.compile(r"^[\s\W\d]*$|^[a-z0-9_.:/#-]+$|^[A-Z_]+$|^\w+\.\w+$|^https?://|^/|^\d")


def arb_files(repo: pathlib.Path) -> dict[str, pathlib.Path]:
    for pattern in ("lib/l10n/app_*.arb", "l10n/app_*.arb", "lib/**/app_*.arb"):
        found = {p.stem.replace("app_", ""): p for p in repo.glob(pattern)}
        if found:
            return found
    return {}


def strings_of(path: pathlib.Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("@") and isinstance(v, str)}


def check_surfaces(repo: pathlib.Path, langs: set[str]) -> list[tuple[str, str]]:
    """Липсващ файл значи цяла повърхност без превод."""
    problems = []
    lproj = {p.name.replace(".lproj", "") for p in repo.glob("ios/Runner/*.lproj") if p.is_dir()}
    if lproj:
        with_strings = {
            p.parent.name.replace(".lproj", "")
            for p in repo.glob("ios/Runner/*.lproj/InfoPlist.strings")
        }
        for lang in sorted(langs - with_strings - {"en"}):
            if lang in lproj:
                problems.append((lang, "ios/Runner/%s.lproj/ няма InfoPlist.strings — системните диалози за разрешения остават на чужд език" % lang))
            else:
                problems.append((lang, "няма ios/Runner/%s.lproj — езикът липсва в iOS пакета" % lang))
    store = {p.stem for p in repo.glob("tool/store_text/*.json")}
    if store:
        for lang in sorted(langs - store):
            problems.append((lang, "tool/store_text/%s.json липсва — описанието в магазина остава на чужд език" % lang))
    return problems


def check_keys(files: dict[str, pathlib.Path]) -> tuple[list, dict[str, list]]:
    en = strings_of(files["en"])
    problems, candidates = [], {}
    for lang in sorted(files):
        if lang == "en":
            continue
        tr = strings_of(files[lang])
        for key in sorted(set(en) - set(tr)):
            problems.append((lang, f"липсва ключ {key}"))
        for key in sorted(k for k, v in tr.items() if not v.strip()):
            problems.append((lang, f"празна стойност {key}"))
        same = [
            k for k in sorted(set(en) & set(tr))
            if en[k].strip() == tr[k].strip() and en[k].strip() not in ALWAYS_OK and len(en[k].strip()) > 3
        ]
        if same:
            candidates[lang] = {k: en[k] for k in same}
    return problems, candidates


def check_hardcoded(repo: pathlib.Path) -> list[tuple[str, int, str]]:
    hits = []
    roots = [repo / "lib"] + [p for p in (repo.parent.parent / "packages").glob("*/lib")] if (repo.parent.parent / "packages").is_dir() else [repo / "lib"]
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.dart")):
            rel = path.as_posix()
            if "/l10n/" in rel or rel.endswith("_test.dart") or "/generated/" in rel:
                continue
            src = path.read_text(encoding="utf-8")
            for m in re.finditer(
                r"(?:Text|SelectableText)\(\s*(['\"])((?:[^'\"\\$]|\\.){4,120}?)\1", src
            ):
                value = m.group(2)
                if TECH.match(value.strip()) or value.strip() in ALWAYS_OK:
                    continue
                if sum(c.isalpha() for c in value) >= 4:
                    hits.append((rel.split("/lib/")[-1], src[: m.start()].count("\n") + 1, value))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo")
    parser.add_argument("--json", dest="out")
    args = parser.parse_args()

    repo = pathlib.Path(args.repo).resolve()
    files = arb_files(repo)
    if "en" not in files:
        print(f"NO\tARB\t{repo}: няма app_en.arb — няма спрямо какво да се сравнява")
        return 1

    langs = set(files)
    surface = check_surfaces(repo, langs)
    keys, candidates = check_keys(files)
    hardcoded = check_hardcoded(repo)

    print(f"{len(files)} езика · {len(strings_of(files['en']))} ключа в en")
    for lang, text in surface + keys:
        print(f"NO\t{lang}\t{text}")
    if hardcoded:
        print(f"NO\t—\t{len(hardcoded)} твърдо закодирани текста в екраните (без превод на НИТО един език):")
        for rel, line, value in hardcoded[:20]:
            print(f"\t\t{rel}:{line} → {value!r}")
    if not surface and not keys and not hardcoded:
        print("OK\tмеханичните проверки\tняма липсващи файлове, ключове, празни стойности и твърд текст")
    print(f"\nкандидати за непреведено (идентични с английския), за носител на езика:")
    for lang, items in sorted(candidates.items(), key=lambda x: -len(x[1])):
        print(f"\t{lang}: {len(items)}")

    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps({"surface": surface, "keys": keys, "hardcoded": hardcoded, "candidates": candidates},
                       ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"\nподробностите → {args.out}")
    return 1 if (surface or keys or hardcoded) else 0


if __name__ == "__main__":
    sys.exit(main())
