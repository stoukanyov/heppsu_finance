# Universal Dog App — техническа архитектура v1

Ред: `docs/ARCHITECTURE-universal-dog-app.md`, 13.09.2026. Стъпва на BRD v1.0 + UX v1.0 (продуктова база), част 1 (`MyBeagleApi/docs/ARCHITECTURE-multi-breed.md`) и част 2 (`Business Partner/docs/ARCHITECTURE-multi-breed-2-stores-and-delivery.md`). Фактите за диска/клиента/политиките: `scratchpad/mb2_facts.md`. Всяко файл:ред е от прочетения код към датата; всяка мярка е скрипт, тест или гейт — не преценка. Без срокове.

Легенда в таблиците: ✅ решено · 🔁 обръща част 1/2 · ⚖️ Ив решава · 🧪 гейт (тест/скрипт).

---

## 0. Решението в едно изречение

Новото приложение е втора тънка обвивка (`apps/universal`) над едно Dart ядро (`packages/dog_core`) и над същия FastAPI бекенд (MyBeagleApi), в който породата е данна на кучето (`breed_type` + `dog_breed_components`), идентичността на приложението идва от ръба (Host → регистър с два записа), справочното съдържание (породи, размерни класове, 8 етапа, 13 категории Journey, country rulesets) е YAML в git на API репото, компилиран в образа и сервиран като статични JSON с ETag — „server-driven без app release“ се изпълнява с обикновен API деплой през гейта `tested/<sha>`, не с CMS/OTA; миграцията при общ акаунт не копира нищо (Beagle Owner избутва локалното идемпотентно, новото прави обикновен sync), абонаментът е един на човек в хъба, а леджър `store_entitlements` пази двете приложения от взаимно сваляне на достъпа; Beagle Owner влиза в режим поддръжка без нови продуктови повърхности.

### 0.1 Какво остава, какво се обръща

| | какво | кой |
|---|---|---|
| ✅ | Общ бекенд, без разклонения по приложение в service слоя (част 1 П1) | решено |
| ✅ | Породата е данна на кучето; `breed_key` = primary компонент (част 1 П2, §2.2) | решено |
| ✅ | Идентичност от ръба: Host → `app_key`; регистър с два записа в код (част 1 П3) | решено |
| ✅ | Един абонамент на човек в хъба Heppsu Subscriptions, `external_id = user.id` (част 1 П4; `billing/service.py:51`) | решено |
| ✅ | Едно приложение за всички породи, не 8 форка (част 2 препоръка); flavors само за BUILD_ENV | решено |
| ✅ | Диск/CI: hosted Linux CI, `disk_guard.sh` в `build_release.sh` (част 2 §6) | решено |
| ✅ | Seed на съдържанието в билда → офлайн от първия старт (част 1 §7.1) | решено |
| 🔁 | Съдържанието се сервира и от API (`/content`, StaticFiles + ETag), не само от билда; „публикуване“ = API деплой | ⚖️ Ив потвърждава (Р1) |
| 🔁 | Генераторът на пакети от Dart (`gen_breed_assets.dart`, част 1 §7) в Python в API репото (`scripts/build_content.py`) | решено |
| 🔁 | Съдържанието расте от „породен пакет“ до профил + размерни класове + етапи + Journey + държави | решено (BRD §9/§10) |
| 🔁 | „Миграция“ = избутване на локалното + sync, без `POST /migration/import` (BRD §21 при общ бекенд) | решено |
| 🔁 | Beagle Owner получава рилийз 1.3.0 (замразено приложение) — само облачно копие на локалното + ядро | ⚖️ Ив решава кога (Р7) |
| 🔁 | Част 1 §2.7 „снимките след първата се губят“ → качват се като `dog_documents kind=photo` | решено |
| ✅ | Правно за паспорта на сървъра (част 1 §10.11 тригер „приложение №2“) | ⚖️ Ив (Р8) |

---

## 1. Инвентар: има / липсва / променя се — по модул

Само сървър и клиент, които вече съществуват. Цитатите са файл:ред в `MyBeagleApi/app/modules/...` и `MyBeagle/lib/...`.

| модул (BRD §) | има | липсва | променя се |
|---|---|---|---|
| §8 Multi-dog, language, country | `dogs.owner_id` + `DogCoOwner` soft-revoke (`dogs/models.py:30-32, :70-109`); покана по код TTL 15 мин (`dogs/co_ownership.py:28`); `users.country` (`identity/models.py:56`) | `users.language`, `users.units`, `users.timezone`; `dogs.residence_country`; „apply to all my dogs“ | `identity/schemas.py:74-116` UserOut/UserUpdate + 3 колони; `PATCH /me/dogs/residence-country` |
| §9 Breed | `dogs.breed` String(120) default 'Бийгъл' (`dogs/models.py:49`; `dogs/schemas.py:12`); фактите в клиента `beagle_reference.dart:17-159` | `breed_type`, `dog_breed_components`, `size_class`, породен индекс, версия на съдържанието | `dogs.breed` става nullable display cache без default; истината = `breed_type` + компоненти + `breed_key` |
| §10 Journey | входове частично: `dogs.date_of_birth :50`, `sex :48`, `health_events.weight_kg` (`health/models.py:61`), `is_rabies_vaccine :80`; 4 `puppyTips` на 18 езика (`beagle_reference.dart:246-425`) | етапи, категории, съдържание, `journey_interactions`, `neutered`, `size_class`, `dob_precision` | `dog.dart:39-41` DogSex получава `unknown`; `dog.dart:101` dateOfBirth получава precision |
| §11 Health | единна линия `health_events` 12 типа (`health/models.py:22-86`); `/dogs/{id}/health-events` (`health/router.py:14-95`); хранене изцяло (`nutrition/models.py:16-50`) | structured `schedule`, `allergy_type`/`reaction`, `follow_up_of_event_id`, female типове, файлове, export за собственика | enum `health_event_type` (`health/models.py:47-49`) + 3 стойности (ALTER TYPE, autocommit); `HealthEventOut` се ползва и от `SharedDogView` (`sharing/schemas.py:7, :53`) → филтър по sections задължителен |
| §12 Travel & ID | `dogs.microchip_number` (`dogs/models.py:53`); ЕС паспорт САМО в телефона (`pet_passport_store.dart:22`, `eu_pet_passport.dart:161-217`); единственият файл на сървъра е `dogs.photo_filename :64` | `travel_documents`, `dog_documents`, readiness, country rulesets, микрочип метаданни | паспортът от `pet_passports.json` → `travel_documents.details` JSONB 1:1 |
| §13 Nearby | `places` категории + `emergency_care` (`places/models.py:32-43, :89-91`); haversine (`places/service.py:68-118`); ревюта `:116-137` | `is_open_now` | `PlaceOut` + `is_open_now: bool|None` + `opening_hours_raw`; без колона |
| §14 Pack | IntroductionToken 10 мин (`social/models.py:20-41`); Friendship; LocationShare с delete-on-read (`social/service.py:240`); GroupWalk + RSVP (`social/router.py:223-270`); квантизация СЪРВЪРНА (`privacy/service.py:19-20, :45`; `social/service.py:660-674`) | `breed=mine|all`, `audience`, RSVP известие, per-dog `community_visible` | `group_walk_events` + `audience`, `breed_key` snapshot; `list_nearby_dogs :677` през visibility слой |
| §15 Safety | reports/blocks (`moderation/models.py:24-31, :56, :90`); `blocked_either_way` (`moderation/service.py:109-155`) | visibility като СЛОЙ (част 1 §4.2.1: „формулировка, не защита“, `ARCHITECTURE-multi-breed.md:377`); target dog/share_link/document | `ReportTargetType` + 3; `_target_exists :36` |
| §16 Sharing | `share_links` scope 3 нива, token 32 байта (`sharing/models.py:20-30`); HTML изглед (`html_view.py`) | access log, sections, `app_key`; `SUPPORTED_LANGUAGES` = 9 (`sharing/schemas.py:20`) при 18 | 9 → 18 езика; `get_shared_view` (`sharing/service.py:91-133`) пише `share_link_accesses` |
| §17 Pedigree | `sire_id/dam_id` + placeholder имена (`dogs/models.py:38-45`); цикъл (`dogs/service.py:32, :217`); ≤6 поколения (`:39`); видимост `:124-192` | потомство, брояч „X от Y“ | `GET /dogs/{id}/relatives` обхожда и надолу със същия предикат |
| §18 Shows | `show_results` (`shows/models.py:16-32`) | `judge`, сертификат | + `judge`; сертификат през `dog_documents.show_result_id` |
| §19 Notifications | `device_tokens` FCM (`social/models.py:83-101`); `send_push` (`core/push.py:35-51`); 3 тригера с хардкоднато 'Beagle Owner' (`dogs/router.py:120, :227, :276`) | inbox, планирани напомняния (днес локални: `reminder_service.dart`), 9 категории; клиентът НЕ регистрира токен (`social_api.dart:88-98` не се вика; firebase не е в pubspec) | push title от регистъра по `device_tokens.app_key`; `notification_preferences` + 5 колони |
| §20 Subscription | хъб: `entitlement_for` кеш/stale/fallback (`billing/service.py:45-67`); verify Apple/Google (`appstore_verification.py:193`; `googleplay_verification.py:153`); webhooks (`webhooks_router.py:23, :36`) | леджър, per-app магазинна конфигурация (`config.py:103, :105` са единични; `appstore_notifications.py:74-77` връща None за чужд bundle) | `verify` (`appstore_verification.py:239-244`) връща и `originalTransactionId`+`expiresDate`; `payment_failed` при отказана проверка (`service.py:176, :182`) → лог + брояч |
| §21 Migration | почти всичко вече на сървъра (кучета, здраве, хранене, изложби, социално, privacy, home layout) | `app_migrations`, `client_dog_id`, tombstones; `user_sessions` лимит 1/акаунт (`identity/models.py:82-102`) избива другото приложение | сесии per `(user_id, app_key)` — ПРЕДУСЛОВИЕ |
| §22 Data model | Alembic единствен head `a3f61d0be274` (`alembic/versions/a3f61d0be274_*.py:13`) | 12 таблици (виж §3) | всичко адитивно; записаните тела на 1.2.5 минават непроменени |
| Клиент, ядро | 30 чисти услуги + 27 модела с тестове (`api_client.dart`, `auth_store.dart`, `sync_service.dart`, `dogs_api.dart:96-113`, …) | `content_store`, `journey_engine`, `documents_api`, `travel_api`, `notifications_api`, `migration_client`, `AppIdentity` | 8 зашити низа (`auth_store.dart:15-19`, `locale_controller.dart:19`, `units_controller.dart:37`, `purchase_service.dart:65`, `store_product_ids.dart:21`, `map_location_picker.dart:41`, `friends_screen.dart:463`, `debug_log.dart:44/:77`, `legal_links.dart:35`) → параметри |
| Клиент, дефекти | — | — | `sync_service.dart:65-67` дубликат при retry; `:57-61` възкресява изтрито; `dog_switcher.dart:63` суров `dog.breed`; `main.dart:112` intl за 9 от 18 локала |

