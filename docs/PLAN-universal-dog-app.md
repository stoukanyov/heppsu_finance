# Universal Dog App — план за имплементация, функционалност по функционалност

Файл: `docs/PLAN-universal-dog-app.md` · v2, 14.09.2026 · стъпва на `ARCHITECTURE-universal-dog-app.md` (§7, §8, §9, §11), BRD v1.0, UX v1.0 и `LESSONS-LEARNED-beagle-owner-2026-09.md` (I1–I14). v2 = v1 след критика от три лещи (QA, бекенд, Flutter): 42 поправки приети, 4 отхвърлени (§6). Без срокове. Всяка функционалност е карта: обхват · бекенд · ядро/приложение · **тестове, написани ПЪРВО** · приемен тест · гейтове · зависимости · решения.

Легенда: 🧪 тест/гейт с име на файл · ⛔ нещо, което НЕ може да се провери преди определен момент, и се казва изрично · ⚖️ решение на Ив.

---

## 0. Как работим — системата за качество

Beagle Owner: ≈22 „поправки на поправката“, 4 отказа от Apple, дефекти, намирани на телефона на Ив след „готово“. Всеки има име (I1–I14). Този план не разчита на внимание — разчита на това, че грешният код не може да мине.

### 0.1 TDD — да, и точно така

| правило | механизъм |
|---|---|
| **Червено → зелено → рефактор** за всяка промяна в `app/`, `packages/`, `apps/` | `.githooks/commit-msg`: комит, който пипа тези пътища без staged тестов файл, се отказва; изключени пътища са изрично изброени (`l10n/`, `content/`, `assets/`, `docs/`, `*.arb`, `*.yaml` в content), не свободен текст; редът `НЯМА тест: <причина>` е позволен, а CI брои такива комити в PR с таван (2) |
| **Тестът се пуска ПРЕДИ имплементацията и трябва да НЕ мине** | 🧪 `regress.sh` като CI check-run за PR с етикет `defect`: тестовите файлове на PR-а се пускат върху merge-base и ТРЯБВА да не минат; без червен run PR не се слива. За нова функционалност гейтът е присъствие на нов тестов файл в diff-а (hook по-горе) |
| **Дефект = регресионен тест, който пада върху стария код** | правило на Ив от 02.08, сега с механизъм (regress.sh); комитът носи ред „Защо не беше хванато:“ |
| **Границата не се тества през стъб на самата граница** | I1: платежната верига беше „зелена“ с подменен разбирач. Apple/Google/хъб/SMTP/Postgres се тестват с истинския код върху записан истински вход (фикстура) или срещу истинската система на тестовата среда. Подправен JWS за нов bundle НЕ е доказателство — казва се ⛔ |
| **Една фикстура на един език за общата логика** | резолверът на Journey и квантизацията четат ЕДНА фикстура (`content/fixtures/journey_cases.yaml`, `tests/fixtures/location_cases.yaml`) от Python И Dart; lint пада, ако единият не я реферира |
| **Правило без механизъм не е мярка** (I14) | всеки ред тук сочи файл; `scripts/ll_gate.sh` прави `test -e` върху всяка пътека — Фаза 0 не завършва, докато не излезе с 0 |
| **Формулировка** | „минават / не минават“; `commit-msg` regex отказва „тест … падат/паднаха/падна … стария код“ (feedback-testove-minaha-ne-padnali) |
| **Хуковете са задължителни** | 🧪 `tests/test_githooks_installed.py`, `git_hooks_test.dart`: `core.hooksPath == .githooks`; `build_release.sh` и `deploy.sh` отказват без тях |

### 0.2 Пирамидата — какво се тества къде

| слой | инструмент | какво задължително покрива всяка функционалност |
|---|---|---|
| Бекенд unit | pytest; **SQLite само за тестове без база, с маркер `@pytest.mark.nodb`** | всяка функция на service слоя: щастлив път, отказ, граница |
| Бекенд с база | **само Postgres 17 в контейнер (testcontainers)** в CI | всичко, което докосва схема, JSONB, enum, backfill |
| Бекенд API | FastAPI TestClient с Host заглавка на приложението (иначе 421) | за всеки ендпойнт: без токен → 401; чужд ресурс → 404 (не 403, не 200); блокиран → невидим; валидация → 422; щастлив път |
| Бекенд визибилити | 🧪 `test_visibility_all_routes.py` — параметризиран по ВСИЧКИ маршрути от `app.routes` | П4: списък, id, известие, файл, споделена страница — един предикат; нов маршрут без запис = червен CI |
| Бекенд договор | `schemathesis` срещу локален процес в CI (Host зададен, mailer whitelist активен, планировчикът на F5 изключен под тест — lifespan флаг) | нито един 5xx за нито едно валидно по схема тяло |
| Ядро (Dart) чисти функции | `dart test` с фикстури | BreedResolver, JourneyEngine, WeightStatus, квантизация, дати по 18 локала |
| Ядро услуги | `mock_backend.dart` + **записани отговори от тестовата среда** (`test/fixtures/recorded/*.json`, `record_fixtures.sh`) | всеки Dart модел парсва всеки записан отговор; 🧪 `mock_backend` маршрутите ⊆ OpenAPI (статично) — и живият гейт в 0.3 |
| Widget + golden | `flutter test` + golden на **375×667 (SE-клас) и 430×932** × bg/en за всеки екран от UX спецификацията; golden се генерират **само в Linux CI** (таг `golden`, изключени локално на Mac) | Beagle Owner: golden ПРЕДИ преместването (днес 0), снимани през тестови обвивки (`minimal_scope.dart`, инжектиран часовник), без пипане на `lib/` до одобрението |
| Малък телефон и overflow | 🧪 `test/harness/small_phone.dart` (375×667) + `all_forms_use_small_phone_test.dart`: бутонът „Запази“ е във viewport (`getRect().bottom <= viewport`) **без** `scrollUntilVisible`; 🧪 overflow тест: всеки екран × 18 локала × най-малък размер × `textScaleFactor 1.3`, `RenderFlex overflowed` = провал | I2 (5): „Запази теглото под 7 карти“; golden bg/en не виждат немски/унгарски overflow |
| Интеграция на устройство | `integration_test` на **5 симулатора** (iPhone SE, среден, Pro Max, iPad-compat, Pixel 6) с манифест от **именувани** екрани за всяка F карта; **върви на Mac-а** — iOS симулатори не вървят на hosted Linux; неуспешен AVD = prod билд се ОТКАЗВА | преди ВСЕКИ билд към Ив; 🧪 `live_check.sh`: всеки `- [ ] <id>` в `RELEASE_BLOCKERS.md` иска `evidence: smoke/<sha>/<device>/<file>.png` от манифеста |
| Локализация — ARB | 🧪 `localization_completeness_test.dart` по glob (18), кирилица извън bg = провал, стойност == en извън allowlist = провал; `no_raw_server_message_test.dart` | I5 |
| Локализация — отвъд ARB | 🧪 `tests/test_no_cyrillic_in_api_errors.py` + `ErrorCode` enum (днес ~30 български `detail=`); `test_email_templates_18.py`; `test_share_html_18.py`; `ios_permission_strings_test` по СЪДЪРЖАНИЕ за `apps/*/ios`; Android `strings.xml` × 18 | четвъртият отказ на Beagle Owner беше език в native ресурси |
| Тихи провали | 🧪 `no_silent_catch_test.dart` (catch без DebugLog/rethrow/`// swallow:` = провал), `hasError` във всеки FutureBuilder; crash телеметрия: DebugLog ring-buffer в production, прикачен към тикета, `POST /tickets/crash` при следващ старт; „нерешен краш“ се затваря само със stack trace | I9 |
| Статичен анализ | бекенд: `ruff` (вкл. S), `mypy --strict` за новите модули, `bandit -ll`, `pip-audit`; клиент: `flutter analyze --fatal-infos --fatal-warnings`, `dart format --set-exit-if-changed`; инфра: 🧪 grep за `\s \? \+` в sed на скриптовете (BSD/GNU капанът) | CI, всеки PR |
| Документация | 🧪 `readme_covers_screens_test.dart` (всяка директория в `apps/*/lib/screens` е спомената в README); DoD: документация в кода при нова функция | feedback-definition-of-done |
| Съдържание | `build_content.py --check`: структурни правила отказват образа, политики изключват елемента | R1 нататък |

