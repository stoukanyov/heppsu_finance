#!/usr/bin/env python3
"""Механичните правила на магазините, проверени върху репото ПРЕДИ билд.

Всеки ред тук е отказ, който вече сме получили (docs/STORE-REJECTIONS.md):
A4 purpose strings по езици, A6/M4 цената и trial-ът, A8/M2 „Google Play"
в iOS низ, M3 правните връзки, M1 подаването. Правило, което живее само в
документ, се нарушава дни по-късно (виж feedback-pravilo-bez-mehanizam);
затова е скрипт, който пада.

    python3 tools/store_gate.py /path/to/flutter/repo [--online]

Печата OK|NO|ASK<TAB>какво<TAB>подробност; излиза с 1 при NO.
Не заменя чеклиста: демо акаунти, sandbox покупка, 5 резолюции, RTDN и
подаването с 3 елемента ги проверява човек/ASC API (review_gate.py).
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

PRICE = re.compile(r"\d[.,]\d\d ?(EUR|€|USD|\$|£|лв)|(EUR|€|USD|\$|£) ?\d")
CYRILLIC = re.compile(r"[Ѐ-ӿ]+")
CYRILLIC_LANGS = {"bg", "ru", "uk", "sr", "mk", "be"}
AUTO_CHARGE = re.compile(
    r"automat|charged|renew|таксува|abgebucht|cobra|prélev|terhel|addebit|pobier|încas|cobrado",
    re.I,
)
PLATFORM_KEY = re.compile(r"google|play|android|apple|ios|store", re.I)

rows: list[tuple[str, str, str]] = []


def ok(what, detail=""):
    rows.append(("OK", what, detail))


def no(what, detail=""):
    rows.append(("NO", what, detail))


def ask(what, detail=""):
    rows.append(("ASK", what, detail))


def arb_dirs(repo: Path) -> list[str]:
    """Къде са ARB файловете: l10n.yaml казва, не предположението.

    Beagle Owner ги държи в lib/l10n, Construction Calculator - в l10n/ на
    корена (`arb-dir: l10n`). Гейт, който гледа само lib/**, казва „няма
    ARB" на напълно локализирано приложение и пропуска проверките за цена,
    „Google Play" и кирилица - точно онова, за което съществува.
    """
    cfg = repo / "l10n.yaml"
    if cfg.exists():
        m = re.search(r"^arb-dir:\s*(\S+)", cfg.read_text(encoding="utf-8"), re.M)
        if m:
            return [f"{m.group(1).strip().rstrip('/')}/**/*.arb"]
    return ["lib/**/*.arb", "l10n/**/*.arb"]


def arb_files(repo: Path) -> dict[str, dict]:
    out = {}
    found = [f for pat in arb_dirs(repo) for f in repo.glob(pat)]
    for f in sorted(found):
        m = re.search(r"_([a-z]{2,3})(?:_[A-Z]{2})?\.arb$", f.name)
        if not m:
            continue
        try:
            out[m.group(1)] = {k: v for k, v in json.loads(f.read_text(encoding="utf-8")).items()
                               if not k.startswith("@") and isinstance(v, str)}
        except json.JSONDecodeError as exc:
            no("ARB се чете", f"{f}: {exc}")
    return out