---

## 2. Доставка: монорепо, ядро, две обвивки

### 2.1 Решено от фактите
- Два репозитория, не три: **MyBeagleApi** (бекенд + `content/`) и **MyBeagle → `heppsu-dogs`** (`git mv`, историята остава: 219 комита, 10 клона).
- **Pub workspace** (Dart `^3.12.2`, `MyBeagle/pubspec.yaml:22`; workspaces от 3.6). Без Melos до ≥3 пакета.
- Форк — отхвърлен (30 услуги × 2, два `mock_backend.dart` срещу един API). Flavors — отхвърлени (UX §1 иска различни табове/Home/тема; `if (flavor == beagle)` = клиентският §10.12; Apple 4.3(a) „variants… single app“ е дословният случай). Flavors остават за BUILD_ENV.

```
heppsu-dogs/
  pubspec.yaml                 # workspace: [packages/dog_core, packages/dog_ui, apps/beagle_owner, apps/universal]
  packages/dog_core/           # услуги, модели, CoreLocalizations (18 ARB), ContentStore, breed/journey engine, AppIdentity, test/ + mock_backend.dart
  packages/dog_ui/             # ЗАДЪЛЖИТЕЛЕН (не „по избор“): споделените екрани по shared_screens.txt — само през Theme.of(context)
  apps/beagle_owner/           # днешният MyBeagle; пакетът остава my_beagle (79 теста с package:my_beagle/ резолват)
  apps/universal/              # зависи САМО от dog_core + dog_ui, никога от apps/beagle_owner
  apps/*/assets/content/v1/    # seed = content_dist от production sha (build_release.sh го дърпа; без lock файл)
  scripts/                     # build_release.sh --app, disk_guard.sh, test_count_gate.sh, check_core_clean.sh,
                               # screen_dup_check.sh, distinctness_check.sh, store_listing_distinctness.sh, screenshots.sh
  .github/workflows/ci.yml     # hosted Linux
```

### 2.2 Ядрото `dog_core`
- **services/** — 30-те днешни (api_client, secure_http_client, secure_store, jwt_utils, auth_api, auth_store, dogs_api, dog_store, sync_service, health_api, nutrition_api, billing_api, entitlement_store, purchase_service, store_product_ids, social_api, meetups_api, places_api, moderation_api, pedigree_api, share_api, shows_api, privacy_api, ticket_api, reminder_service, reminder_preferences, calendar_service, save_with_side_effects, release_notes_service, debug_log, locale_controller, units_controller, build_config, splash_config) + нови: `content_store`, `documents_api`, `travel_api`, `journey_api`, `notifications_api`, `migration_client`.
- **models/** — 27 днешни (dog с `breedKey/breedType/components/dobPrecision/sex.unknown/neutered/sizeClass/residenceCountry`, health_event с новите полета, eu_pet_passport като travel document) + `breed_profile`, `life_stage`, `journey_item`, `country_ruleset`, `dog_document`, `travel_document`, `notification`, `store_entitlement`, `app_migration`.
- **identity/** — `AppIdentity {appKey, keychainPrefix, playPackage, iosBundleId, userAgentPackageName, storeProductIds, debugLogTitle, termsUrlBuilder, apiBaseUrl}` замества 8-те зашити места.
- **breed/** — `BreedResolver` (PURE/MIXED_KNOWN/MIXED_UNKNOWN/UNKNOWN → size_class + basis), `JourneyEngine` (чиста функция dog + records + content → карти), `assessWeight`/`WeightStatus.classify` с кривата като аргумент (днес `beagle_reference.dart:115-159`).
- **l10n/** — `CoreLocalizations`, ~120 ключа × 18 (enum етикети на 13-те UI-coupled модела).
- **test/** — `mock_backend.dart`, `in_memory_secure_store.dart`, 53 чисти тестови файла. Правило: файл се мести САМО с теста си, в същия комит.

### 2.3 `dog_ui` — задължителен
`packages/dog_ui/shared_screens.txt`: DogAvatar, DogSwitcherSheet, EmptyState, PermissionPrimer, MapLocationPicker, report/block sheet, NeedsSyncPrompt, BuildInfoFooter, QR show/scan, sparkline, Nearby карта, Friend profile, Meetups, Billing тяло, Blocked users, Delete account, Legal. 🧪 `scripts/screen_dup_check.sh`: клас с име от списъка съществува само в `packages/dog_ui`; копие в `apps/*` = червен CI. Токените на темата на universal (радиуси, типография, иконография) са различни — споделен компонент никога не дава еднакъв скрийншот.

### 2.4 Beagle Owner като обвивка без регресия (всяка стъпка = PR със зелен CI, в dev; main на Beagle Owner не се пипа до одобрение на 1.2.4(74))
- **S0** CI върху днешния код (`.github` липсва): `dart format --set-exit-if-changed`, `flutter analyze`, `flutter test`, `localization_completeness_test`; базова линия 82 файла / ~336 случая; 🧪 `test_count_gate.sh` = allowlist на тестови файлове (не брояч — броячът се изключва при първото легитимно сливане).
- **S1** Golden ПРЕДИ преместването (днес `matchesGoldenFile` = 0): Home, Health, Weight, Friends, Nearby, Account, Billing, SubscriptionRequired, Onboarding × bg/en × 375×812 и 430×932; замразен clock и фиксиран индекс на факта през `minimal_scope.dart`; реални шрифтове, генерирани в Linux CI и комитнати от артефакт. 🧪 PR, който пипа `.png` и `lib/` едновременно, не минава; регенерация само в отделен PR само с png + Flutter bump.
- **S2** `git mv` в `apps/beagle_owner` + workspace корен; нищо друго. 🧪 CI зелен = доказано преместване.
- **S3** `dog_core` по клъстери: (a) api_client/secure_*/jwt; (b) auth; (c) dogs/dog_store/sync/mock_backend; (d) billing/entitlement/purchase/store_product_ids; (e) health/nutrition; (f) social/meetups/places/moderation/pedigree/share/shows/privacy/ticket; (g) reminder/calendar/locale/units/misc; (h) models. Импортите `../../services/x.dart` → `package:dog_core/x.dart` (sed). След всеки клъстер: test в двете директории, golden непроменени.
- **S4** `AppIdentity`. 🧪 `apps/beagle_owner/test/beagle_identity_test.dart` пинва `'my_beagle_auth_token'`, `'my_beagle_auth_email'`, `'my_beagle_auth_country'`, `'my_beagle_auth_terms_accepted'`, `'my_beagle_auth_full_name'`, `'my_beagle_locale_override'`, `'my_beagle_weight_unit'`, `'com.heppsu.myBeagle'`, `'com.heppsu.myBeagle.plus.monthly'` — промяна = всички потребители излезли от акаунта.
- **S5** `CoreLocalizations`. 🧪 `core_l10n_parity_test.dart`: 18 локала × всеки enum член == днешният AppLocalizations.
- **S6** Breed/content: `beagle_reference.dart` → `dog_core/breed` с `ContentStore` (seed само beagle пакет, без journey глоб, remote изключен за Beagle Owner). 🧪 `beagle_pack_golden_test.dart`: 19 точки, (0, 9.07), (9.07, 13.61), (0, 13.61), 0.10/0.20/0.30; `Dog.fromJson({'heightVariety':'thirteenInch'})` → (0, 9.07). Кодовете не се преименуват (`dog.dart:263`).
- **S7** Едва сега `apps/universal`. Временно копие на `screens/` е позволено само като скеле, което се трие екран по екран; 🧪 `screen_dup_check.sh` + `diff -rq apps/beagle_owner/lib apps/universal/lib` = 0 идентични файла преди подаване.

🧪 `scripts/check_core_clean.sh`: `grep -rnE "beagle|Beagle|бийгъл" packages/dog_core/lib` = 0 (allowlist `thirteenInch/fifteenInch` като данни); `grep -rnE "breedKey\s*==\s*'" packages apps` = 0.

### 2.5 Каденция и хоризонт на Beagle Owner
- Промяна в `dog_core/{auth,api_client,secure_*,billing}` = задължителен билд на Beagle Owner (5 резолюции) + подаване като MINOR при следващото размразяване. 🧪 CI етикет `needs-beagle-release` при PR в тези пътища без нов таг на beagle_owner.
- 🧪 `git merge-base --is-ancestor origin/main dev` в CI на heppsu-dogs — hotfix в main, който не е в dev, е червен.
- Критерий за край на Beagle Owner (дял completed миграции / MAU) — ⚖️ Р13.

### 2.6 CI и диск
- CI на hosted Linux (дискът на Mac-а е на 95 %, mb2_facts §4); при промяна в `packages/**` тестовете и на двете приложения; golden само Linux.
- `scripts/disk_guard.sh` в `build_release.sh` преди всеки билд; `build/` и DerivedData се чистят между приложенията (reference-xcode-74).
- `build_release.sh --app <key>`: изходно име приложение + версия (feedback-release-filename); дърпа `content_dist` от production sha и отказва при разминаване с production манифеста; `screenshots.sh` ≥4 екрана × 5 резолюции × 18 езика при тестов рилийз.

---

## 3. Бекенд