### 0.3 CI и гейтове — от ден 0

- `.github/workflows/ci.yml` в **двете** репота преди първата функционалност (I10). Hosted Linux. Без зелен check-run за sha: няма `tested/<sha>`, няма билд, няма merge в dev.
- `tested/<sha>` само от `deploy.sh dev` след health на тестовата среда И зелен CI за същия sha; когато diff-ът съдържа `alembic/versions/`, условие е и `rehearse_migrations.sh` върху възстановен Арес дъмп (локална стъпка на гейта; дъмпът не пътува до CI).
- **Production**: `deploy.sh prod --ot-iv "<дословната реплика на Ив>"` — ASCII-строг regex `\b[0-9a-f]{7,40}\b` (кирилско „е“ = отказ), точно едно съвпадение, prefix на `git rev-parse TARGET`; при успех анотиран таг `prod/<sha>` с текста на Ив; `prod/` тагове не се местят (🧪 `test_infra_deploy.py`); ред `LIVE: prod/<sha> <дата>` само след жив `/health`; `scripts/what_is_live.sh` за всеки въпрос за живо състояние. `main` само ff-merge от dev (guard_git.sh вече отказва комит на main).
- **Гейт към живата среда преди `flutter build`** (fail-closed, I3): `/health` връща `git_sha` и е потомък на `BACKEND_MIN_SHA` и на HEAD на бекенд клона (`merge-base --is-ancestor`); литералите `/api/v1/…` от `lib/` ⊆ живия `/openapi.json` (липсващ път = отказ с името му); `/health?deep=1` → `{db, smtp, subhub, store_keys{appstore, play}, fcm}` от жив опит — `false` = отказ; `config.py` отказва старт в production без `APPSTORE_*`, `GOOGLE_PLAY_*`, `SMTP_*`, `COCKPIT_*`, `PUBLIC_BASE_URL`; 🧪 `tests/test_service_health.py` (503 при паднал SMTP/хъб); `deploy.sh` не казва „готово“ при интеграция down.
- **`build_release.sh --app <key> --env test|prod`**: чисто дърво → `.tool-versions` (Flutter/Xcode/CocoaPods) → `disk_guard` → живият гейт → seed на съдържанието == sha на средата, към която се билдва → analyze + test → pack_lint + distinctness → **уникален номер**: +N от последния таг `build/*`, отказ при съществуващ таг/файл или N ≤ `store_max_build.sh` (ASC/Play API; недостъпен API = отказ, не пропуск), анотиран таг `build/<ver>+<N>`, `--dart-define=GIT_SHA` показан в Акаунт → билд → `verify_artifact.sh` (API_BASE_URL, applicationId/bundle на flavor-а, InfoPlist.strings × 18 по съдържание, versionCode) → манифест от 5 резолюции → име `<App>-<ver>+<N>-<env>.<ext>` → `releases/UPLOADS.md`, архив на Арес, локалното се трие. 🧪 `test/build_release_guard_test.sh` за всеки отказ.
- **Диск**: `DISK_MIN_FREE_GB` = 25 за обикновен билд, 45 за Xcode ъпгрейд; произход: `df` от 12.09.2026 (Data том 228 GB, 9,6 GB свободни; след `disk_reclaim.sh` ≈ 30–35 GB) — числото се записва в скрипта с датата, не се разхлабва на ръка (⚖️ D8 от част 2 за външен SSD).
- Един Xcode на машината; ъпгрейд на инструмент = отделен PR със зелен CI.

### 0.4 „Готово“ означава таблица с доказателства (I12)

| | какво | проверено с |
|---|---|---|
| ✅ | тестове: N unit / M API / K widget / G golden минават; червените преди имплементацията — check-run на `regress.sh` | CI, sha |
| ✅ | приемният тест на функционалността (картата) | команда + изход |
| ✅ | 18 езика без липси, ARB и отвъд | тестовете от 0.2 |
| ✅ | на устройство: 5 резолюции, именуваните екрани на картата | манифест `store/screenshots/smoke/<sha>/` |
| ✅ | тестовата среда: `tested/<sha>`, здраве 200, живата проверка на функцията (лог/curl с ред) | команда + ред |
| ⛔ | какво НЕ е направено / не е проверимо преди магазина | изричен ред, никога празен |

### 0.5 Дефекти — протокол

1. Доклад → доказателство от живата система (лог, база, API на стора) с цитирана команда; хипотези след това (`prompt_guard` hook).
2. Регресионен тест → `regress.sh` червен на стария код → поправка → зелен → „Защо не беше хванато:“ в комита; нов клас = нов гейт.
3. Дефект в клас, който вече има гейт = гейтът е дупкав → първо гейтът, после дефектът.
4. Цел: **0 известни дефекти при подаване** (`RELEASE_BLOCKERS.md` празен е гейт); всеки избягал дефект → `docs/DEFECTS.md` с клас и гейта, който го затваря.

### 0.6 Работен ритъм

Една функционалност = feature branch от `dev` = един PR (< ~400 реда производствен код; по-голяма функционалност се реже на вертикални срезове с тест). Merge само със зелен CI + `merge-base --is-ancestor origin/main dev` (hotfix в main, който не е в dev, е червен). Нищо в production и в магазините до одобрението на 1.2.7. Всеки production деплой и всяко подаване/активиране — с думата на Ив и sha.

### 0.7 Тестова поща и тестови акаунти (I13) — преди първия тест срещу тестовата среда

- `mailpit` в docker-compose на тестовата среда с `MP_SMTP_RELAY_ALLOWED_RECIPIENTS` (реалните тестери: адресите на Ив, `@heppsu.com`); `SMTP_HOST` на test → mailpit; кодовете се четат от `GET /debug/last-code?email=` (🧪 `tests/test_smoke_endpoint.py`: 404 при `ENV=prod`).
- `mailer.py` отказва RFC 2606 домейни (`example.com/.org/.net`, `.test`, `.invalid`) във всички среди — 🧪 `tests/test_mailer_reserved_domains.py` пада на днешния код.
- `scripts/store_session.sh`: `xcrun simctl erase` + свеж `<име>+qa-<дата>@heppsu.com` за всяка демо/скрийншот сесия. Нито един тест върху акаунт на Ив; нито един reset на негова парола.