def check_arb(repo: Path, arbs: dict[str, dict]) -> None:
    if not arbs:
        ask("ARB файлове", f"няма ARB в {', '.join(arb_dirs(repo))} — приложението не е локализирано през ARB?")
        return
    ok("езици в ARB", ", ".join(sorted(arbs)))

    # A6/M4: никаква написана цена.
    hits = [f"{lang}:{k}" for lang, a in arbs.items() for k, v in a.items() if PRICE.search(v)]
    (no if hits else ok)("написана цена в ARB", ", ".join(hits[:6]) or "няма")

    # A8/M2: един низ за двата магазина.
    both = [f"{lang}:{k}" for lang, a in arbs.items() for k, v in a.items()
            if "App Store" in v and "Google Play" in v]
    (no if both else ok)("„App Store“ и „Google Play“ в един низ", ", ".join(both[:6]) or "няма")
    loose = [f"{lang}:{k}" for lang, a in arbs.items() for k, v in a.items()
             if ("Google Play" in v or "App Store" in v) and not PLATFORM_KEY.search(k)]
    if loose:
        ask("магазин по име в общ низ", f"ключът не подсказва платформа: {', '.join(loose[:6])} — идва ли през {{store}}?")

    # M4: trial изречение — колко трае, сумата, автоматично.
    trial = [f"{lang}:{k}" for lang, a in arbs.items() for k, v in a.items()
             if "{price}" in v and AUTO_CHARGE.search(v)]
    # „free“ само по себе си не е пробен период: безплатно приложение пише
    # „free, and staying free“ и няма какво да таксува после. Правилото важи
    # за текст, който наистина обещава пробен период.
    TRIAL_WORDS = re.compile(r"free trial|trial|days free|пробен период|безплатен период", re.I)
    if any(TRIAL_WORDS.search(v) for a in arbs.values() for v in a.values()):
        (ok if trial else no)("trial: сума + „автоматично“ в едно изречение",
                              f"{len(trial)} низа с {{price}} и обяснение" if trial else "има trial текст, но нито един низ с {price} и „charged automatically/renews“")
    else:
        ok("trial изречение", "няма trial в текстовете")

    # A4: кирилица извън кирилските езици.
    cyr = [f"{lang}:{k}" for lang, a in arbs.items() if lang not in CYRILLIC_LANGS
           for k, v in a.items() if CYRILLIC.search(v)]
    (no if cyr else ok)("кирилица извън bg/ru/uk/sr", ", ".join(cyr[:6]) or "няма")


#: Как изглежда „проверка за абонамент" в клиентски Dart код.
_ENTITLEMENT_USE = re.compile(r"\b(isPlus|isSubscribed|hasSubscription|entitlement\.entitled|SubscriptionRequired)\b")
#: Файловете, които САМИ пресмятат абонамента — там употребата не е гейт.
_BILLING_FILE = re.compile(r"(billing|entitlement|subscription|purchase|store_gateway)[^/]*\.dart$")


def _check_subscription_unlocks_something(sources: list[Path]) -> None:
    """Абонамент, който не отключва нищо, е отказ и измама едновременно.

    App Review проверява точно това („what does the subscription unlock?"), а
    човекът плаща за услуга без услуга. Dog Journey стоеше така до 25.09.2026:
    `isPlus` беше пресметнат правилно и не се ползваше никъде — глутницата,
    споделянето с ветеринар и облачното копие бяха достъпни и без плащане, а
    описанието в магазина ги изброяваше като ползи на Plus.

    Признакът е употреба на състоянието ИЗВЪН слоя, който го пресмята: екран,
    който показва врата, или заявка, която го проверява. Употреба само в
    `billing_controller.dart` значи „пресметнато, но неизползвано".
    """
    users = sorted(
        {
            p.name
            for p in sources
            if not _BILLING_FILE.search(p.as_posix()) and _ENTITLEMENT_USE.search(p.read_text(encoding="utf-8", errors="ignore"))
        }
    )
    (ok if users else no)(
        "абонаментът отключва нещо",
        ", ".join(users[:4]) if users else "състоянието на абонамента не се ползва никъде извън билинга",
    )


def _workspace_packages(repo: Path) -> list[Path]:
    """Пакетите на същото хранилище, от които това приложение зависи по път.

    Чете `dependencies:` с `path:` от pubspec.yaml — без да внася yaml
    библиотека заради три реда. Връща само съществуващи папки ВЪТРЕ в
    хранилището; чужд път (например пакет от pub кеша) не е наш код.
    """
    pubspec = repo / "pubspec.yaml"
    if not pubspec.exists():
        return []
    found: list[Path] = []
    for match in re.finditer(r"^\s*path:\s*(\S+)\s*$", pubspec.read_text(encoding="utf-8"), re.MULTILINE):
        candidate = (repo / match.group(1)).resolve()
        if candidate.is_dir() and candidate != repo.resolve():
            found.append(candidate)
    return found