### 3.1 Принципи и регистър
- `app_key` е СТОЙНОСТ (колона, аргумент, ключ в регистър), никога условие. 🧪 `tests/test_no_app_branching.py`: `grep -nE "if .*app_key|app_key\s*==|match .*app_key|APPS\[.*\]\.\w+\s*(==|if)" app/modules/*/service.py` = 0; allowlist само `billing`, `identity`.
- Регистър `app/core/apps.py` (Pydantic, от settings, два записа): `beagle {hosts: [mybeagle.heppsu.com, test.mybeagle.heppsu.com], ios_bundle_id: com.heppsu.myBeagle, apple_app_id, android_package, product_ids, push_title: 'Beagle Owner', legal_brand, default_breed_key: 'beagle', min_client_version}` и `universal {… TBD от Р15 …}`. 🧪 `test_apps_registry.py`: модел `App` съдържа само идентичност/продукти/URL/id-та — нито едно bool/поведенско поле (регистърът не става feature-flag система); bundle/package/product_ids не се пресичат; всеки host → точно един app_key.
- Ръб `app/core/edge.py`: nginx сетва `X-App-Key` по server block и го презаписва от клиента; middleware валидира; непознат Host → **421** + брояч в health check (не тих fallback към beagle). `X-App-Key` от клиента се чете само при `settings.environment != production` (🧪 тест). Изричен списък изключения (`/health`, `/content`, `/docs` само dev) в код с тест, че всичко друго дава 400. Cron/задачи работят с БД, не с HTTP.
- Единичните `APPSTORE_BUNDLE_ID`/`GOOGLE_PLAY_PACKAGE_NAME` (`config.py:103, :105`) стават deprecated псевдоними към `APPS['beagle']`. Push заглавие (`dogs/router.py:120, :227, :276`) → `APPS[device_token.app_key].push_title`. `legal/router.py` и `html_view.py` → `legal_brand`; правните документи стават ЕДИН набор × 18 шаблони с `{app_name, bundle, support_email}` от профила (не 74 файла). `/get-app` (`applink/router.py:12-14`) → `?app=<key>`.

### 3.2 Alembic (от `a3f61d0be274`)
R1 колони + backfill · R2 `ALTER TYPE … ADD VALUE IF NOT EXISTS` в `autocommit_block` (само `health_event_type` +3, `report_target_type` +3) · R3 нови таблици · R4 колони по social/sharing/notification_preferences · R5 tombstones/client_dog_id/app_migrations. Всички НОВИ изброими колони са `String(32)` + CHECK (или Pydantic Literal), не native enum — Postgres не маха стойност. 🧪 `test_migrations_postgres.py` в CI срещу Postgres контейнер: upgrade → downgrade → upgrade; R2 е обявена без реален downgrade (проверява се идемпотентност). 🧪 `alembic heads` == 1. 🧪 `test_client_compat_125.py`: записаните тела на 1.2.5 за POST/PATCH /dogs, health-events, nutrition, privacy минават непроменени; POST /dogs без `breed_type` през Host beagle → компоненти `[beagle]` (от `default_breed_key`); PATCH с `'breed':'Бийгъл'` не пипа компонентите.

### 3.3 По модули

**identity** — `users` + `language String(5) NULL`, `units String(8) NOT NULL server_default 'metric'`, `timezone String(64) NULL` (IANA, от клиента при вход); `user_sessions` + `app_key String(32) NOT NULL server_default 'beagle'`, лимитът става per `(user_id, app_key)` (`identity/models.py:82-102`, `service.create_session`) — предусловие. `app_migrations(user_id PK, source_app_key, target_app_key, status String, counts JSONB, legacy_pushed_at, completed_at)`; `GET/PUT /me/migration` идемпотентен; `has_legacy_data` се извежда от история `user_sessions.app_key='beagle'` или ред в app_migrations; PUT `legacy_pushed` след `completed` = 200 с обновени counts (Beagle Owner е жив). `user_app_community_consent(user_id, app_key, consented_at)` (част 1 §2.3). `DELETE /me`: `owned_photo_filenames` (`dogs/service.py:355`) → `owned_media(user)` включително документи.

**dogs** — колони: `breed_type String(16) NOT NULL` (CHECK PURE|MIXED_KNOWN|MIXED_UNKNOWN|UNKNOWN), `breed_key String(32) NULL` + CHECK `((breed_type IN ('PURE','MIXED_KNOWN')) = (breed_key IS NOT NULL))` — backfill `'beagle'`/`PURE` само за съществуващите редове, после server_default `UNKNOWN`; `residence_country String(2)` (backfill от `users.country`); `neutered Boolean NULL`, `neutered_on Date NULL`; `size_class String(8) NULL`; `dob_precision String(12) NOT NULL server_default 'exact'` (exact|month|year|age_only|unknown); `sex` + `unknown`; `community_visible Boolean NOT NULL` — **backfill := privacy_settings.show_dogs_in_community на собственика** + ред consent('beagle') за същите потребители (иначе A3 изпразва общността на 1.2.5); `hero_focus_x/y`, `hero_zoom Float NULL`, `variety String(32) NULL`; `microchip_implanted_on`, `microchip_location String(80)`, `microchip_registry String(120)` (1:1 върху dogs, `microchip_number` е там `:53`); `client_dog_id String(36) NULL` + UNIQUE(owner_id, client_dog_id); `deleted_at TIMESTAMPTZ NULL` (tombstone). `dogs.breed` (`:49`) nullable display cache, default 'Бийгъл' пада (`schemas.py:12`). Таблици: `dog_breed_components(id, dog_id FK CASCADE, breed_key, share Numeric(5,2) NULL, position SmallInt, UNIQUE(dog_id, breed_key))` (PURE=1, MIXED_KNOWN=1..N, иначе 0; 🧪 `breed_key == components[position=0]` и като SELECT в health check); `dog_breed_changes(dog_id, actor, old JSONB, new JSONB, at)`; `dog_access_events(dog_id, actor_user_id, subject_user_id, action, at)` (днес само последният цикъл, `dogs/models.py:95-98`). Ендпойнти: `PUT /dogs/{id}/breed` (идемпотентен; `breed_key` срещу content индекса, не хардкоднат списък; отговорът носи `journey_basis_changed`); `PATCH /me/dogs/residence-country {country, dog_ids|all}`; `POST /dogs` идемпотентен по `client_dog_id`; `GET /dogs/{id}` с ETag и `PATCH` с `If-Match` (412 при stale — два живи писача); `GET /dogs?include_deleted_since=`; `GET /dogs/{id}/relatives → {known, on_app, nodes[]}` и надолу със `_pedigree_visible_to` (`dogs/service.py:124-192`).

**health** — `health_events` + `schedule JSONB`, `reminder_enabled Boolean NOT NULL default false`, `allergy_type String(16)`, `reaction String(255)`, `follow_up_of_event_id FK SET NULL`, `details JSONB` (Pydantic discriminated union по type — 🧪 тест на всеки тип; никаква `dose_for_weight` функция). Enum + `heat_cycle`, `pregnancy`, `whelping` (spay = surgery + `details.kind`); показват се при `sex=female`. `GET /dogs/{id}/export?format=json&sections=` + `dog_export_log(dog_id, user_id FK CASCADE, sections, created_at)`; PDF по-късно през `html_view.py`. `reminders(id, dog_id, source_kind String, source_id, fire_at TIMESTAMPTZ, category, sent_at NULL, UNIQUE(source_kind, source_id, fire_at))` — `fire_at` = `due_on` 09:00 в `users.timezone`; източник и `journey_interactions.remind_at`. Напомнянията вървят като **lifespan задача във FastAPI** с Postgres advisory lock + ред `reminders_heartbeat(last_run_at)` — не crontab на хоста (контейнерът се пресъздава при деплой, `b9faedb`); мониторингът по MON-001 алармира при heartbeat > 30 мин. Push стига само до universal (Beagle Owner не регистрира токен) — локалните напомняния там остават.

**documents** (нов) — `dog_documents(id, dog_id FK CASCADE, uploaded_by FK SET NULL, kind String(24) [lab_result|vaccination_record|vet_visit|travel_document|show_certificate|photo|other], title, filename /* MEDIA_ROOT/documents/<dog_id>/<uuid>.<ext> */, content_type, size_bytes, sha256, document_date, provider, health_event_id FK SET NULL, travel_document_id FK SET NULL, show_result_id FK SET NULL, created_at)`; partial UNIQUE(dog_id, sha256) WHERE kind='photo'. `POST` multipart (10 MB, allowlist jpeg/png/webp/pdf; 507 под праг свободно място — сървърен disk_guard), `GET ?kind=`, `GET /{doc_id}/file` → 302 към подписан URL (HMAC doc_id+exp, TTL 5 мин; НЕ статичен път като снимките `dogs/schemas.py:58-62`), `DELETE`. Седмо LAST_SUCCESS клеймо за `MEDIA_ROOT` (reference-bekapi-klejma).

**travel** (нов) — `travel_documents(id, dog_id FK CASCADE, type String(24), document_number, issuing_country String(2) /* никога автоматично — FR-DOG-006 */, issuing_authority, issued_on, expires_on, details JSONB /* EU: 1:1 с eu_pet_passport.dart:161-217 */, client_updated_at, created_at, updated_at)`, partial UNIQUE(dog_id) WHERE type='eu_pet_passport'. CRUD + `PUT /dogs/{id}/travel-documents/eu-pet-passport` (upsert, last-write-wins по `client_updated_at`, връща победителя). Раздел V (бяс) остава `health_events.is_rabies_vaccine` (`health/models.py:80`). Секцията `owner` (адрес/телефон) е **изключена по подразбиране** от съсобственик, от share sections и от emergency. Travel readiness се смята **само в клиента** от content (без сървърен ендпойнт — един двигател, не два).

**journey** (нов) — `journey_interactions(id, dog_id FK CASCADE, item_id String(120), action String(12), remind_at NULL, acted_at, UNIQUE(dog_id, item_id))`; `POST/DELETE /dogs/{id}/journey/{item_id}/{action}`. Сървърният `journey.compute` връща САМО `{stage, size_class, basis, content_version}` (за `journey_milestone` push); картите се резолват само в клиента. Двата кода четат една фикстура (§4.6).

**content** — `app.mount("/content", StaticFiles(directory="/app/content_dist"))` до `_register_media` (`app/main.py:45-50`); Starlette 1.6.0 дава ETag/304. Без auth. gzip през nginx или `GZipMiddleware` (🧪 `Content-Encoding` при `Accept-Encoding: gzip`). При старт API сравнява `manifest.content_version` с env `CONTENT_SHA` (image label) и отказва `/content` при разминаване — ръчна редакция на `content_dist` е засечена.