---

## 1. Фаза 0 — фундаментът, преди първата функционалност

Без него всяка функционалност повтаря I2, I3, I8, I10. Редът е зависимост, не предпочитание.

| # | какво | тестове първо / гейт | зависи от |
|---|---|---|---|
| Ф0.0 | Хуковете и скриптовете: `.githooks/commit-msg` + `pre-commit` (файл > 5 MB, лични адреси, забранени думи) в двете репота; `regress.sh`; `.tool-versions`; `ll_gate.sh`; `disk_guard.sh`, `disk_reclaim.sh --dry-run`; sed-grep тест; **0.7 тестова поща**; `asc.py submission-check` (фикстурата от 10.09: 1 елемент → exit 1), `play_status.py track-check`, `STATUS_TEMPLATE.md`, `internal_accounts.txt` | 🧪 `test/scripts/*_test.sh` с фалшиви дървета: всеки отказ се доказва; `ll_gate.sh` = 0 | — |
| Ф0.1 | CI в MyBeagleApi: ruff, mypy (нови модули), bandit, pip-audit, schemathesis, `alembic heads == 1`, `alembic check`; **миграциите**: upgrade от ПРЕДИШНИЯ head върху фикстура **с редове и ръбове** (собственик без `privacy_settings`, `users.country` NULL, `dogs.breed ≠ 'Бийгъл'`, куче без owner country) — backfill-ите се твърдят по брой И по стойност; upgrade → downgrade → upgrade; необратимата enum стъпка обявена и идемпотентна (`ADD VALUE IF NOT EXISTS`); `rehearse_migrations.sh` върху Арес дъмп като условие за `tested/` при промяна в `alembic/versions/`; `app/db/types.py AwareDateTime` TypeDecorator + 🧪 статичен тест за всяка DateTime колона без него | самият CI; `test_migrations_postgres.py` | Ф0.0 |
| Ф0.2a | CI в клиента: format, analyze (fatal), test, `localization_completeness` (glob), `no_silent_catch`, `no_raw_server_message`, `test_count_gate` (allowlist, не брояч); трите ще паднат върху днешния код — това е списъкът за Ф0.2b | самият CI | Ф0.0 |
| Ф0.3 | Golden на Beagle Owner (Home, Health, Weight, Friends, Nearby, Account, Billing, SubscriptionRequired, Onboarding) × bg/en × 375×667 и 430×932; през тестови обвивки, замразен clock, фиксиран факт; **правилото „png + lib в един PR = червен“ важи само за `apps/beagle_owner/test/golden/`**, изключва чисти преименувания (`git diff -M100%`); за `apps/universal` — регенерация в същия PR при етикет `golden-update` + преглед на диффа | golden минават в Linux CI | Ф0.2a |
| Ф0.2b | Поправките от Ф0.2a: 23 `catch (_)`, 27 `e.message`, факти 9 → 18 езика (900 низа, ⚖️ Р3) | тестовете от Ф0.2a стават зелени; golden непроменени | Ф0.3 |
| Ф0.4 | Монорепо `heppsu-dogs`: `git mv` в `apps/beagle_owner` + workspace корен; нищо друго | CI зелен = доказано преместване; golden непроменени | Ф0.3 |
| Ф0.5 | Ядро `packages/dog_core` по клъстери (api/secure/jwt → auth → dogs/sync/mock_backend → billing → health/nutrition → social/places/… → reminder/locale/units → models); `packages/dog_ui` + `shared_screens.txt`; **🧪 `beagle_pack_golden_test.dart` се пише ТУК, преди `beagle_reference.dart` да мръдне** (19 точки, (0, 9.07), (9.07, 13.61), 0.10/0.20/0.30, `thirteenInch` не се преименува) | след всеки клъстер: тестове в двете директории, golden непроменени; `screen_dup_check.sh`; `check_core_clean.sh` се пуска едва в края на Ф0 | Ф0.4 |
| Ф0.6 | `AppIdentity` — 8-те зашити места (keychain ключове, bundle, product ids, push заглавие, terms URL) | 🧪 `beagle_identity_test.dart` пинва днешните низове — промяна = всички разлогнати | Ф0.5 |
| Ф0.7 | `CoreLocalizations` | 🧪 `core_l10n_parity_test.dart`: 18 × всеки enum == днешния AppLocalizations | Ф0.5 |
| Ф0.8 | Договор клиент↔среда: записани отговори (`record_fixtures.sh`), 🧪 `mock_backend ⊆ openapi`; 🧪 `test_client_compat_127.py` върху записани **заявки** на клиента от тага 1.2.7 (edge лог/replay); 🧪 `test_response_compat_127.py`: всеки отговор към Host beagle се парсва от Dart моделите на тага | всяко разминаване пада в CI, не на телефона | Ф0.1, Ф0.5 |
| Ф0.10 | Бекенд: `visibility.py` като слой + 🧪 `test_visibility_all_routes.py` (параметризиран по всички маршрути) | тестът пада на днешния код за маршрутите, които заобикалят предиката — това е списъкът за R0 | Ф0.1 |
| Ф0.11 | `docs/PRODUCT_FACTS.yml`: запис за **Beagle Owner сега** (цена, trial 30, product ids, 18 езика, 18+, изключени държави), запис за universal при ⚖️ Р15; 🧪 `test_product_facts.py` срещу ЖИВИЯ план на хъба (не self-reported конфиг), `product_facts_test.dart` (правни × 18, ARB, листинг); `store_facts_check.sh` срещу живите ASC/Play (оферти, цена, възраст, име на абонамента, езици) от `build_release.sh prod` и ежедневно (launchd → Control Center) | I7 | — |
| Ф0.12 | **Изолация тест/production на устройството** (I3): flavor `test` с `applicationIdSuffix .test` / iOS bundle `<bundle>.test`, име „(Test)“, отделна икона, Firebase plist per flavor; DogStore/Keychain/LocaleStore с префикс `<env>/<userId>`; `verify_artifact.sh` проверява applicationId/bundle на flavor-а — важи и за Beagle Owner 1.3.0 | 🧪 `env_isolation_test.dart`: данни под env=test не се четат при env=prod; стар Keychain запис се презаписва без грешка | Ф0.5, Ф0.6 |

**Приемен критерий за Фаза 0 (проверим):** същият golden набор непроменен; същият allowlist на тестове; полетата на `verify_artifact.sh` за Beagle Owner, билднат от `apps/beagle_owner` през новия `build_release.sh`, равни на тези на 1.2.7 (78); CI зелен в двете репота; `tested/<sha>` издаден от CI-зелен sha; `ll_gate.sh` = 0.

---

## 2. Функционалностите

Редът следва зависимостите (§3). Кодовете F се ползват в клоновете и PR заглавията.

### F0 — Идентичност на приложението и регистър (бекенд, R0)