def check_links(repo: Path, online: bool) -> None:
    # Генерираните преводи не са код: там думата „абонамент" е текст за
    # потребителя („плащаш веднъж, без абонамент"), не продукт.
    sources = [p for p in repo.glob("lib/**/*.dart") if "l10n/generated" not in p.as_posix()]
    # Кодът на приложението не е само в неговата `lib/`: в pub workspace
    # (Dog Journey) идентификаторите на продуктите и целият общ слой живеят в
    # съседен пакет. Без него гейтът обяви абонамента за еднократна покупка и
    # пропусна проверката за връзка към отказване (25.09.2026).
    sources += [
        p
        for local in _workspace_packages(repo)
        for p in local.glob("lib/**/*.dart")
        if "l10n/generated" not in p.as_posix()
    ]
    dart = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in sources)
    urls = set(re.findall(r"https://[^\s'\"]+(?:privacy|terms|policy|legal)[^\s'\"]*", dart))
    # Dog Journey строи връзката от базата на средата: '${base}/legal/privacy/$lang'
    # (legal_links.dart) — пътят е доказателството, не буквалният https.
    urls |= set(re.findall(r"/legal/(?:privacy|terms)[^\s'\"]*", dart))
    privacy = [u for u in urls if "privacy" in u or "policy" in u]
    terms = [u for u in urls if "terms" in u or ("legal" in u and "privacy" not in u)]
    (ok if privacy else no)("политика за поверителност в кода", ", ".join(privacy) or "няма https://…privacy… в lib/")
    (ok if terms else no)("условия за ползване в кода", ", ".join(terms) or "няма https://…terms… в lib/ (Apple 3.1.2(c), M3)")
    uses_launcher = "url_launcher" in (repo / "pubspec.yaml").read_text(encoding="utf-8")
    (ok if uses_launcher else no)("връзките се натискат (url_launcher)", "" if uses_launcher else "адрес като текст не е „functional link“ (M4)")
    manage = re.search(r"apps\.apple\.com/account/subscriptions|play\.google\.com/store/account/subscriptions", dart)
    has_iap = "in_app_purchase" in (repo / "pubspec.yaml").read_text(encoding="utf-8")
    # Правилото за „достъп до отказване" е на абонаментите. Приложение само с
    # еднократни покупки (non-consumable) няма какво да се отказва - искането
    # на такава връзка там е измислен отказ, не предпазна мярка.
    # Признак за абонамент е API-то за абонаменти, не думата: `StreamSubscription`
    # е поток, а „без абонамент" в текст е точно обратното на абонамент.
    sells_subscription = bool(re.search(
        r"autoRenew|subscriptionPeriod|SubscriptionOffer|ProductType\.subs"
        r"|productId\s*[:=]\s*'[^']*(monthly|yearly|annual)"
        # Идентификаторът на продукта невинаги стои до думата `productId`:
        # Dog Journey го държи в таблица `'plus_monthly': 'com.…plus.monthly'`
        # и гейтът го обяви за еднократна покупка, тоест пропусна проверката
        # за връзка към отказване (намерено на 25.09.2026). Признакът е самият
        # низ, който изглежда като продукт с период.
        r"|'[\w.]*[._](monthly|yearly|annual)'",
        dart))
    if has_iap and sells_subscription:
        (ok if manage else no)("връзка за управление/спиране на абонамента",
                               "" if manage else "Play policy: direct access to cancellation → Subscription Center")
        _check_subscription_unlocks_something(sources)
    elif has_iap:
        ok("покупки", "еднократни (non-consumable) — правилото за отказване на абонамент не важи")
    if online:
        for u in sorted(urls):
            # curl, не urllib: python на тази машина няма CA пакет и пада с
            # CERTIFICATE_VERIFY_FAILED (виж reference-control-center-backlog).
            import subprocess
            code = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "10", u],
                                  capture_output=True, text=True).stdout.strip()
            code = int(code) if code.isdigit() else code
            (ok if code == 200 else no)(f"отваря се {u}", str(code))