**notifications** (нов) — `notifications(id, user_id FK CASCADE, dog_id FK SET NULL, category String(24) [health_reminder|vaccination|medication|journey_milestone|journey_suggestion|friend_at_park|group_walk|rsvp|co_owner_invite|vet_share_expiry|subscription] /* БЕЗ migration категория */, title_key, body_params JSONB, title, body /* рендирани на сървъра по users.language от content/notifications/texts/<lang>.yaml, fallback en */, deep_link String(200) /* от allowlist маршрути */, created_at, read_at, delivered_push Boolean)`; `GET /me/notifications?after=`, `POST /{id}/read`, `DELETE`. Push payload носи готов локализиран текст (не ключ — тавата не може да локализира) и никога здравни стойности. `notification_preferences` + `health_reminders, journey, dog_news, vet_share, subscription` (default false; `health_reminders` — Р11). `device_tokens` + `app_key`. Firebase: един проект, второ app регистриране за новия bundle → една FCM credential (🧪 `test_push_routing.py`: токен `app_key='universal'` се праща с профила universal и никога с beagle title).

**social** — `group_walk_events` + `audience String(12) NOT NULL server_default 'all'` + `breed_key` snapshot; `GET /community/nearby-dogs?breed=mine|all`, `GET /group-walks?breed=mine|all`; RSVP (`service.py:626`) известява организатора. Квантизацията остава сървърна за ВСИЧКИ клиенти (`privacy/service.py:19-20, :45`; `social/service.py:660-674`); 422 по app_key НЕ се въвежда (universal има клиентски тест, че не праща >2 знака).

**sharing** — `share_links` + `sections JSONB NULL` (NULL = стар scope), `app_key`; `SUPPORTED_LANGUAGES` 9 → 18 (`sharing/schemas.py:20`) + `html_view.py` на 18; `share_link_accesses(id, share_link_id FK CASCADE, accessed_at, ip_hash /* sha256(ip+дневна сол) */, user_agent, format)` в `get_shared_view` (`sharing/service.py:91`); `GET /dogs/{id}/share-links/{link_id}/accesses`; `vet_share_expiry` през reminders 24 ч преди `expires_at`. 🧪 emergency никога не носи `schedule`, `documents`, owner секция.

**moderation** — `ReportTargetType` + `dog`, `share_link`, `document`; `_target_exists` (`service.py:36`).

**places** — `PlaceOut.is_open_now bool|None` + `opening_hours_raw`; ограничен OSM парсер (24/7, `Mo-Fr 08:00-18:00; Sa …`); None при непознат синтаксис, никога изключение. `emergency_vet` НЕ става категория (`places/models.py:89-91`).

**shows** — `show_results.judge String(120) NULL`.

**billing** — `store_entitlements(id, user_id FK CASCADE, source_store String(8), source_app_key, product_id, store_subscription_id UNIQUE /* Apple originalTransactionId / Google purchaseToken */, latest_transaction_id, environment, status String(8) [ACTIVE|GRACE|EXPIRED|REVOKED], valid_until, last_verified_at, created_at, updated_at)`. Пълни се от `verify_purchase` (`billing/service.py:151`), ASSN, RTDN; `appstore_verification.verify` (`:239-244`) връща и `originalTransactionId`+`expiresDate`. Verifier по претендиран app_key, но след верификацията `bundleId`/`packageName` на транзакцията ТРЯБВА да съвпадне с профила → иначе 400 + event `bundle_mismatch`. ASSN `verifier_for` по `bundleId` от `JWSTransactionDecodedPayload` (`appstore_notifications.py:74-77`), `/webhooks/appstore/{app_key}` с жив псевдоним на стария път. Агрегатор `recompute(user_id)` е единственият говорител към хъба: ACTIVE|GRACE с `valid_until>now` → `renewed`; всички EXPIRED|REVOKED → `cancel`; GRACE без ACTIVE → `payment_failed`; разминаване на собственик → лог + брояч, никога `payment_failed` (`service.py:176, :182`). `GET /me/billing` + `source_store, source_app_key, product_id, valid_until, manage_subscription: {source_store, url|null}` — `url` само когато `source_store` == магазинът на платформата (`X-Platform` на ръба), иначе null. `POST /verify-purchase` с втори активен `store_subscription_id` → 200 `entitled=true` + `warning already_entitled_via` + известие `subscription`. Хъбът недокоснат: един продукт, един `SUBHUB_API_KEY` (`config.py:87-88`). 🧪 `reconcile_entitlements` нощно в health check: леджър ≠ хъб → аларма. 🧪 контракт cancel → renewed за същия customer (смяна на магазин).

### 3.4 Visibility policy (FR-SAFE-003 като слой)
`app/core/visibility.py`: `visible_dogs(viewer, app_key)` = own ∪ co-owned ∪ (community_visible ∧ owner.show_dogs_in_community ∧ consent(owner, app_key) ∧ ¬blocked_either_way ∧ ¬is_hidden) ∪ friends-of-my-dogs; `visible_events`, `visible_places`, `visible_notifications`, `visible_pedigree`. Прилага се като маркер-dependency `Depends(viewer_scope(...))` на всеки маршрут, който връща чужди данни (REST списъци, shared HTML/JSON, export, inbox, relatives, journey). 🧪 `test_visibility_all_routes.py` чете `route.dependant`; allowlist е файл `{route, reason}` с таван на броя, вдиган само с изричен комит. 🧪 `test_community_visibility_three_conditions.py`: всяко от трите условия изключено поотделно → невидим (пада днес: `nearby-dogs` проверява само акаунта). 🧪 `test_visibility_backfill_125.py`: nearby/group-walks за 1.2.5 върху production-подобна фикстура дават същото множество преди и след.

### 3.5 Гейт срещу изтичане на старото име
🧪 `test_no_legacy_branding.py`: при Host universal нито един човекочетим текст (share HTML, push title/body, писма — подател/тема/тяло, legal, `/get-app`) не съдържа `Beagle|Бийгъл|myBeagle`; продуктовите идентификатори (`com.heppsu.myBeagle.*` в manage URL) са изрично класифицирани като не-бранд.

---

## 4. Съдържание

### 4.1 Днес
Единствените справочни числа: `beagle_reference.dart:17-59` (варианти), `:77-97` (крива 19 точки), `:111-119` (прагове), `:246-425` (4 puppyTips на 18 езика със source). `beagle_facts.dart` 100 факта × 9 езика (9 липсват). На сървъра — нула; прецедент за файлове в образа: `legal/router.py:19`. Никъде няма етапи, размерни класове, породен индекс, rulesets, версия.

### 4.2 Формат (YAML в `MyBeagleApi/content/`, git = CMS, 0 таблици, 0 админ)
```
content/
  manifest.yaml                    schema_version: 1; review_warn_days: 180; review_stale_days: 365
  sources.yaml                     {id, publisher, url, retrieved_at, kind}
  breeds/index.yaml                {key, size_class, fci_group?, has_profile} · index.texts/<lang>.yaml ×18
  breeds/<key>/profile.yaml        BREED_PROFILE: size_class, varieties (кодовете НЕ се преименуват), combined_weight_kg,
                                   weight_curve, weight_thresholds, life_stage_overrides, life_expectancy, exercise, coat,
                                   temperament_tags, health_watch[{key, source_ids}], sources, review
  breeds/<key>/texts/<lang>.yaml · facts/<lang>.yaml
  size_classes/<toy|small|medium|large|giant>/profile.yaml · size_classes/facts/<lang>.yaml
  life_stages.yaml                 8 етапа × starts_at_months по size_class (AAHA котви; междинни = draft до източник)
  journey/items/<category>/<item_id>.yaml   id, category (13), ui_group (8), kind, medical, priority,
                                   targeting{stages|age_months, breed_keys, size_classes, sex, neutered, basis_required,
                                   requires_records, country_codes}, source_ids, effective_from/to, archived, review
  journey/texts/<lang>.yaml        title, notice, why, do, ask_vet ×18
  notifications/texts/<lang>.yaml  11 категории × title/body ×18 (push се рендира на сървъра)
  countries/catalog.yaml · <CC>/ruleset.yaml (vaccination items с review; travel rules с destination, requirements,
                                   effective_from/to, source.last_reviewed_at) · texts/<lang>.yaml
  fixtures/journey_cases.yaml      ЕДИНСТВЕНАТА фикстура за резолвера (Python и Dart я четат)
  approvals.yaml                   {item_id: {content_sha, reviewer, at}}
  schema/*.json · schema/ui_groups.yaml · schema/forbidden_phrases/<lang>.yaml · schema/url_allowlist.yaml
  glossary.<lang>.yaml
```
Таблица 13 категории → 8 UI карти: growth, development_milestones → Growth; nutrition, feeding_frequency → Food; behaviour, temperament → Behaviour; training → Training; activity → Activity; weight, preventive_care, senior_changes → Health; grooming → Grooming; fun_facts → Fun fact.

### 4.3 Резолюция mixed/unknown (в `dog_core/breed`, детерминистична)
PURE с профил → профилът; PURE без профил (`has_profile:false`) → size_class от индекса, `basis=size`, UI „още нямаме породни насоки за X“; MIXED_KNOWN → size_class = претеглена мода на компонентите; при разминаване >1 стъпка → пита за размер; ЧИСЛА само от size_class профила, никога претеглени породни криви (P7); `health_watch` на компонентите „може да важи“; MIXED_UNKNOWN/UNKNOWN → size_class от онбординга; без него и без възраст → само елементи с `basis_required: []`. `basis ∈ {pure, components, size, age_only}` се показва („Guidance for Max is based on…“). Етап = `starts_at_months[size_class]` по `ageInMonthsFrom` (`dog.dart:24-28`) + `dob_precision` (age_only/unknown → без етап). „Today never looks empty“ = fun_facts + нестадийни елементи. Днешните 4 puppyTips са първите 4 journey items.