- **Обхват:** два записа в `app/core/apps.py` (beagle, universal); идентичност от Host на ръба (`X-App-Key` от nginx, игнориран в production ако не идва от ръба); `user_sessions.app_key NOT NULL server_default 'beagle'`; лимитът 1 сесия/акаунт става per `(user_id, app_key)` — иначе „вход в universal → Beagle Owner не е разлогнат“ не минава; `device_tokens.app_key`; push заглавие от регистъра (3-те зашити „Beagle Owner“); `/get-app` → `/go/{slug}` (F15); **изричен списък изключения от 421** с тест: `/health` през docker healthcheck на `localhost` (иначе контейнерът никога не е healthy и деплоят спира), `/content`, `/webhooks/appstore`, `/webhooks/google-play`, `/.well-known/*`, външната проверка MON-001; брояч 421 в `/health`.
- **Тестове първо:** 🧪 `test_apps_registry.py`; `test_edge_identity.py` (непознат Host → 421; изключенията → 200; заглавка от клиент в production се игнорира); `test_sessions_per_app.py`; `test_no_app_branching.py` (0 `if app.app_key ==` в service); `test_push_title_from_registry.py`; `test_infra_edge.py` върху ИСТИНСКИЯ nginx.conf (`nginx -t` + кой Host се проксира); `test_client_compat_127.py` + `test_response_compat_127.py` (Ф0.8).
- **Приемен:** deploy dev → `curl -H 'Host: test.<new>.heppsu.com'` → сесия с `app_key=universal`; `curl -H 'Host: test.mybeagle.heppsu.com'` → `beagle`; 421 броячът е 0 след smoke на Beagle Owner срещу test.
- **Гейтове:** `alembic heads == 1`; `test_visibility_all_routes`; `check_ingress.sh` след reload (всички стари и нови имена 200 + валиден сертификат) в `deploy.sh`.
- **Зависи от:** Ф0.1, Ф0.10, ⚖️ Р15 (име/домейн), Р16 (nginx на Арес — през test среда първо).
- **Store:** нищо.

### R0 добавка — колони и backfill, които F2/F3/F5/F14 чакат (бекенд, адитивно)

- `users.language/units/timezone` (tz NULL → дефиниран fallback), `dogs.residence_country`, `dob_precision`, `sex.unknown`, `neutered`, `onboarding_state` (JSONB, само след вход); `dogs.community_visible` с backfill от `privacy_settings.show_dogs_in_community` на собственика (дефиниран default за собственик без ред) + `user_app_community_consent` с consent('beagle') за същите потребители; `app_migrations`, tombstones (`POST /dogs` с tombstoned `serverId`/`client_dog_id` → 410), `POST /dogs` идемпотентен по `client_dog_id`, `PATCH /dogs/{id}` с `If-Match`.
- **Тестове първо:** 🧪 `test_visibility_backfill_127.py` (nearby/group-walks дават СЪЩОТО множество преди/след върху production-подобна фикстура) — **гейт на деплоя на R0**; `test_dog_create_idempotent.py` (пада на днешния `sync_service.dart:65-67` клас); `test_tombstone_refuses_resurrection.py` (пада на днешния код); `test_dog_patch_if_match.py`; `test_users_prefs_columns.py`.
- **Приемен:** Beagle Owner 1.2.7 срещу test: регистрация → куче → nearby → същите резултати като преди деплоя (записаните фикстури).

### F1 — Модел на породата и съдържателен конвейер (R1)

- **Обхват:** `dogs.breed_type` (PURE/MIXED_KNOWN/MIXED_UNKNOWN/UNKNOWN), `dog_breed_components`, `size_class`, `breed_key` = primary; `content/` (breeds index top-N, профили, size_classes, life_stages, sources, schema, fixtures) → `build_content.py` → JSON в образа → `/content/v1/*` с ETag; `ContentStore` със seed; `BreedResolver`.
- **Бекенд:** миграция + backfill beagle (по брой и стойност); StaticFiles + ETag + gzip; `CONTENT_SHA` в `/health` (≠ manifest → `/content` отказан); `pyyaml` пинат.
- **Ядро:** `content_store.dart`, `breed_resolver.dart`, `breed_reference.dart` (`BreedSizeVariant`).
- **Тестове първо:** 🧪 `test_breed_model.py` (CHECK, backfill, `breed_key == components[0]`, UNKNOWN без крива); `test_content.py` (структурни правила); `test_content_static.py` (ETag **заглавката** еднаква между два отделно построени образа — `os.utime` от хеша; 304 през истинския nginx на test, gzip → weak ETag; production без draft); `test_content_compat_seed.py` (старият парсер чете HEAD — „адитивно завинаги“); `content_store_test.dart` (seed без мрежа = beagle числата; повреден кеш → seed; 304 не пише; app update с по-нов seed върху валиден стар кеш → seed; revert на сървъра → сървърът печели; изтекло `effective_to` не се показва; смяна на език офлайн → seed/fallback en); `breed_resolver_test.dart` + `tests/test_journey_fixture.py` върху **същата** `journey_cases.yaml` (lint: и двата я реферират); health проверка `breed_key ≠ components[0]` = 0.
- **Приемен:** промяна на число в `content/` → deploy dev → тестовият билд го показва след refresh; `git revert` → връща се; офлайн от първи старт показва seed; seed на тестов билд == sha на **test** средата.
- **Гейтове:** `build_content.py --check` в Dockerfile (паднал lint = няма образ); `check_core_clean.sh`.
- **Зависи от:** F0; ⚖️ Р1, Р2, Р3.

### F-shell — Обвивката на universal (първа в R4)

- **Обхват:** `apps/universal`: тема/токени по UX §2 — **само light** (🧪 тест, че `darkTheme` не е зададена); 5 таба; **една таблица с маршрути** `routes.dart`, от която четат `distinctness_check.sh`, `notification_routes_test.dart`, deep-link allowlist на content lint и `app_links`; `AppIdentity` за universal; Firebase per flavor; `registerDeviceToken` (днес не се вика в Beagle Owner); flavors от Ф0.12; crash телеметрия (ring-buffer + `POST /tickets/crash`); вградено ръководство + „Съобщи проблем“ през тикетинга (SCR-ACC-008).
- **Тестове първо:** 🧪 `routes_table_test.dart` (всеки маршрут от UX §19 съществува; никой екран не се регистрира извън таблицата); `theme_light_only_test.dart`; `device_token_registered_test.dart`; `crash_ring_buffer_test.dart`; приемен за тикетинг: тикет от тестов билд с `app_key=universal` → ред в Control Center (гейт в стила на `/me/billing/config` от тикетинга — feedback-app-baseline-integrations).
- **Зависи от:** Ф0.12, F0.

### F2 — Онбординг (SCR-ONB-001…015, R4)