def check_plist(repo: Path, arbs: dict[str, dict]) -> None:
    plist = repo / "ios/Runner/Info.plist"
    if not plist.exists():
        ask("Info.plist", "няма ios/Runner/Info.plist")
        return
    text = plist.read_text(encoding="utf-8")
    keys = re.findall(r"<key>(NS\w+UsageDescription)</key>", text)
    lprojs = sorted(repo.glob("ios/Runner/*.lproj/InfoPlist.strings"))
    if not keys:
        ok("purpose strings", "няма NS*UsageDescription — приложението не иска разрешения")
        return
    if not lprojs:
        no("purpose strings по езици", f"{len(keys)} ключа, но нито един *.lproj/InfoPlist.strings (A4)")
        return
    missing = [f"{p.parent.name}:{k}" for p in lprojs for k in keys
               if k not in p.read_text(encoding="utf-8", errors="ignore")]
    (no if missing else ok)("purpose strings по езици", ", ".join(missing[:8]) or f"{len(keys)} ключа × {len(lprojs)} езика")
    declared = set(re.findall(r"<string>([a-z]{2,3})</string>", text.split("CFBundleLocalizations")[1].split("</array>")[0])) if "CFBundleLocalizations" in text else set()
    undeclared = sorted({p.parent.name.split(".")[0] for p in lprojs} - declared)
    (no if undeclared else ok)("CFBundleLocalizations изброява lproj езиците",
                               ", ".join(undeclared) + " липсват — iOS няма да покаже превода" if undeclared else f"{len(declared)} езика")
    want = {l for l in arbs} - {"en"}
    have = {p.parent.name.split(".")[0].split("-")[0] for p in lprojs}
    gap = sorted(want - have - {"bg"} if "bg" not in have else want - have)
    if gap:
        ask("езици на purpose strings", f"ARB има {", ".join(gap)}, InfoPlist.strings няма")


def check_notes(repo: Path) -> None:
    """Бележките за ревюъра: дължина и как се говори за AI.

    M5 (24.09.2026): „no AI service“ в списък с липси донесе 2.1 и въпроси.
    Темата или не се отваря, или се затваря докрай.
    """
    files = list(repo.glob("docs/store-assets/apple-review/review-notes.txt")) + \
        list(repo.glob("store/apple-review/review-notes.txt"))
    if not files:
        ask("бележки за ревюъра", "няма review-notes.txt")
        return
    text = files[0].read_text(encoding="utf-8")
    (no if len(text) > 4000 else ok)("бележки ≤ 4000 знака", str(len(text)))
    mentions_ai = re.search(r"\bAI\b|artificial intelligence|machine learning", text)
    if mentions_ai:
        answered = re.search(r"NO artificial intelligence|no artificial intelligence or machine learning", text)
        (ok if answered else no)("бележките обясняват AI, не само го отричат в списък",
                                 "" if answered else "„AI“ се споменава мимоходом — M5: това носи 2.1 с три въпроса")


def check_store_text(repo: Path) -> None:
    files = sorted(repo.glob("tool/store_text/*.json")) + sorted(repo.glob("store/text/*.json"))
    if not files:
        ask("описания за магазините", "няма tool/store_text/*.json — описанията се пишат на ръка?")
        return
    for f in files:
        t = json.loads(f.read_text(encoding="utf-8"))
        desc = str(t.get("description", "")).replace("{price}", str(t.get("price_line", "")))
        blob = " ".join(str(v) for v in t.values() if isinstance(v, str)) + desc
        if PRICE.search(blob):
            no("написана цена в описанието", f.name)
        if not re.search(r"https://\S+(terms|privacy)", desc):
            no("правна връзка в описанието", f"{f.name}: няма https://…terms/privacy (M3, A5)")
        # A4, но в описанието: чужда азбука издава копи-пейст от друг език.
        # Намерено на живо в японското описание на Calctera (25.09.2026).
        lang = str(t.get("language", f.stem))
        if lang not in CYRILLIC_LANGS and CYRILLIC.search(blob):
            no("кирилица в чуждоезично описание",
               f"{f.name}: {', '.join(sorted(set(CYRILLIC.findall(blob)))[:3])}")
        # Дължини, които магазините отрязват мълчаливо.
        for field, limit in (("title", 30), ("short_description", 80), ("description", 4000)):
            if field in t and len(str(t[field])) > limit:
                no(f"{field} ≤ {limit}", f"{f.name}: {len(str(t[field]))}")
    if not any(r[0] == "NO" and "описанието" in r[1] for r in rows):
        ok("описания за магазините", f"{len(files)} езика: без цени, с правна връзка")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    repo = Path(sys.argv[1]).resolve()
    online = "--online" in sys.argv
    if not (repo / "pubspec.yaml").exists():
        print(f"NO\tрепо\t{repo} няма pubspec.yaml")
        return 1
    arbs = arb_files(repo)
    check_arb(repo, arbs)
    check_links(repo, online)
    check_plist(repo, arbs)
    check_store_text(repo)
    check_notes(repo)
    for state, what, detail in rows:
        print(f"{state}\t{what}\t{detail}")
    return 1 if any(r[0] == "NO" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