### 4.4 Доставка — най-евтиният server-driven вариант
- `scripts/build_content.py` → `content_dist/v1/{manifest.json {schema_version, content_version, files[{path, sha256, bytes}]}, breeds/index.<lang>.json, breeds/<key>.json, breeds/<key>.<lang>.json, size_classes.json, life_stages.json, journey.json, journey.<lang>.json, notifications.<lang>.json, countries/<CC>.json, countries.<lang>.json, fixtures.json}`. `content_version = <дата на последния комит в content/>-<sha7 на sha256 върху сортираното съдържание>` — функция само от съдържанието, без .git в Docker; `os.utime` от хеша → детерминистичен ETag (🧪 две строения = байт-идентичен манифест).
- **Адитивно завинаги**: без `v2` директория. Dart моделите игнорират непознати полета (🧪 манифест с непознато поле се зарежда); lint „непознато поле = грешка“ важи за YAML източника, не за консуматора; несъвместима промяна = app release с нов seed (част 1 §7 остава в сила за този случай).
- Dockerfile: `COPY content` + `RUN python scripts/build_content.py` след `COPY scripts` (`infra/api.Dockerfile:20`); паднал СТРУКТУРЕН lint = няма образ = `deploy.sh` спира на build (`infra/deploy.sh:399`). `pyyaml` явно в `requirements.txt` (днес само транзитивен).
- Публикуване = комит в `content/` → `deploy.sh dev` → `tested/<sha>` → `deploy.sh prod` с одобрен sha (`infra/deploy.sh:98-178`); rollback = `git revert` + деплой. Цената е рестарт на контейнера (секунди) за двете приложения — приема се; bind mount + `--content-only` се отлага до доказана честота (първата истинска „втора система“). Nginx на Арес не се пипа ЗА СЪДЪРЖАНИЕТО (виж §7 R0.5 за домейните).

### 4.5 Клиент: `ContentStore` (~150 реда), версии, офлайн
- Seed = `content_dist/v1` от production sha, дърпан от `build_release.sh` (без lock файл); работи офлайн от първия старт. Кешът пази `{content_version, built_at, app_build}`; при старт `seed.built_at > cache.built_at` ИЛИ сменен `app_build` → кешът се трие, seed печели; сървър ↔ кеш = „различен sha“, не „по-нов“ → revert на сървъра се следва.
- Обновяване при foreground ≤1×/6 ч: `GET manifest.json` с `If-None-Match` → 304 → нищо; 200 → тегли само файлове с различен sha256 И само своя locale + неутралните, проверява, пише tmp+rename (`dog_store.dart:184-187`), манифестът последен; повреден кеш (отрязан JSON, грешен sha, чужд schema_version) → целият store на seed. Fallback en само при повреден кеш.
- Клиентът филтрира по `effective_to` при рендер и показва `last_reviewed_at` + `source_url` на всяко изискване до дисклеймъра на Travel readiness; `status: stale` → „възможно е да е остаряло“. Държава без ruleset → „нямаме проверени правила за X“ + официален линк от catalog.
- 🧪 `content_store_test.dart`: seed без мрежа възпроизвежда beagle числата; повреден кеш → seed; 304 не пише; app update с по-нов seed върху валиден стар кеш → seed; revert на сървъра → сървърът печели след refresh; правило с изтекло `effective_to` не се показва от кеш.

### 4.6 Един двигател, една фикстура
`content/fixtures/journey_cases.yaml` (≥12 кучета: pure с/без профил, mixed known съгласувани/разминати, mixed unknown с/без размер, unknown с/без възраст × sex/neutered; изход: basis, size_class, stage, curve_ref, списък item_id). 🧪 `tests/test_journey_fixture.py` и `dog_core/test/journey_engine_test.dart` четат СЪЩИЯ файл (клиентът от seed); lint пада, ако някой от двата теста не го реферира. Онлайн клиентът ползва `{stage, basis}` от сървъра само за паритет с известията; при разлика в `content_version` първо обновява съдържанието. Известие с `item_id`, който липсва локално → refresh; при неуспех заглавие по категория.

### 4.7 pack_lint (`build_content.py --check`, и като `tests/test_content.py`)
**Структурни (отказват образа):** 1 схема, непознато поле = грешка; 2 референтна цялост (source_id, item_id ↔ texts, breed_key ↔ index, requirement ↔ catalog, ui_group ↔ category, fixture ↔ тестове); 3 всичките 18 езика (bg, cs, da, de, el, en, es, fr, hu, it, ja, ko, nb, nl, pl, pt, ro, sv) непразни за всеки текстов ключ, „очакван script по локал“ (не „кирилица само в bg“); 4 числа с ≥1 source_id, монотонна крива, растящи прагове, `starts_at_months` строго растящи от 0; 5 насочване (stages xor age_months; country_codes само preventive_care; basis_required ⊆ {age, weight, sex, neutered, breed, size}); 8 език на безопасността — forbidden_phrases ×18 за `do/why` на medical („дай…“, „кучето ти има…“, „give … supplement“, „your dog has…“) + дозировъчен regex `\d+\s?(mg|ml|mcg)(\s?/\s?kg)?` + списък лекарствени имена; `ask_vet` непразно; 10 id `^[a-z][a-z0-9_]{2,63}$`, файл под `journey/items` не може да бъде изтрит, само `archived: true` — CI сравнява id-тата с предишния production таг през git (без `published_ids.txt`); 12 `deep_link` ∈ фиксиран списък маршрути (същият файл храни `notification_routes_test.dart`), `source_url` и `sources.yaml.url` само от `schema/url_allowlist.yaml`, нула `http` в текстовете; 13 `source_hash` на en текста във всеки преведен запис — разминаване = грешка (регенерирането на 16-те езика става падащ билд, не забравена задача); 14 approved само ако `approvals.yaml[item].content_sha == текущия sha` на елемента.
**Политики (изключват елемента, печатат, НЕ спират билда):** 6 `effective_from ≤ effective_to`, изтекло → строи се `archived`; 7 review `draft|reviewed|approved` — `medical:true` (тегло, етапи, preventive_care, senior_changes, health_watch, vaccination) само approved с reviewer/reviewed_at; draft никога не се строи; 11 country rules: `last_reviewed_at` > 180 дни → `status: warn`, > 365 → `status: stale` (readiness никога не дава `met` от stale правило). Нито едно правило по дата не може да спре деплой на код. 🧪 `test_content_policy_excludes_not_fails.py`. `--strict` е отделен CI job, задължителен само за PR, който пипа `content/`. 9 golden: beagle профилът = точно днешните числа (тестът е написан ПРЕДИ преместването).

### 4.8 Медицински преглед и превод — честно
Днес `approved` = сесията събира от именуван източник, Ив преглежда bg/en и комитва `reviewer: "iv"` с `content_sha` — проследимост, не медицинска гаранция; приложението казва „насока, не диагноза“ (както `beagle_reference.dart:6-7`); думите approved/reviewed/vet-reviewed НЕ влизат в UI и листинг (🧪 върху ARB и листинг). Кой пише 18 езика: сесията пише bg + en, генерира 16 в същия комит, Ив преглежда bg/en; lint 3 + 13 правят частичен или застарял език невъзможен за публикуване. Обем за MVP: факти 100 × 9 липсващи езика = 900; Journey ~60 × 5 секции × 18 = 5 400; индекс 900 (top-50) или 6 300 (FCI); travel етикети ~360; push текстове 11 × 2 × 18 = 396 → ~8 000–13 000 низа (Р2, Р3).

---

## 5. Миграция и entitlement

### 5.1 Какво е вече споделено (не се мигрира)
`users` (`identity/models.py:23-65`), кучета със serverId (`dog.dart:136-140`), `dog_co_owners`, `health_events` (клиентът няма локално копие — `health_api.dart:9-30`), хранене, изложби, родословие, приятели/споделяния/разходки/preferences/device_tokens, `share_links`, `privacy_settings`, блокове, `home_widget_order`, билинг състоянието в хъба (`billing/service.py:51`). 🧪 `test_migration_no_copy.py`: броят редове по таблица за user_id преди/след фаза 2 е равен.

### 5.2 Локално-само → дестинация (всяка стойност с идемпотентен ключ)
1. Незкачени кучета (`dog_store.dart:118-119`) → `POST /dogs` с `client_dog_id` (дефект днес: `sync_service.dart:65-67` → дубликат; 🧪 пада на стария код).
2. `heightVariety`, `heroFocusX/Y`, `heroZoom` (`dog.dart:161-177`; `sync_service.dart:88-97`) → `dogs.variety`, `hero_*` през `PATCH /dogs/{id}` с `If-Match`; Beagle Owner 1.3 бута само dirty полета.
3. `photoPaths` след първата (`sync_service.dart:71-73` качва само първата) → `dog_documents kind=photo` (sha256 partial unique).
4. ЕС паспорт (`pet_passports.json`, ключ = локален dogId, `pet_passport_store.dart:26-31`) → dogId → `dogs.json[id].serverId` → `PUT .../eu-pet-passport {details, client_updated_at}`; раздел V не се дублира. Изисква изрична стъпка за съгласие (адрес/телефон на собственика) с отказ, който пуска всичко освен паспорта (Р8).
5. Единици (`units_controller.dart:36`), език (Keychain) → `users.units`, `users.language` през `PATCH /me`.
6. `reminder_preferences` (`reminder_preferences.dart:67`) → `notification_preferences`.
7. Локалните напомняния (`reminder_service.dart:8-9`) не се копират; universal ги пренасрочва от `health_events.due_on` (🧪 брой насрочени == брой due_on в бъдещето).
8. Keychain токен (`auth_store.dart:15-19`; без access group `secure_store.dart:20-26`) — не е стойност, а сесия: нов вход с имейл+парола или password-reset (писмата × 18, 🧪). Факт на деня, release notes, календар — per-installation, не се пренасят (казва се в SCR-MIG-004).
🧪 `test_legacy_push_complete.py`: фикстура от 1.2.5; след фаза 1 всяка стойност 1–6 е четима през Host universal; повторно изпълнение → 0 нови редове.

### 5.3 Потокът
- **Фаза 0** (бекенд, `tested/<sha>`): §3 R1–R5 + регистър + леджър + сесии per app + `/get-app?app=`. 1.2.5 продължава без промяна.
- **Фаза 1** (Beagle Owner 1.3.0, Р7): избутването е **тих upsert при `sync()`** — не продуктова повърхност. Екранът „Облачно копие на паспорта и снимките“ (собствена стойност, със стъпката за съгласие) и дискретен ред „Още от Heppsu“ в Account се показват само при `universal.store_live=true` от регистъра (сървърна конфигурация, не store release). Никога „growing/moved/new version“. Tombstones се зачитат ВИНАГИ (🧪 сирак с serverId в tombstones не се пресъздава — пада на `sync_service.dart:57-61`); „режим само издърпва“ НЯМА — ново куче от Beagle Owner след `completed` се създава нормално. `PUT /me/migration {legacy_pushed, counts}`.
- **Фаза 2** (universal): SCR-MIG-002 вход със същия имейл (handoff-code — Р9); `GET /me/migration`; `has_legacy_data=true` → SCR-MIG-003 „We found Max“ с броячи ОТ СЪРВЪРА → pull (`sync_service.dart:108-119`), снимка, документи, паспорт, пренасрочване → `PUT {completed}`. Прекъсване = повторение. Свеж акаунт (`has_legacy_data=false`) не вижда нито един низ с името на Beagle Owner (🧪 `fresh_account_no_cross_app_test.dart`). `has_legacy_data=true` + `store_live/min_version` неизпълнени → „данните ти са тук; паспортът ще дойде с обновлението на Beagle Owner“ + равностоен „Продължи без“.
- **Конфликти**: паспорт от две устройства → `client_updated_at`; полета на кучето → `If-Match` 412 + днешното правило (`sync_service.dart:20-25`); съсобственическите кучета не са предмет. 🧪 `sync_after_migration_test.dart`: редакция в universal → sync от Beagle Owner → стойността остава.