- **Обхват:** сплаш → език → държава („защо питаме“) → име → порода (търсене, популярни, всички, mixed, не знам) → mixed (компоненти/размер) → възраст (точна/приблизителна/само възраст/неизвестна) → пол (+ кастрация по-късно) → опционален профил → готово → тур (5 екрана, пропускаем). **Local-first** (5.1.1(v)): `OnboardingController` пази състоянието ЛОКАЛНО (env-префикс, secure store); кучето, `journey_interactions` и напомнянията на потребител без акаунт живеят локално и се избутват идемпотентно при първия вход с `client_dog_id`; сървърният `onboarding_state` само след вход. С `breed_hint` от кампания (F15) → породата предизбрана и видима с „Change“.
- **Тестове първо:** 🧪 `onboarding_state_machine_test.dart` (всеки преход, пропускане, връщане, възобновяване локално и от сървъра след вход, breed_hint път, „без акаунт → Today работи“); widget + golden за 15-те екрана × 2 размера × bg/en; `product_tour_test.dart` (5, пропускаем, достъпен после от Акаунт); `test_onboarding_state.py` (запис/четене след вход, идемпотентно); `local_dog_push_on_login_test.dart` (0 дубликати при повторение); `journey_basis_disclosure_test.dart` (mixed/unknown → текст за базата видим) — тук, защото приемният на F2 го иска; l10n 18 за всички нови ключове от първия комит.
- **Приемен (UX §20 #1, #2, #5):** онбординг без здраве/тегло/чип; второ куче без повторно въвеждане; mixed/unknown получава Journey с обяснение на базата; Today без акаунт.
- **Гейтове:** smoke на 5 резолюции с именуваните 15 екрана; `journey_without_account_test.dart`.
- **Зависи от:** F1, F-shell, R0 добавка; ⚖️ Р19.
- **Store:** скрийншот №3 (Breed picker).

### F3 — Много кучета, държава, единици (SCR-MDOG-001…003, ACC-002…004, R4)

- **Обхват:** dog switcher; съкратен онбординг за второ куче; „Кой се премести?“ (това куче / всички); account default country; единици авто/метрични/имперски; език.
- **Бекенд:** `PATCH /me/dogs/residence-country {scope}`; паспортът НЕ се пипа (FR-DOG-006).
- **Тестове първо:** 🧪 `test_residence_country_scope.py` (one/all; съсобствено куче не се сменя от несобственик; паспортът остава); `dog_switcher_test.dart` (текущото куче недвусмислено на всеки dog-specific екран — UX §20 #3; switching пази таба); `units_controller_test.dart`; `date_formatting_locales_test.dart` (18 локала).
- **Приемен:** две кучета, смяна на държава само за едното; паспортът на другото непроменен на сървъра.
- **Зависи от:** F2.

### F4 — Today + Journey (SCR-TOD-001…003, R4)

- **Обхват:** Today (hero + етап + „This week with Max“ + приоритетен стек ≤ 3 + бързи действия + Pack preview); Journey (stage rail 8 етапа, 8 UI карти от 13 категории); detail (4 секции); „Today never looks empty“; „insufficient profile“; Journey по size class за mixed/unknown с изрична база; Emergency vet на ≤ 2 докосвания от Today (бутонът тук, екранът в F8).
- **Бекенд:** `journey/items` + `journey/texts` × 18 + `life_stages.yaml`; `journey_interactions` (saved/remind later).
- **Ядро:** `JourneyEngine` — чиста функция, `basis ∈ {pure, components, size, age_only}`.
- **Тестове първо:** 🧪 `journey_engine_test.dart` + `test_journey_fixture.py` върху `journey_cases.yaml` (≥ 12 кучета); `today_never_empty_test.dart`; golden Today/Journey/Detail; `content` lint `forbidden_phrases` × 18 за медицински текст (пада върху нарочно грешна фикстура); `emergency_quick_action_test.dart` (≤ 2 докосвания от Today).
- **Приемен (UX §20 #11, #12):** Today не е празен за куче само с име; Emergency vet на ≤ 2 докосвания.
- **Гейтове:** медицинска безопасност в lint; `distinctness_check.sh` изисква `/today`, `/journey`, `/journey/:id`.
- **Зависи от:** F1, F2; ⚖️ Р4, Р5.
- **Store:** скрийншоти №1 и №2.

### F5 — Известия: център + push + напомняния (SCR-TOD-004/005, PACK-016; бекенд в R3, приложение в R4)

- **Обхват:** inbox (Today/Earlier/Social/Health) с deep link към реален екран; push с локализирано заглавие/тяло на сървъра (11 категории × 18); напомняния за ваксини/лекарства/Journey milestone от сървъра по `users.timezone`; предпочитания (5 категории, ⚖️ Р11 default за health); нативното разрешение само при включване.
- **Бекенд:** `notifications` (inbox), `notification_preferences` + колони, `notifications/texts/<lang>.yaml`; **планировчик в процеса**: таблица `reminders` с `UNIQUE(source_kind, source_id, fire_at)`; Postgres advisory lock (uvicorn с > 1 worker = N планировчика); решение **at-least-once** с `sent_at` след push и дедупликация по UNIQUE при рестарт (контейнерът се пресъздава при всеки деплой); `users.timezone` NULL → fallback по държава, иначе UTC 09:00; health проверка `reminders_heartbeat`; планировчикът НЕ тръгва под TestClient/schemathesis (lifespan флаг).
- **Тестове първо:** 🧪 `test_push_localized.py` (11 × 18, заглавие от регистъра по app_key); `test_reminders_unique.py` (due_on → точно едно; повторен heartbeat → 0 нови); `test_reminders_concurrent.py` (два конкурентни изпълнителя → едно известие); `test_reminders_restart_between_push_and_sent.py`; `test_reminders_timezone.py`; `test_no_marketing_push.py` (dog_news/subscription opt-in false; няма категория migration); `notification_routes_test.dart` (всеки тип → маршрут от `routes.dart`); `test_notification_preferences_default.py`; `cold_start_from_push_test.dart` (маршрутът не се губи преди първия кадър).
- **Приемен:** ваксина с due_on утре на test → push на тестов телефон на езика на потребителя; inbox го показва; тап отваря ваксината; два worker-а → едно push.
- **Зависи от:** F0, R0 добавка (tz/language), F-shell; Firebase app за новия bundle (⚖️ Р15).

### F6 — Здраве (SCR-HLT-001…014; бекенд R3, приложение R4)

- **Обхват:** Health Home със status strip; тегло (тренд, очакван диапазон само при `basis ∈ {pure, size}`); ваксини; посещения (follow-up); лекарства (schedule, next dose, напомняния); conditions & allergies; labs & documents (файлове); диета; female health (условно); export (PDF след MVP — ⚖️ Р5; vet link в F10).
- **Бекенд:** `health_events` + 3 нови типа в enum (`ADD VALUE IF NOT EXISTS`, autocommit — Postgres тест), структурирани `schedule`, `allergy_type/reaction`, `follow_up_of_event_id`; `dog_documents` (kind, sha256 partial unique, лимит размер/тип, `client_max_body_size` в nginx); **кой сервира подписания URL** — маршрут в приложението, който стриймва (не статичния път на снимките), тестван през истинския nginx на test; сървърен `disk_guard` (507 под праг); седмо `LAST_SUCCESS` клеймо за `MEDIA_ROOT/documents` (прагът 26 ч); `DELETE /me` трие и документите (днес `dogs/service.py:355` трие само снимки) — 🧪 „0 файла на диска“; `SharedDogView` филтър по секции (F10).
- **Тестове първо:** 🧪 `test_health_enum_migration_postgres.py`; `test_health_events_visibility.py`; `test_documents_signed_url.py` (изтича; чужд → 404; тип/размер; през nginx на test); `test_documents_disk_guard.py` (507); `test_delete_account_removes_documents.py`; `test_medication_schedule.py` (next dose, край, timezone); widget + golden за 14-те екрана; `weight_expected_range_test.dart` (P7).
- **Приемен (UX §20 #13):** документ качен от тестов билд → подписан URL работи 1 h, после 404; лекарство със schedule → напомняне; бекъп клеймото на документите е свежо.
- **Зависи от:** F1, F5; ⚖️ Р5.

### F7 — Travel & ID (SCR-DOG-003…007; бекенд R3, приложение R4)

- **Обхват:** микрочип (колони на dogs — ⚖️ Р18); документи (ЕС паспорт, друг паспорт, здравен сертификат, друго) с издаваща държава ≠ пребиваване; travel readiness (произход/дестинация → чеклист от country rulesets с `last_reviewed_at`, източник, дисклеймър; stale правило никога не дава „met“; държава без ruleset → официален линк).
- **Бекенд:** `travel_documents` (details JSONB, `client_updated_at`), `PUT /dogs/{id}/eu-pet-passport` (upsert за F14), `countries/<CC>/ruleset.yaml` (BG + ЕС + top-N).
- **Тестове първо:** 🧪 `test_travel_documents.py` (upsert идемпотентен; съсобственик; visibility); `test_passport_country_independent.py` (FR-DOG-006); `content` lint за rulesets (effective dates, източник, review); `travel_readiness_test.dart`; golden за 5-те екрана.
- **Приемен (UX §20 #4):** пребиваване и издаваща държава са отделни полета и се показват отделно; stale правило се показва като „възможно е остаряло“.
- **Зависи от:** F1, F3, F6 (документи); ⚖️ Р8 (правно за паспорта — блокира подаването).

### F8 — Nearby (SCR-NBY-001…006, R4; бекенд R3)

- **Обхват:** ветеринари / спешни / хотели; карта/списък; радиус; open now; place detail; Emergency vet екран (отворените първи); pre-permission за локация.
- **Бекенд:** `PlaceOut.is_open_now` + `opening_hours_raw`; debug параметър `?now=` само non-prod (🧪 404 в prod).
- **Тестове първо:** 🧪 `test_opening_hours.py` (парсване, timezone на мястото, неизвестно → None; `?now=`); `emergency_vet_screen_test.dart` (отворените първи); `permission_primer_test.dart` (нативното разрешение само тук); golden.
- **Приемен:** unit тест с `now=22:00` местно: emergency показва отворените първи.
- **Зависи от:** F2; ⚖️ доставчик на места (BRD §29.6 — curated DB за v1).

### F9 — Pack (SCR-PACK-001…016; бекенд R3, приложение R4)

- **Обхват:** съществуващото (QR 10 мин, приятели, live location 5–60 мин с countdown и Stop, community presence OFF по подразбиране с точност град/държава, „В парка съм“, разходки + RSVP с куче) + филтър My breed / All при nearby dogs и walks, `audience` на разходка, per-dog `community_visible`, известие при RSVP, „Which dog is coming?“.
- **Бекенд:** `group_walk_events.audience`, `breed_key` snapshot, филтър `breed=mine|all` през visibility слоя; квантизацията остава СЪРВЪРНА.
- **Тестове първо:** 🧪 `test_location_quantization.py` върху `location_cases.yaml` (същата фикстура и в Dart); `test_community_visibility_three_conditions.py`; `test_walks_breed_filter.py`; `test_rsvp_notification.py`; `test_nearby_schema_no_precise.py` (OpenAPI: `NearbyDogOut` няма поле с > 2 знака); widget/golden за 16-те екрана; `live_location_countdown_test.dart`; QR: функционален тест сканиране → заявка → приятелство в списъка (без секунди).
- **Приемен (UX §20 #6–#10, #16):** видимост OFF по подразбиране; точна локация не съществува в community договора; блокът се вижда на следващата заявка в карта, приятели, разходки, известия.
- **Зависи от:** F0, R0 добавка (consent backfill), F5, Ф0.10.

### F10 — My Dog: профил, родословие, изложби, достъп и споделяне (SCR-DOG-001…018; бекенд R3, приложение R4)

- **Обхват:** Dog Profile / Edit Dog (смяна на порода → потвърждение за преизчисляване на Journey; медицинската история никога не се трие); родословие (дърво, link/placeholder, „X от Y в приложението“, потвърждение при чужд собственик); изложби (+ съдия, сертификат като документ); съсобственици; vet share със scope по секции, срок 1h/24h/7d/custom, лог, отмяна; per-dog privacy и settings (danger zone).
- **Бекенд:** `GET /dogs/{id}/relatives`, `show_results.judge`, `share_links.sections/expires/app_key`, `share_link_accesses`, споделената страница 9 → 18 езика.
- **Тестове първо:** 🧪 `test_pedigree_visibility.py` (публично ИЛИ приятели; чужд родител без разрешение = placeholder); `test_share_sections.py`; `test_share_access_log.py`; `test_share_html_18.py`; `test_co_owner_revoke.py`; `edit_dog_breed_change_test.dart` (потвърждение; здравните записи остават); golden; `pedigree_counter_test.dart`.
- **Приемен:** vet линк с 24 h и 2 секции → отваря се без акаунт, показва точно тях, логва достъп; след отмяна → 404.
- **Зависи от:** F6, F9.

### F11 — Безопасност: visibility слой, докладване, блокиране (FR-SAFE-001…005, R0 + всяка F)

- **Обхват:** `visibility.py` (Ф0.10) задължителна зависимост на всеки маршрут с ресурс; докладване на съдържание/потребител/куче/share link/документ/ревю на място; двупосочен блок през ЕДИН предикат; списък блокирани.
- **Тестове първо:** 🧪 `test_visibility_all_routes.py`; `test_block_everywhere.py` (след блок, на следващата заявка: приятели, карта, разходки, известия, споделени страници, файлове); `test_report_targets.py`.
- **Приемен (UX §20 #16):** блок в едно приложение → невидим в другото на следващата заявка (общ бекенд).

### F12 — Акаунт и paywall (SCR-ACC-001…009, PAY-001…003, R4)

- **Обхват:** акаунт; абонамент със състояния Trial / Active / Grace / Expired / **„Включено в абонамента ти Beagle Owner Plus“** (никога „legacy“) / **„проверяваме“** при недостъпен `/me/billing` (fail-open, не paywall, не краш); продукти незаредени от магазина → изричен текст, не празна цена; Manage линк само при съвпадение магазин+платформа (сървърът решава); Restore винаги вика магазина, после `/me/billing`; покупката изисква вход („Вече абониран? Влез“ — иначе local-first потребител купува втори път); paywall с 30 дни / локализирана цена / условия / връзки към Условия и Политика; expired state пази данните; изтриване с въвеждане на имейла, обяснение за съсобствени кучета и абонамента.
- **Тестове първо:** 🧪 `paywall_states_test.dart` (7 състояния × golden); `paywall_hidden_when_entitled_test.dart`; `purchase_requires_login_test.dart`; `manage_link_platform_test.dart` (4 комбинации; grep: нула `play.google.com` в iOS път); `restore_calls_store_then_server_test.dart`; `store_flags_test.dart` (`min_client_version`, `store_live`); `migration_empty_keychain_test.dart`; `billing_error_language_test.dart`; `legal_links_in_paywall_test.dart` (3.1.2); `test_delete_account_coowned.py` (съсобственото куче остава; абонаментът се отменя в хъба; audit ред без PII; документите изтрити).
- **Приемен (UX §20 #14):** състояние и Restore на 2 докосвания от всеки екран; изключен хъб → „проверяваме“.
- **Зависи от:** F13, Ф0.11.

### F13 — Entitlement леджър и билинг за две приложения (бекенд; R0 частично, R5 останалото)

- **Обхват R0 (beagle):** `store_entitlements` леджър; bundle/package match при verify (токен от друго приложение → отказ без `payment_failed` към хъба); агрегатор: `entitled` = хъб, леджърът пази от взаимно сваляне; `double_subscription` събитие + известие; Restore backfill; `/me/billing` с `origin_app`, `manage_url` по платформа; health: възраст на последния ASSN/RTDN по app_key.
- **Обхват R5 (universal):** верификаторите per bundle/package за новия bundle (днес единични), ASSN/RTDN за новия package; ⛔ **за новия bundle няма истински JWS/purchase token до първата sandbox покупка в universal (след ASC/Play запис)** — подправен вход не е доказателство; `test_webhook_new_bundle.py` минава с фикстура едва след тази покупка.
- **Тестове първо:** 🧪 `test_double_entitlement.py`; `test_verify_bundle_mismatch.py`; `test_hub_cancel_then_renewed.py`; `test_verify_owner_mismatch.py`; фикстури с **истински** подписани транзакции на beagle (sandbox JWS от 11.09) през реалния `SignedDataVerifier`; `test_billing_manage_url_platform.py`; `reconcile_entitlements` (леджър ≠ хъб → събитие) — **преди R5**.
- **Приемен = гейт на R6:** тестов телефон с Beagle Owner (sandbox абонат) + universal (тестов билд от TestFlight/internal track, за да има истински sandbox) → universal без paywall; отмяна в единия → другият остава; кръстосана платформа → текст без линк.
- **Зависи от:** F0; ⚖️ Р4/Р10 (продукт, цена, без intro offer); IAP продукт като чернова (F16).

### F14 — Миграция от Beagle Owner (SCR-MIG-001…006 + Beagle Owner 1.3.0; бекенд R0, universal страна R4, Beagle страна R7)

- **Обхват:** без копиране. Beagle Owner 1.3.0: тих upsert при sync на локалното (незкачени кучета с `client_dog_id`, `heightVariety`, hero, снимки след първата като `dog_documents`, ЕС паспорт → `travel_documents` **със съгласие преди първия PUT** за секцията на собственика, единици/език, reminder preferences); екран „Облачно копие“; tombstones винаги; дискретен ред „Още от Heppsu“ само при `store_live=true`. Universal: SCR-MIG-002 вход със същия имейл → `GET /me/migration` → SCR-MIG-003 „We found Max“ с броячи от сървъра → SCR-MIG-004 preview с изричния въпрос за community consent (⚖️ Р17) и равностоен „Продължи без“ → MIG-005 progress (възобновяем) → MIG-006 success → `PUT {completed}`, което НЕ блокира последващ sync от Beagle Owner с ново куче; свеж акаунт не вижда нито един низ за Beagle Owner.
- **Тестове първо:** 🧪 `test_migration_no_copy.py` (row count по таблица равен); `test_legacy_push_complete.py` (фикстура от 1.2.7; повторно → 0 нови реда); `test_migration_idempotent.py`; `test_migration_has_legacy_data.py`; `test_completed_does_not_block_new_dog.py`; `test_tombstones.py`; `sync_after_migration_test.dart`; `fresh_account_no_cross_app_test.dart`; `cloud_copy_consent_test.dart` (0 PUT паспорт преди съгласие); `migration_screens_golden_test.dart` (MIG-001…006, „Продължи без“ равностоен); `dog_switcher_display_breed_test.dart`; `check_forbidden_store_words.sh` върху ARB × 18 на двете приложения.
- **Приемен (UX §20 #15):** два билда на един телефон (flavor `test` изолира ги — Ф0.12), два акаунта: фаза 1 → фаза 2: паспорт, hero, variety, снимки, единици, език, напомняния видими; повторение → 0 нови реда; куче изтрито в universal → Beagle Owner не го пресъздава (410).
- **Зависи от:** F0, R0 добавка, F7, F13; ⚖️ Р7, Р8, Р9, Р17.

### F15 — Кампании по порода (§11 на архитектурата; бекенд R3, приложение R4, CPP R5)

- **Обхват:** `go.heppsu.com/<slug>` → router; `content/campaigns.yaml`; `acquisition_contexts` без PII преди акаунт; AASA + assetlinks на `go.heppsu.com` и `<new>.heppsu.com` (само universal); `app_links` + Install Referrer; `OnboardingContext.breedHint`; CPP × кампанийни породи през ASC API като чернова; отчет по кампания в Control Center.
- **Тестове първо:** 🧪 `test_go_router.py` (404 за непозната; iOS UA → CPP/App Store; Android → Play с URL-encoded referrer; `active:false` → основна); `test_acquisition_no_pii.py`; `test_aasa_assetlinks.py` + `check_ingress.sh` (200, без redirect, `Content-Type: application/json` на двата домейна); `campaign_onboarding_test.dart` (предизбрана + Change; смяна → hint не става истина); `install_referrer_parse_test.dart`; `cold_start_from_link_test.dart` (маршрутът не се губи преди първия кадър); `late_referrer_test.dart` (късен referrer обновява само ако породата още не е потвърдена); lint: `breed_hint` реферира съществуващ breed_key.
- **Приемен:** ⛔ Android Install Referrer работи само при инсталация от Play → изисква поне internal track (действие в магазина с думата на Ив); iOS CPP deep link — само след публикуване. И двете се записват като ⛔ до тогава; до момента се тества през Universal/App Link на инсталирано приложение.
- **Зависи от:** F2, F0; ⚖️ Р21, Р22; DNS за `go.heppsu.com`.

### F-legal — Правни документи като шаблон (преди R5)

- **Обхват:** ЕДИН набор × 18 шаблони с `{app_name, bundle, support_email}`; `sync_legal.sh`; `legal_brand` в `legal/router.py` / `html_view.py`; политиката за поверителност получава секции паспорт/документи/микрочип/известия за ДВЕТЕ приложения; Условия §8 от `PRODUCT_FACTS.yml`.
- **Тестове първо:** 🧪 `test_legal_parity.py` (18 × 3 документа × 2 приложения от шаблон; рендер с profile на universal без „Beagle“); `test_legal_covers_new_data.py`; `test_no_legacy_branding.py` (писма, push, share HTML).
- **Зависи от:** ⚖️ Р8, Р11 (правен преглед — прегледът е на сесията, Ив потвърждава), Р15.

### F16 — Готовност за магазините и различност (R5)

- **Обхват:** ASC/Play записи за новия bundle, IAP продукт с еквивалентна цена (чернова), листинги × 18 (+ Условия/Политика), скрийншоти 5 резолюции × 18 (първите три: Today / Journey detail / Breed picker), App Privacy labels / Data safety, App content въпросник, ASSN URL + RTDN за новия package, review notes в репото (честни: същият разработчик, споделен абонамент, два демо акаунта), `docs/STORE-COMPLIANCE-<app>.md`, план Б за 4.3 в `docs/`, `min_client_version`/store flags преди подаването.
- **Единствен вход към магазините (I6):** `store/storectl.py` — мутация без `--approved-by-iv "<цитат> <дата час>"` = dry-run с diff и общия ефект; deny в settings за `python3 -c *appstoreconnect*`, `curl *androidpublisher*`; `upload_ios.sh` като единствен път на .ipa (отказва при червени store тестове); `appstore_preflight.sh attach` — билдът не се закача към версията при IAP ≠ READY_TO_SUBMIT, демо акаунт, който не влиза в production, ASSN ≠ 200 → бутонът Submit физически не е активен; `postflight_ios.sh --expect-items 3` след „готово“.
- **Тестове/гейтове първо:** 🧪 `store/test_storectl.py` (мутация без флаг → SystemExit(2)); `store_listing_distinctness.sh`; `check_forbidden_store_words.sh`; `release_gate_store.sh`; `store_requirements_check.sh`; `distinctness_check.sh` (задължителни маршрути от `routes.dart`, 0 идентични файла между обвивките, първи маршрут Today, име не на `/Owner$/`); `test_get_app_platform.py`; `store_facts_check.sh` (Ф0.11).
- **Приемен:** `preflight` зелен; `PREFLIGHT_OK_<build>`; едно приложение в преглед в даден момент; всичко като чернова до думата на Ив.
- **Зависи от:** всички F за първата версия (⚖️ Р5); F-legal; ⚖️ Р15, Р12, Р22.

### F17 — Beagle Owner 1.3.0 като обвивка (R7)

- **Обхват:** обвивка над ядрото; само: облачно копие (F14), ядрото (невидимо), дефекти (`client_dog_id`, tombstones, `dog_switcher.dart:63`, чуждо куче без насоки → банер), правни документи (F-legal), flavor `test` (Ф0.12). Нищо друго.
- **Тестове първо:** 🧪 `beagle_owner_scope_test.dart` (не импортира journey_engine/breed_resolver/notification_routes/travel readiness); `foreign_breed_test.dart`; golden непроменени; `beagle_identity_test.dart`; 5 резолюции; `check_forbidden_store_words.sh` (what's new без „всички породи“).
- **Приемен:** 1.2.7 потребител обновява → нищо видимо освен „Облачно копие“; данните му са в universal след вход.
- **Зависи от:** F14, одобрение на universal (R6); ⚖️ Р7, Р12, Р14 (`min_client_version` за 1.2.x след 1.3.0 → 426 с ясен текст).

---

## 3. Ред на пускане

| етап | какво | какво се подава / деплойва |
|---|---|---|
| Ф0 | Ф0.0 → Ф0.1 → Ф0.2a → Ф0.3 → Ф0.2b → Ф0.4 → Ф0.5 → Ф0.6 → Ф0.7 → Ф0.8 → Ф0.10 → Ф0.11 → Ф0.12 | нищо; Beagle Owner се билдва байт-идентично от новото място |
| R0 | F0, R0 добавка, F11, F13 (beagle част) | production бекенд с изричен sha — **след одобрението на 1.2.7**; гейт: `test_visibility_backfill_127` |
| R0.5 | вход `<new>.heppsu.com` + `go.heppsu.com` (DNS, TLS, server blocks, AASA/assetlinks) | nginx на Арес през test среда първо (⚖️ Р16); `check_ingress.sh` |
| R1 | F1 (съдържание) | production бекенд |
| R3 | бекенд повърхности: F5, F6, F7, F8, F9, F10, F14 (universal страна), F15 | production бекенд, адитивно |
| R4 | F-shell → F2 → F3 → F4 → F5 → F6 → F7 → F8 → F9 → F10 → F12 → F14 (universal) → F15 | тестови билдове на Ив след всеки вертикален срез (flavor test) |
| F-legal | правни шаблони | production (`/legal`) |
| R5 | F13 (universal част), F16 чернови, `reconcile_entitlements`, store flags | чернови в магазините; първа sandbox покупка в universal (⛔ се затваря тук) |
| R6 | — | **подаване на universal първо** (sha + дума на Ив) |
| R7 | F17, F14 (Beagle страна) | Beagle Owner 1.3.0 след одобрение на universal |
| R8 | PDF export, `min_client_version` → 426 за 1.2.x, групирани content деплои | production бекенд |

Health проверки живеят с картата на повърхността си (не в R8): брояч 421 (F0), `reminders_heartbeat` (F5), диск `MEDIA_ROOT/documents` (F6), възраст на последния ASSN/RTDN по app_key (F13), `breed_key ≠ components[0]` (F1).

---

## 4. Какво измерваме

| метрика | цел | откъде |
|---|---|---|
| Известни дефекти при подаване | 0 | `RELEASE_BLOCKERS.md` празен = гейт |
| Избягали дефекти след подаване, по клас | всеки с регресионен тест и гейт за класа | `docs/DEFECTS.md` |
| PR без тест / комити „НЯМА тест“ над тавана | 0 | hook + CI |
| Тестове, минали срещу стария код | 0 | `regress.sh` check-run |
| Разминаване клиент↔среда, хванато на телефон | 0 | записани фикстури + жив гейт при билд |
| Билд към Ив без манифест от 5 резолюции | 0 | `build_release.sh` |
| Езици с липси (ARB, API грешки, писма, native) | 0 | тестовете от 0.2 |
| Production деплой без `prod/<sha>` таг с текста на Ив | 0 | `deploy.sh prod --ot-iv` |

---

## 5. Какво ми трябва от Ив, по ред на блокиране

1. **Р15** — име, bundle/package, домейн, цена: блокира F0, F13, F15, F16, F-legal.
2. **Р12** — Beagle Owner в магазина след новото (листнат / замразен / Remove from Sale след праг).
3. **Р8** — паспортът на сървъра (какво пазим, съгласие): блокира F7, F14 и подаването.
4. **Р5** — минималният отличителен набор за първата версия.
5. **Р2/Р3/Р4** — обем на породите и фактите, медицински преглед.
6. **Матрицата с породите** (F1).
7. **Р21/Р22** — домейн за кампании, кои породи първи.
8. **D8** (част 2) — външен SSD / архив: дискът е на 9,6 GB свободни.
9. Одобрение на 1.2.7 от Apple — до него: само Ф0 и feature branches; нищо в production и в магазините.

---

## 6. Отхвърлени при критиката (за да не се повдигат пак)

| предложение | защо не |
|---|---|
| Golden × light/dark като отделен гейт | universal е само light в v1; един тест, че `darkTheme` не е зададена |
| pre-commit „файл с ≥ 2 комита за 48 ч иска ред „Проверено на живо““ | покрива се от `live_check.sh` + evidence в манифеста |
| `regress.sh` за ВСЕКИ PR | само за PR с етикет `defect`; за нова функционалност гейтът е присъствие на тест |
| SQLite отпада изцяло от pytest | остава само за unit тестове без база с изричен маркер; всичко с база — Postgres 17 |