### 5.4 Entitlement — един на човек, нула двойни таксувания
Факти: Apple (developer.apple.com, „Offering a subscription across multiple apps“, 13.09.2026): „create a separate and equivalent auto-renewable subscription for each app“, „your server must grant access to the subscription content across all apps“, „Failing to persist the purchase to the other apps opens the possibility of a user paying multiple times“; Play проверява `purchaseToken` само с `packageName` на продавача (`googleplay_verification.py:115-120`). Магазините НЕ помагат.
- **Слой 1 UI**: universal никога не показва paywall при `entitled==true`; SCR-ACC-007 „Включено в абонамента ти Beagle Owner Plus“ (никога „legacy“); Manage линк САМО при съвпадение на магазин и платформа, иначе текст „управлява се в <App Store|Google Play> на другото ти устройство“ без URL (🧪 4 комбинации в двете приложения; grep: нула `play.google.com` в iOS път и `apps.apple.com/account` в Android). Restore ВИНАГИ вика магазина, после `GET /me/billing`; при entitled от сървъра → „Достъпът е активен“, не „нищо не е намерено“. Бутонът за покупка изисква вход („Вече абониран? Влез“) — иначе local-first потребител купува втори път.
- **Слой 2 сървър**: леджър + агрегатор (§3.3 billing); `double_subscription` event + известие `subscription` с deep link към Manage.
- **Слой 3 хъб**: един продукт, един ключ; `lifecycle.py:32-41` отказва втори абонамент. Trial от хъба не се повтаря; intro offer в магазина е per продукт (Р10).
- Продуктите са еквивалентни (еднаква цена/период във всеки storefront — 🧪 в регистъра), с различни display имена/описания × 18 с изричен текст за достъп в другото приложение. Backfill на леджъра: първият verify/restore/webhook (Restore в Beagle Owner минава през `billing_screen.dart:182-200`). Fail-open (`service.py:57-63`; `entitlement_store.dart:27-31`) остава — приет компромис с двоен обхват; 🧪 `entitled` никога не се извлича от леджъра.

---

## 6. Магазини и 4.3

### 6.1 С какво двете приложения са различен продукт (само видимото)
(1) Journey като център — Today с приоритетен стек, stage rail 8 етапа, 13 категории, detail с 4 секции (Beagle Owner е widget-grid, `home_screen.dart`); (2) всички породи + mixed/unknown първокласни (Beagle Owner няма избор на порода, `dog.dart:90-94`); (3) Travel & ID с readiness по rulesets, микрочип с регистър, документи с файлове; (4) Health като структурирано досие (medications schedule, conditions/allergies, labs & documents, female, export); (5) Notifications center + push; (6) нова марка, тема, 5 таба, друг bundle/package/Firebase/домейн, собствени продукти, шаблонни правни документи с новото име. Аргументът пред Apple е ФУНКЦИОНАЛЕН (различна IA и core loop), никога „различна аудитория“ — 4.3(a) казва именно аудиторийните варианти да са едно приложение.

### 6.2 Остатъчен риск и гейтове
Общият видим слой: OSM места, приятелства/разходки/QR, съсобственост, vet share, родословие, абонамент на същата цена. Наказанието е на ниво developer акаунт, в който е и My Life Within. Гейтове:
- 🧪 `distinctness_check.sh`: ЗАДЪЛЖИТЕЛНИ route-ове по UX §19 (`/today`, `/journey`, `/journey/:id`, `/notifications`, `/onboarding/breed`, `/onboarding/mixed`, `/dog/:id/travel`, `/dog/:id/travel/readiness`, `/health/labs`, report+block за dog/share_link/document/place review/user); броячите (екрани, ARB) са информационни, не гейт; 0 идентични файла между `apps/beagle_owner/lib` и `apps/universal/lib`; първият маршрут след онбординг е Today; app name не съвпада с `/Owner$/`.
- 🧪 `store_listing_distinctness.sh`: описанията × 18 не споделят изречение с листинга на Beagle Owner; първите три скрийншота на всяка резолюция са Today/Journey Detail/Breed picker (никога Nearby/Pack); perceptual hash различен; what's new на Beagle Owner 1.3.0 без „всички породи“; без „диагностицира/лекува/предписва“.
- 🧪 `check_forbidden_store_words.sh`: moved, replaced, new version, growing, migrate, legacy, old app и еквиваленти × 18 върху ARB на двете приложения и review notes.
- 🧪 `test_get_app_platform.py`: iOS UA → `apps.apple.com/app/id<apple_app_id>`, Android UA → `play.google.com/store/apps/details?id=`, никога файл, никога чужд badge при `from=ios`; без `apple_app_id` → 404.
- Review notes в репото (`docs/store/review-notes-<app>.md`), задължителни в `build_release.sh`: честно — същият разработчик има Beagle Owner (breed community), това е продукт за всички кучета, абонаментът е споделен по Apple multi-app; два демо акаунта (свеж с 2 кучета pure+mixed; entitled-via-Beagle при поискване). Едно приложение в преглед в даден момент.
- `docs/STORE-COMPLIANCE-<app>.md`: App Privacy labels (Contact Info: адрес/телефон от паспорта; User Content: документи/снимки; Coarse Location; Identifiers), Play Data safety, уеб URL за изтриване на акаунт, Photo picker без READ_MEDIA, ASSN URL per app, RTDN topic per package, IAP прикачени към версията, target API / Play Billing версия (`scripts/store_requirements_check.sh` пинва minSdk/targetSdk и `in_app_purchase` от pubspec.lock), категория Lifestyle (никога Medical/Health), Health apps декларация „за животни“. 🧪 `scripts/release_gate_store.sh` отказва store билд при неотметнат ред. Политиката за поверителност × 18 на ДВЕТЕ приложения получава секции паспорт/документи/микрочип/известия в СЪЩОТО подаване (🧪 `test_legal_covers_new_data.py`).
- Push: няма категория migration; `dog_news`/`subscription` opt-in false (4.5.4); 🧪 `test_no_marketing_push.py`.
- 5.1.1(v): Today/Journey/My Dog работят без акаунт (кучето локално, seed съдържание); вход при Pack/Nearby/споделяне/sync с обяснение (🧪 `journey_without_account_test.dart`).

### 6.3 Какво Beagle Owner повече не получава
Избор на порода/mixed, Journey/Today, Travel readiness, Notifications center и push, документи/файлове UI, medications schedule/female/export, per-dog privacy/residence екрани, новата тема, `breed=mine` филтри, новия paywall. Получава САМО: облачно копие на локалното (1.3.0), ядрото (невидимо), дефекти (`client_dog_id`, tombstones, `dog_switcher.dart:63`, `main.dart:112`, не-бийгъл куче без насоки — 🧪 `foreign_breed_test.dart`: `breed_key != 'beagle'` → без WeightStatus/BeagleFact/puppyTips, банер „управлява се в <universal>“), правни документи. 🧪 `beagle_owner_scope_test.dart`: `apps/beagle_owner/lib` не импортира `journey_engine`, `breed_resolver` (освен ContentStore), `notification_routes`, travel readiness. Записано в `apps/beagle_owner/README.md`.

### 6.4 Абонамент през две приложения — Apple цитат
Apple 3.1.2(a): „You may offer a single subscription that is shared across your own apps and services, but these subscriptions may not extend to third-party apps or services.“ 3.1.3(b): достъпът до купено другаде е допустим „provided those items are also available as in-app purchases within the app“, и „must not directly or indirectly target iOS users to use a purchasing method other than in-app purchase“ — оттук правилото за Manage линка по платформа (§5.4).

### 6.5 Банерът
Няма банер „Beagle Owner is growing“. Има: (а) екран „Облачно копие“ като функция на Beagle Owner; (б) дискретен ред „Още от Heppsu“ в Account/About, показван само при `store_live=true`; (в) в universal — SCR-MIG-003 само при `has_legacy_data`. Линкът от (б) минава през `/get-app` с платформен redirect.

### 6.6 План Б за 4.3 (комитва се в `docs/` преди подаването, Р12)
(а) 4.3 върху universal → обжалване с едностраничен документ „какво е различно“ + различни скрийншоти, подготвен предварително; (б) 4.3 върху Beagle Owner 1.3.0 → 1.2.4 остава последната магазинна версия, миграцията минава само през SCR-MIG-002, локалното се въвежда наново; (в) при настояване за консолидация → Beagle Owner Remove from Sale, инсталираните работят срещу общия бекенд (адитивният договор 1.2.5 го гарантира).

---

## 7. Ред на работа и подавания (без срокове)

Всяка стъпка = feature branch → dev → `tested/<sha>` → main с одобрен sha; unit тестове в същата промяна; SemVer (universal 1.0.0; Beagle Owner 1.3.0 MINOR).

| # | етап | приемен тест |
|---|---|---|
| R0 | Бекенд-фундамент: регистър + edge, сесии per app, dogs/users колони + backfill (вкл. `community_visible`/consent), компоненти, `client_dog_id`/tombstones, `If-Match`, visibility.py, billing леджър + per-app верификатори + bundle match + Manage по платформа, `app_migrations`, travel_documents + upsert, dog_documents, push title от регистъра | `test_client_compat_125`, `test_sessions_per_app`, `test_visibility_all_routes`, `test_visibility_backfill_125`, `test_double_entitlement`, `test_webhook_new_bundle`, `test_verify_bundle_mismatch`, `test_migrations_postgres`, `alembic heads == 1`; deploy dev → Beagle Owner 1.2.4 от TestFlight без регресия |
| R0.5 | Вход: DNS + TLS + `server_name` за `<new>.heppsu.com` (Арес) и `test.<new>.heppsu.com` (Деймос) в общия nginx, `X-App-Key` по block | `scripts/check_ingress.sh` след reload: всички стари и нови имена 200 + валиден сертификат; в `deploy.sh` като гейт; `test_infra_edge.py` (nginx -t) — Р16 |
| R1 | Съдържание: `content/` + schema + `build_content.py` + lint + mount + gzip + `CONTENT_SHA` + pyyaml pin; beagle профил (golden), 5 size class, life_stages, 4 puppyTips + породо-неутрални items, notifications texts × 18, BG + EU + top-N rulesets, индекс (Р2) | `test_content`, `test_content_static` (ETag, 304, gzip, production без draft), `test_journey_fixture`, образът се строи |
| R2 | Ядро (heppsu-dogs dev): S0 → S6; `dog_ui` със shared_screens | `test_count_gate`, golden непроменени, `beagle_identity_test`, `core_l10n_parity`, `beagle_pack_golden`, `check_core_clean`, `screen_dup_check`; Beagle Owner 1.3.0-internal се билдва, НЕ се подава |
| R3 | Бекенд нови повърхности (отделни клонове): health + R2 enum + reminders lifespan + notifications + sharing sections/accesses/18 + social audience/breed + places open_now + moderation targets + export + журнал | `test_reminders_heartbeat`, `test_push_localized` (11 × 18), `test_sharing_sections`, `test_share_access_log`, `test_documents_signed_url`, `test_opening_hours` |
| R4 | `apps/universal` (S7): D1 bootstrap+тема+5 таба+Firebase+registerDeviceToken; D2 Onboarding; D3 Today/Journey/Notifications; D4 My Dog (Travel & ID, documents, readiness клиентски, sharing, per-dog privacy/settings); D5 Health; D6 Nearby; D7 Pack; D8 Account + Paywall; D9 Migration MIG-002..006. 18 ARB от първия комит | `distinctness_check`, `notification_routes_test`, `content_store_test`, `journey_engine_test` (същата фикстура), `paywall_*`, `manage_link_platform_test`, `journey_without_account_test`, `fresh_account_no_cross_app_test`, `migration_empty_keychain_test`, `date_formatting_locales_test`, `screenshots.sh` 5 резолюции × 18 |
| R5 | Магазини като ЧЕРНОВА (Р15, Р10): ASC/Play записи, продукти с еквивалентна цена, листинги + IAP × 18, скрийншоти, Data safety/Privacy labels, App content въпросник, ASSN/RTDN за новия bundle, review notes | `store_listing_distinctness`, `check_forbidden_store_words`, `release_gate_store`, `store_requirements_check`, `test_get_app_platform`, `test_no_legacy_branding` (вкл. писма), `test_legal_covers_new_data`; нищо активно без думата на Ив |
| R6 | Подаване на universal ПЪРВО (след разрешаване на 1.2.4(74); едно приложение в преглед) | `tested/<sha>`, Ив дава sha; план Б в `docs/` |
| R7 | Beagle Owner 1.3.0 (след одобрение на universal; Р7): обвивка над ядрото, тих legacy push при sync, екран „Облачно копие“ + съгласие, tombstones винаги, дефекти, правни документи с новите секции; `store_live=true` в регистъра се пуска с деплой на конфигурация | `beagle_identity_test`, golden, `test_migration_idempotent`, `sync_after_migration_test`, `foreign_breed_test`, `beagle_owner_scope_test`, `check_forbidden_store_words`, 5 резолюции, `tested/<sha>` |
| R8 | След двете одобрения: `reconcile_entitlements`, health check с шестте нови проверки (§8), PDF export, content деплои групирани, `min_client_version` → 426 за 1.2.5 (Р14) | тест, че всяка проверка има праг и канал |

Приемни тестове на ниво система (test среда, два билда на един телефон, два акаунта): (1) вход в universal → Beagle Owner не е разлогнат; (2) фаза 1 → фаза 2: паспорт, hero, variety, снимки, единици, език, напомняния видими; повторно фаза 1 → 0 нови реда; (3) row count по таблица равен; (4) абонат в Beagle Owner → universal без paywall; отмяна в едното → достъпът остава, докато другото е ACTIVE; кръстосана платформа → текст без линк; (5) push от universal с новото име, share HTML/писма без Beagle; (6) промяна на число в `content/` → deploy dev → клиентът го вижда; revert → връща се; офлайн от първия старт; (7) куче изтрито в universal → Beagle Owner не го пресъздава; редакция в universal → sync от Beagle Owner не я презаписва; (8) блокиран потребител и съсобственик: nearby/walks/notifications/relatives/documents не изтичат; (9) `alembic upgrade head` върху production dump на test.

---

## 8. Гейтове и тестове (файлове)

**MyBeagleApi/tests/**: `test_apps_registry.py` · `test_no_app_branching.py` · `test_edge_identity.py` (421 при непознат Host, X-App-Key игнориран в production, изключения) · `test_sessions_per_app.py` · `test_client_compat_125.py` · `test_breed_model.py` (CHECK, backfill, UNKNOWN без крива, `breed_key == components[0]`) · `test_dog_create_idempotent.py` · `test_dog_patch_if_match.py` · `test_visibility_all_routes.py` · `test_community_visibility_three_conditions.py` · `test_visibility_backfill_125.py` · `test_location_quantization.py` (никога >2 знака, независимо от клиента) · `test_double_entitlement.py` · `test_webhook_new_bundle.py` · `test_verify_bundle_mismatch.py` · `test_verify_owner_mismatch.py` (никога `payment_failed`) · `test_billing_manage_url_platform.py` · `test_hub_cancel_then_renewed.py` · `test_legacy_push_complete.py` · `test_migration_no_copy.py` · `test_migration_idempotent.py` · `test_tombstones.py` · `test_migration_has_legacy_data.py` · `test_documents_signed_url.py` (чужд uuid 404, изтекъл подпис 403, DELETE /me → 0 файла, 507 под праг) · `test_shared_view_sections.py` (emergency без schedule/documents/owner; 18 езика) · `test_share_access_log.py` · `test_content.py` (структурни правила 1–5, 8–10, 12–14; golden beagle) · `test_content_policy_excludes_not_fails.py` · `test_content_static.py` (ETag детерминистичен, 304, gzip, `CONTENT_SHA`) · `test_content_compat_seed.py` (стар парсер чете HEAD) · `test_journey_fixture.py` · `test_push_localized.py` (11 × 18, без ключ в payload, без Beagle при universal) · `test_push_routing.py` · `test_no_marketing_push.py` · `test_reminders_heartbeat.py` (двоен пуск → едно известие; tz; journey remind_at) · `test_opening_hours.py` · `test_migrations_postgres.py` + `alembic heads` · `test_no_legacy_branding.py` (вкл. писма × 18) · `test_email_templates_18.py` · `test_legal_covers_new_data.py` · `test_get_app_platform.py` · `test_infra_edge.py` · `test_moderation_targets.py`. **Dockerfile**: `RUN python scripts/build_content.py` (структурен lint). **Health check**: `double_subscription` за 24 ч, възраст на последния ASSN/RTDN по app_key, `reminders_heartbeat`, свободно място `MEDIA_ROOT/documents`, rulesets с `stale`, брояч 421, леджър ≠ хъб, `breed_key` ≠ components[0].

**heppsu-dogs/**: `.github/workflows/ci.yml` · `scripts/test_count_gate.sh` (allowlist) · `scripts/check_core_clean.sh` · `scripts/screen_dup_check.sh` · `scripts/distinctness_check.sh` · `scripts/store_listing_distinctness.sh` · `scripts/check_forbidden_store_words.sh` · `scripts/release_gate_store.sh` · `scripts/store_requirements_check.sh` · `scripts/disk_guard.sh` · `scripts/screenshots.sh` · `scripts/build_release.sh --app` (seed от production sha, review notes задължителни) · `apps/beagle_owner/test/golden/*.png` + `golden_test.dart` · `apps/beagle_owner/test/beagle_identity_test.dart` · `apps/beagle_owner/test/foreign_breed_test.dart` · `apps/beagle_owner/test/beagle_owner_scope_test.dart` · `apps/beagle_owner/test/dog_switcher_display_breed_test.dart` (в dog_ui) · `apps/beagle_owner/test/cloud_copy_consent_test.dart` (съгласие преди първия PUT паспорт) · `packages/dog_core/test/core_l10n_parity_test.dart` · `beagle_pack_golden_test.dart` · `content_store_test.dart` · `journey_engine_test.dart` (същата фикстура) · `sync_after_migration_test.dart` · `reminders_rescheduled_after_pull_test.dart` · `date_formatting_locales_test.dart` (`main.dart:112`, 9 → 18) · `notification_routes_test.dart` · `client_quantization_test.dart` · `apps/universal/test/paywall_hidden_when_entitled_test.dart` · `manage_link_platform_test.dart` · `restore_calls_store_then_server_test.dart` · `purchase_requires_login_test.dart` · `journey_without_account_test.dart` · `fresh_account_no_cross_app_test.dart` · `migration_empty_keychain_test.dart` · `store_flags_test.dart` (store_live/min_version комбинации) · `localization_completeness_test.dart` (в трите пакета) · `arb_forbidden_phrases.sh` (notif*/journey* ключове).

---

## 9. Решения за Ив

| # | решение | препоръка | цена на алтернативата |
|---|---|---|---|
| Р1 | Съдържание = API деплой (git-като-CMS, StaticFiles, `tested/<sha>`), отменя част 1 §7 „само в билда“ (seed остава) | да | отделен bucket с ръчно публикуване = втора система за доставка при един поддържащ; „само в билда“ = BRD цел 10 неизпълнена |
| Р2 | Обхват на `breeds/index.yaml`: пълна FCI (~350 × 18 = 6 300 низа) или top-50 + свободен текст (900) | top-50 за v1, FCI след това | FCI веднага = +5 400 низа преди първия билд |
| Р3 | 40 или 100 факта на порода (`test/beagle_facts_test.dart:7-9` = 100 за bg/en); 900 низа на 9-те липсващи езика преди първия билд или изключение в `manifest.yaml` | 100, преведени; без изключение | изключение = отклонение от „всички езици, винаги“, записано, не мълчаливо |
| Р4 | Медицински reviewer (BRD §29.5): (а) approved = Ив, по-тежък „попитай ветеринар“ език; (б) платен ветеринарен преглед на `medical:true` преди go-live | (а) за v1, (б) преди широка реклама | (б) е разход и чакане; (а) е репутационен риск при грешно число — всяко число носи URL към източника |
| Р5 | Минимален отличителен набор за ПЪРВАТА подадена версия | Journey/Today, порода+mixed онбординг, Travel readiness, Notifications; Labs/export/female могат да са 1.x | по-малко = 4.3 сигнал; всичко = по-дълъг път до първата видима стойност (без срок, но структурен риск) |
| Р6 | `RemotePackSource` в MVP на universal; Beagle Owner само seed | да / само seed | без remote = BRD цел 10 не е изпълнена; remote в замразеното приложение = нова функция там |
| Р7 | Кога Beagle Owner 1.3.0 тръгва (замразено до 1.2.4(74)); задължителна ли е фаза 1 | след одобрение на universal; пожелателна с „Продължи без“ | без 1.3.0 паспортите остават в телефона и изчезват при деинсталация |
| Р8 | Правно за паспорта на сървъра: адрес/телефон на собственика — какво пазим, колко, съсобственик, share | owner секция изключена по подразбиране; срок = докато има куче; съгласие преди първия PUT | без решение подаването не тръгва (5.1.1 / Data safety) |
| Р9 | Handoff-code Beagle Owner → universal (TTL 10 мин) | не в MVP; само с verified App/Universal Links по-късно | без него: парола/password-reset (писма × 18 задължителни) |
| Р10 | Intro offer на новия продукт; политика при двоен абонамент (възстановяване, писмо) | без intro offer; писмо + връщане през магазина | с intro = втори безплатен месец за мигрирали (подарък, не таксуване) |
| Р11 | `notification_preferences.health_reminders` default true или false (прецедент `models.py:121-123` = false) | true | false = напомнянията за ваксини изискват настройка |
| Р12 | Значението на „Beagle Owner остава жив“ в магазинни термини: листнат и обновяем / замразен на 1.2.4 / Remove from Sale след праг на миграция | Remove from Sale след праг (стойност в Control Center), инсталираните работят | на витрината безсрочно = съзнателно носен 4.3 риск на ниво акаунт (My Life Within) |
| Р13 | Критерий за край на Beagle Owner (дял completed / MAU) | праг в Control Center | без критерий: две UI кодови бази без хоризонт |
| Р14 | `min_client_version` → 426 за 1.2.5 след като 1.3.0 е в магазините | да, след 1.3.0 | 1.2.5 продължава да възкресява изтрити кучета без tombstone логика |
| Р15 | Име, bundle (`com.heppsu.<new>`), package, домейн `<new>.heppsu.com`, push заглавие, цена (€0.99/месец е чернова); името не е вариант на „… Owner“, иконата без бийгълски цветове | — | без тях R0.5/R5/R6 не могат да започнат; „Dog Owner“ = вариант пред ревюъра |
| Р16 | Втори server block в общия nginx на Арес (риск за Groomelle, reference-vhodut-na-ares) — кога и с какъв прозорец | през test среда + `check_ingress.sh` | без него universal се тества само срещу localhost |
| Р17 | Пренасяне на community consent при фаза 2 („вземи видимостта ми в новото приложение“) | да, като изричен въпрос в SCR-MIG-004 | без него Nearby в universal стартира без нито един бийгъл |
| Р18 | Микрочип като колони на dogs или отделна таблица с история; placeholder роднини само родители или и потомство | колони; само родители | таблица/потомство = миграция + UI без заявено търсене |
| Р19 | Единици/език/timezone на сървъра (`users.units/language/timezone`) | да | само локално = губят се при миграция; push без tz = 09:00 UTC за всички |
| Р20 | sha за всеки production деплой (R0, R1, R6, R7) и одобрение за всяко подаване/активиране в магазините | по правилата | — |

---

## 10. Какво НЕ правим в v1

- Не строим CMS, админ, OTA таблици, `min_version` матрица, `v2` директория — съдържанието е адитивно завинаги; несъвместима форма = app release.
- Не правим `POST /migration/import`; не копираме редове между приложенията; не пренасяме Keychain/токени.
- Не правим „режим само издърпва“ в Beagle Owner; не правим banner „Beagle Owner is growing“; не правим push категория `migration`.
- Не сервираме документи по статичния път на снимките; не показваме Manage линк към чужд магазин; не строим URL в клиента.
- Не въвеждаме поведение по `app_key` в service слоя (без 422 по app_key, без флагове в регистъра); не махаме сървърната квантизация.
- Не създаваме втори продукт/customer в хъба; не активираме нищо в магазините без думата на Ив; не подаваме две приложения едновременно.
- Не използваме native Postgres enum за нови колони; не пускаме crontab на хоста за напомняния; не ползваме `published_ids.txt`, `content_seed.lock` или ръчни дати в билд гейт.
- Не добавяме в Beagle Owner нито една нова продуктова повърхност (§6.3); не показваме „approved/vet-reviewed“ в UI или листинг.
- Не правим PDF export, `pedigree_placeholders` за потомство, история на микрочипове, handoff-code, Sign in with Apple/трети вход (иначе 4.8 се задейства), Melos, dog_ui като „по избор“.
- Не даваме оценки за време.

---

## 11. Кампании по порода — придобиване без отделни приложения (добавено 13.09.2026)

Източник: предложение от външен анализ (Ив, 13.09.2026), проверено срещу Apple/Google документацията и срещу кода. Проверено на 13.09.2026 в https://developer.apple.com/app-store/custom-product-pages/ (дословно): „You can publish up to 70 additional versions of your product page“; „You can also assign a deep link for each of your custom product pages. When you add a deep link, people who tap to open your app from your custom product page will be taken to a specific destination in your app. Deep links for custom product pages are supported in iOS 18 and iPadOS 18, or later.“; „assign keywords to your custom product page … appear in search results for those selected keywords“; аналитика на страница: impressions, downloads, redownloads, conversion, retention, proceeds.

### 11.1 Моделът
```
Facebook група / Reddit / уеб  →  go.heppsu.com/<slug>  →  Campaign Router (FastAPI, същият бекенд)
      iOS: инсталирано → Universal Link → /onboarding?breed_hint=…      неинсталирано → CPP URL на породата (deep link при отваряне от страницата, iOS 18+)
      Android: инсталирано → App Link → същото                          неинсталирано → Play URL (+ CSL по URL) с &referrer=campaign=<slug>
      Първи старт: Android чете Install Referrer; iOS получава deep link-а от CPP (ако е отворено от бутона Open) → AcquisitionContext{breed_hint, country_hint, language_hint, source, campaign}
      Онбординг: породата е ПРЕДИЗБРАНА и видима („French Bulldog ✓ · Change“), не скрита; breed_hint ≠ dogs.breed_key, докато потребителят не потвърди.
```

### 11.2 Какво съществува и какво е ново
| | | къде |
|---|---|---|
| ✅ има | UA-базиран redirect към двата магазина | `MyBeagleApi/app/modules/applink/router.py:31` `/get-app` — разширява се до `/go/{slug}` |
| ➕ ново | регистър на кампаниите като данни | `MyBeagleApi/content/campaigns.yaml` {slug, breed_hint, country_hint, language_hint, source, cpp_url, csl_url, active} — git-като-CMS като останалото съдържание; lint: breed_hint ∈ breeds/index |
| ➕ ново | `acquisition_contexts` | user_id (nullable до регистрация), anon_id, campaign, source, breed_hint, country_hint, store, clicked_at, installed_at, onboarded_at, trial_at, paid_at — без PII преди акаунт |
| ➕ ново | AASA + assetlinks.json | `/.well-known/apple-app-site-association` и `/.well-known/assetlinks.json` на `<new>.heppsu.com` и `go.heppsu.com` — само за universal (Beagle Owner не получава кампании, §6.3) |
| ➕ ново | клиент | `app_links` (Universal/App Links) + `android_play_install_referrer` в `dog_core`; `OnboardingContext.breedHint`; SCR-ONB-005 в режим „предизбрана + Change“ |
| ➕ ново | CPP × кампанийни породи | ASC API ресурси `appCustomProductPages` / `…Versions` / `…Localizations` — скриптируемо в `store_push.sh`; лимит 70 → само породите с кампания, останалите на основната страница |
| ➕ ново | отчет по кампания | Control Center: clicks (router) · installs (Android referrer; iOS от CPP аналитиката през ASC API) · onboarded · trial · paid (бекенд) |

### 11.3 Уговорки (проверени, не предположения)
- iOS deferred deep link без CPP не съществува first-party: споделен `go.heppsu.com/frenchie` в чат на iOS без инсталирано приложение → App Store → първият старт НЕ знае породата, освен ако човекът натисне Open от CPP страницата. Приема се; без clipboard трикове и без AppsFlyer/Adjust/Branch (трета страна = App Privacy label + ATT въпроси).
- Няма Meta/Facebook SDK: атрибуцията е first-party (нашият линк → магазин); нищо не се връща към Facebook. Иначе ATT prompt е задължителен.
- `go.heppsu.com/beagle` сочи към **universal** (Р12), не към Beagle Owner — Beagle Owner не получава нови кампании.
- Play CSL: таргетирането по уникален URL и по ключови думи е документирано (mb2_facts §2); дали CSL сменя името/иконата остава D3 от част 2.
- Универсалният линк на инсталирано приложение с друга порода в профила НЕ сменя породата на съществуващо куче — само предлага при добавяне на ново.

### 11.4 Гейтове
🧪 `test_go_router.py`: непозната кампания → 404; iOS UA → CPP URL (или App Store URL без CPP); Android UA → Play URL с URL-encoded `referrer`; `active:false` → основната страница. 🧪 `campaign_onboarding_test.dart`: breed_hint → породата е предизбрана и видима с Change; смяна → breed_hint не се записва никъде като истина. 🧪 `test_acquisition_no_pii.py`: ред без user_id не съдържа нищо освен slug/анонимен id/време. 🧪 `content` lint: `campaigns.yaml.breed_hint` реферира съществуващ breed_key.

### 11.5 Решения за Ив
| # | решение | препоръка |
|---|---|---|
| Р21 | Домейн за кампаниите: `go.heppsu.com` (общ за бъдещи продукти) или `<new>.heppsu.com/go/…` | `go.heppsu.com` — един AASA/assetlinks, един router |
| Р22 | Кои породи получават CPP в първата вълна (лимит 70) | породите с реални групи, в които ще се публикува; останалите — основна страница |
| Р23 | Отчетът по кампания в Control Center: колонките от 11.2 | да, като таблица иконка · какво · кой |
