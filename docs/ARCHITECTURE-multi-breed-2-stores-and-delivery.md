# Архитектура за 7 породи, част 2: магазини, дистрибуция, диск

файл `docs/ARCHITECTURE-multi-breed-2-stores-and-delivery.md` · 13.09.2026 · продължение на част 1 (`docs/ARCHITECTURE-multi-breed.md`); затваря §10.9, §11.1, §11.7 и добавя диска и матрицата.

Легенда: **РЕШЕНО** = решено от Ив (общ бекенд; матрицата идва от него) или следва механично от дословния текст на политиките. **ИВ РЕШАВА** = отворено, с препоръка и цена на алтернативата (§10). Всяка мярка е файл, скрипт, тест или гейт с име — не намерение.

## 0. Решението в едно изречение + какво остава от част 1

**Едно приложение — днешните `com.heppsu.myBeagle` (Apple bundle id и Play package, неизменими след публикуване) — носи всичките 7 породи като пакети с данни в билда; породата виси на кучето; ASO по порода се прави със страници вътре в приложението (Apple Custom Product Pages, Play Custom Store Listings); седем bundle id-та не се създават, защото са дословният пример от Apple 4.3(a) и от Play Repetitive Content, а наказанието е на ниво developer акаунт, в който виси и My Life Within.**

Какво остава от част 1 (иконка · какво · кой):

| | секция от част 1 | статус при T1 | кой |
|---|---|---|---|
| ✅ | §1 „един процес, една схема“; П1–П4 | остават; П3 „породата виси на КУЧЕТО, марката на АРТЕФАКТА“ е причината T1 да е безболезнена | сесията |
| ✅ | §2 `breed_key` контролирана стойност | остава; `app/core/apps.py` = един запис, `breed_keys` със 7 елемента | сесията |
| ⏸ | §2 три нови таблици; §3 nginx host per app, `PUBLIC_BASE_URL_<KEY>`, `SUBHUB_API_KEY_<KEY>`, `COCKPIT_APP_TOKEN_<KEY>`; §11.6 домейни | не се строят; остават като документиран, неползван клон | — |
| ⚠️ | §4 обхват на откриването по порода | принципът остава; в едно приложение обхватът идва от КУЧЕТО, не от сесията → нов код, решение D1 | Ив |
| ✅ | §5 един абонамент, един Play пакет / bundle / ASSN URL, RTDN | тривиално вярно с днешните стойности, нула нови продукти | сесията |
| ✅ | §6 плейсхолдъри (3) в 54 общи файла, push заглавие | една стойност: умбрела-името; правните текстове с новото име × 18 езика | сесията + Ив (§11.8) |
| ✅ | §7 pack.yaml, `gen_breed_assets.dart`, OTA отхвърлена, кодовете `thirteenInch`/`fifteenInch` не се преименуват | изцяло; цената на OTA-отказа при T1 се записва изрично (§9) | сесията |
| 🔴 | §9 R0 днешни дефекти | beagle факти на 9 от 18 езика = първата съдържателна задача; `pack_lint` е червен за beagle от ден 1 | Ив (D5) |
| 🔁 | §9 R-1 (Apple 4.3 предусловие), R9 (приложение №2 като приемен тест) | R-1 е изпълнен от топологията, не от ревю; R9 → „порода №2 като пакет“ | сесията |
| ✅ | §10.12 праговете на смъртта | остават + клиентски еквивалент: grep гейт за `breedKey ==` в `lib/` | сесията |
| ✔ | §10.9, §11.1, §11.6, §11.7 | затворени в този документ | — |
| 🔓 | §11.2/3, §11.4/5, §11.8 | остават за Ив (§10) | Ив |

## 1. Политиките на магазините — дословно и какво значат за нас

### 1.1 Apple App Store Review Guidelines, 4.3 Spam
URL: https://developer.apple.com/app-store/review/guidelines/ (изтеглено 13.09.2026)

(a) „Don't create multiple Bundle IDs of the same app (for example, submitting a separate map app for every city in the world instead of a single worldwide map that allows users to search any city). This practice results in unnecessary apps, which makes it hard for users to find the apps they want. If your app has different versions for specific locations, sports teams, universities, etc., consider submitting a single app and providing the variations using in-app purchase.“

(b) „Don't submit apps that are indistinguishable from what's already widely available. Opportunistically creating variants of existing app categories or popular apps degrades App Store discovery, reduces overall app quality, and harms both users and developers. […] Repeated submissions of this kind may lead to removal from the Apple Developer Program.“

### 1.2 Google Play — Spam policy → Repetitive Content
URL: https://support.google.com/googleplay/android-developer/answer/9899034 (изтеглено 13.09.2026)

„We don't allow apps that merely provide the same experience as other apps already on Google Play.“ Примери за нарушение: „Copying content from other apps without adding any original content or value.“ / „Creating multiple apps with highly similar functionality, content, and user experience.“ Препоръка: developers „should consider creating a single app that aggregates all the content“.

### 1.3 Google Play — Enforcement Process
URL: https://support.google.com/googleplay/android-developer/answer/9899234

„Repeated or serious violations (such as malware, fraud, and apps that may cause user or device harm) of these policies or the Developer Distribution Agreement (DDA) will result in termination of individual or related Google Play Developer accounts.“
„When your developer account is terminated, all apps in your catalog will be removed from Google Play and you will no longer be able to publish new apps. This also means that any related Google Play developer accounts will also be permanently suspended.“

### 1.4 Какво значи за нас

| | политика | какво наказва | има ли обект при T1 (едно приложение) | при T3 (седем bundle id-та) |
|---|---|---|---|---|
| ✅ | Apple 4.3(a) | „multiple Bundle IDs of the same app“; породата е класът „locations, sports teams, universities“ | няма — T1 е буквално „consider submitting a single app and providing the variations“ | дословно съвпадение; отказ реалистичен още при №2 |
| ⚠️ | Apple 4.3(b) | „indistinguishable from what's already widely available“ — сравнение с ПАЗАРА, не с нашите породи | непроменено спрямо днес; **расте, ако новото име е родово** („Dog …“) — сравнението става с десетки общи dog-care приложения | умножено ×7 + „Repeated submissions“ |
| ✅ | Play Repetitive Content | „Creating multiple apps with highly similar functionality, content, and user experience“ | няма — CPP/CSL са страници на едно приложение, не приложения; T1 е препоръката „a single app that aggregates all the content“ | дефиницията; вторичните източници сочат второто-третото приложение |
| 🔴 | Play Enforcement | „Repeated or serious violations … termination of individual or related … accounts … all apps in your catalog will be removed“ | ъпдейт на едно приложение не е нарушение | последицата не е „Pug Owner отказан“, а свален каталог |

Последицата на ниво акаунт: Beagle Owner и My Life Within са в СЪЩИТЕ акаунти (Apple team Heppsu, Play developer account Heppsu). Спам находка не е отказ на едно приложение — е риск за всички продукти и за правото да се публикува изобщо. Това е рамката, в която се чете всяко решение по-долу.

Честна формулировка на риска при T1 (поправена след ревю): **нулев по 4.3(a) и по Repetitive Content; по 4.3(b) непроменен спрямо днес и зависим от името.** „Нулев риск“ без уточнение е надценка.

Вторични източници (не официални): „Weather Forecast for New York / Los Angeles / Miami“ е класическият Play пример за Repetitive Content — същият код, различно име на града; отказът обикновено идва при второто-третото приложение от същия акаунт; помага реална функционална разлика и различно съдържание, не преименуване.

## 2. Топология

### 2.1 Препоръка: T1 — един bundle id, седем породни пакета (ИВ РЕШАВА, D0)

- Приложението Е днешното: `com.heppsu.myBeagle` в App Store и в Play, същият keystore, същият Firebase app, същите продукти `plus_monthly` / `com.heppsu.myBeagle.plus.monthly`, същият ASSN URL, същият RTDN топик. Нищо от идентичността не се сменя; рейтинг, ревюта и абонати се запазват без миграция.
- Породата виси на кучето (`dogs.breed_key`, контролирана стойност). При добавяне на куче потребителят избира порода; съществуващите кучета мълчаливо стават `beagle` (`is_default_for_legacy`), с тест `test/legacy_dog_breed_migration_test.dart`.
- Beagle Owner не се спира, не се клонира, не се преиздава. Преименуването (D2) е единствената магазинна промяна и е обратимо.
- Бекенд: `app/core/apps.py` = един запис с `breed_keys` = 7 стойности; трите таблици от §2 и фасадите от §3 не се строят.
- Клиент: без flavors. Пакетите са в билда (§7 на част 1): `assets/breed/<key>/{reference.json, facts.<lang>.json, texts.<lang>.json, measurement.png}`, регистрирани с глоб `assets/breed/` в pubspec.

Защо T1 е и обратимата посока: преходът T1 → T3 по-късно е добавяне на записи в `apps.py` (данни) + flavors на клиента (работа, §5); преходът T3 → T1 при живи породни приложения е sunset на bundle id-та с потребители и абонаменти, които не се прехвърлят. Единственото евтино „Plan B“ е да не се стига до него.

### 2.2 T2 — два bundle id-та (Beagle Owner + „X Owner“ с останалите 6)

Същият вид риск като T3 по 4.3(a) — „multiple Bundle IDs of the same app“ важи при две, както при седем; само подаванията са по-малко. Удвоява завинаги листинги, IAP продукти, App content въпросници, ревю опашки и артефакти. Не се препоръчва; отговорът на „Beagle Owner не бива да се пипа“ е „изчакай одобрението на 1.2.7 и го пипни“, не „направи второ“.

### 2.3 T3 — седем bundle id-та (заявеното)

Дословно 4.3(a) („submitting a separate map app for every city“) и Play примерът с градовете. Три независими ревюърски четения (§ПРИСЪДИ) стигат до едно: отказ при №2 или №3 с шаблонния текст, ретроактивна класификация на клъстера от Play при №4–№5, а „Repeated submissions“ се брои на ниво екип. Различно съдържание (факти, криви, икона) не помага — примерът за нарушение е точно приложение с различно съдържание по град/отбор; помага само реално различен feature set, който тук не съществува и не е поискан. Ако Ив избере T3, това е изрично поемане на риск върху акаунтите, в които виси и My Life Within, и се записва с тази формулировка.

### 2.4 Откриване в едно приложение — новото решение, което T1 отваря (ИВ РЕШАВА, D1)

Част 1 §4 стеснява откриването по идентичност на приложението в сесията. При един запис с 7 породи това означава: собственик на мопс вижда бийгъли в „наблизо“. Две възможности:
- (а) откриване между всички породи — част 1 без промяна, наистина нула нов сървърен код; продуктово: „кучешка екосистема“, а не „breed-specific“;
- (б) откриване по породата на активното куче — нов код в заявките за наблизо/разходки/запознанства + UI „за кое куче гледам“ + правило за домакинство с две породи; продуктово: празни екрани за рядка порода в началото.
За избрания вариант: `MyBeagleApi/tests/test_discovery_scope_single_app.py` през всеки канал (П4), включително домакинство beagle+pug. Твърдението „нула редове нов сървърен код“ е вярно само при (а).

## 3. Различност пред ревюъра

При T1 въпросът „с какво всяко приложение е различно“ няма обект: ревюърът вижда едно приложение, чиято новост е „още породи“ — точно това, което 4.3(a) препоръчва. Различимостта се премества на три места.

### 3.1 Срещу пазара (4.3(b)) — артефакти, които днес липсват
- `scripts/gen_review_notes.dart` → `store/review_notes/<lang>.md` от pack.yaml на всички пакети в билда: колко и кои породи, разновидности, криви на теглото, източници с URL, къде в приложението се избира породата. Lint в същия скрипт пада, ако текстът съдържа „Jaccard“, „RGB“, „distinctness“ или метрика — ревюърът чете какво прави приложението, не числа. `build_release.sh` спира, ако файлът е по-стар от най-новия pack.yaml.
- Описанието във всеки от 18-те езика изброява `display_name[lang]` на ВСЕКИ пакет в билда (гейт №5 по-долу).
- Първите скрийншоти показват избора на порода — „вариациите“ са видими в самото приложение.
- Името запазва породната специализация (сигнал „по порода/breeds“ в име или подзаглавие), не родово „Dog“ (D2).

### 3.2 Породен здравен модул — НЕ в първата версия
`health_flags` с поведение (породни предупреждения, напомняния по график) е реална функционална разлика между пакетите, но: не е нужна за одобрение при T1; напомняне по график от сървъра нарушава „0 реда нов сървърен код“ и §10.12 (първо `if breed_key ==` в service слоя); при един поддържащ е първото, което остава наполовина. Първата версия носи референтни данни и факти; в матрицата остава само `breed_notes[lang]` (низ, без поведение). Модулът е отделен MINOR, ако Ив го поиска (D10), всеки флаг = код + тест + 18 езика.

### 3.3 `scripts/distinctness_check.sh` — какво мери и какъв праг
Гейт за КАЧЕСТВО на съдържанието при T1, не броня пред ревюъра. Bash обвивка около `scripts/distinctness_check.dart` (unicode-safe; без Jaccard — при 18 езика, шаблонен преводач и писмености без интервали Jaccard е шум, който подтиква към редактиране на факти заради число). Пуска се в CI и в `build_release.sh` преди копиране в `releases/`. Изход: таблица (иконка · какво · кой), exit 1 при нарушение.

| № | проверка | праг |
|---|---|---|
| 1 | байтова идентичност на `texts/<lang>.yaml` между две породи | 0 идентични файла |
| 2 | идентичност на сериализираните `weight_curve` и `varieties` между две породи | 0 идентични двойки |
| 3 | SHA-256 на `assets/breed/<key>/measurement.png` | N различни хеша за N пакета |
| 4 | всеки факт има `source_id`, който съществува в `sources[]`; `sources[]` на пакет ≠ beagle има ≥ 2 URL извън beagle | exit 1 при липса |
| 5 | `store/description.<lang>.md` за всеки от 18-те езика изброява `display_name[lang]` на всеки пакет в билда | липсващ език или порода = exit 1 |
| 6 | `store/cpp/<key>/<lang>/` и `store/csl/<key>/<lang>/`: налични текстове и manifest за 5 резолюции × ≥ 4 скрийншота; текстът съдържа `display_name[lang]` на ТАЗИ порода и не съдържа име на друга | exit 1 |

Тест `test/scripts/distinctness_check_test.sh`: два умишлено еднакви пакета → exit 1; фикстура `content/breeds/_fixture/` държи гейта червен поне веднъж преди порода №2 (гейт, който никога не е бил червен, не е доказано, че работи).

Механично НЕпроверимо: преценката „същото преживяване“. Затова скриптът е гейт за качество при T1, а не аргумент при T3.

## 4. Матрицата — финалната схема

Един ред на порода (7 реда; `beagle` се извлича от днешния код като референтен ред). Общи числа в `content/breeds/_defaults.yaml` (weight_thresholds по подразбиране 0.10/0.20/0.30, възрастови прагове); пакетите override-ват само различното; `validate_pack.dart` резолвира наследяването (`test/content/defaults_inherit_test.dart`).

| поле | тип | задълж. | източник | къде отива | низ / поведение |
|---|---|---|---|---|---|
| `breed_key` | slug `[a-z_]{3,20}`, контролирана стойност | да | сесията (от името) | `content/breeds/<key>/`, `apps.py breed_keys`, `dogs.breed_key`, `store/cpp\|csl/<key>/` | ПОВЕДЕНИЕ (избор на пакет; обхват по D1) |
| `display_name[lang]` | низ × 18 | да | Ив / преводач | `texts/<lang>.yaml` → per-dog ARB ключове | НИЗ |
| `strings[lang]` (per-dog ключове, пълни низове) | низ × 18 за всеки per-dog ключ | да | Ив / преводач; за beagle копирани дословно от днешните ARB | `texts/<lang>.yaml` → `weightOutOfRangeWarning`, `weightRangeDialogBody`, `heightMeasurementWhyBody`, `passportSharePreamble`, `defaultBreed…`, `beagleFactTitle` (по активното куче) | НИЗ (golden тест срещу днешните) |
| `name_in_search[lang]` | низ × 18 | да | Ив | Apple keywords (глобално поле, 100 знака общо), CPP keyword set, CSL keyword set | НИЗ; бюджет по локал в `pack_lint` |
| `units` | `metric` | да | схема | pack.yaml | – |
| `varieties[]` `{code, applies_to_sex, weight_kg{min,max}, shoulder_height_cm{min,max}, source_ids}` | масив ≥ 1 | да | Ив (AKC/FCI/клуб) | pack.yaml → reference.json | ПОВЕДЕНИЕ: екран за вариант само при > 1; `applies_to_sex` → избор на пол; кодовете `thirteenInch`/`fifteenInch` не се преименуват |
| `combined_weight_kg{min,max}` | обект | не | Ив | pack.yaml | ПОВЕДЕНИЕ (общ диапазон без варианти) |
| `weight_curve[]` `{max_age_months, reference_kg}` | масив ≥ 12 точки (beagle: 19), монотонна | да | Ив по източник | pack.yaml → reference.json | ПОВЕДЕНИЕ (крива на растежа) |
| `weight_thresholds{ideal,normal,attention}` | три дроби | не (от `_defaults.yaml`) | Ив | pack.yaml | ПОВЕДЕНИЕ |
| `puppy_tips[lang]` | низ × 18 | не | Ив / преводач | `texts/<lang>.yaml` | НИЗ |
| `breed_notes[lang]` | низ × 18 | не | Ив | `texts/<lang>.yaml` → екран за породата | НИЗ (без поведение; заместител на `health_flags`) |
| `facts[lang][]` `{id, text, source_id}` | ≥ N × 18 (N = 40 или 100, D5) | да | Ив / преводач | `facts/<lang>.yaml` | НИЗ; `pack_lint`: N еднакво за всички езици, без празни |
| `sources[]` `{id, url, publisher, retrieved_at}` | масив ≥ 2 | да | Ив | pack.yaml + екран „Източници“ + review notes | НИЗ |
| `source_sha`, `reviewed_by`, `translation_status` (на всеки `<lang>.yaml`) | низ | да | сесията / Ив | `validate_pack.dart` пада при остарял sha спрямо `en.yaml` или празен `reviewed_by` | – (свежест на превода) |
| `measurement_image` | PNG | да | Ив / художник | `assets/breed/<key>/measurement.png` | ВИЗУАЛ (уникален хеш) |
| `accent_color` | hex | не | Ив (D7) | pack.yaml → породен акцент върху днешната палитра | ВИЗУАЛ |
| `store_promo[lang]` | низ × 18, ≤ 170 знака (Apple) | да | Ив | `store/cpp/<key>/<lang>/`, `store/csl/<key>/<lang>/` | НИЗ |
| `store_description[lang]` | низ × 18 | да | Ив | `store/csl/<key>/<lang>/` (CPP няма собствено описание) | НИЗ |
| `store_screens` | manifest с хешове; 5 резолюции × ≥ 4 екрана × 18 езика | да | автоматично (`store_screenshots.sh`) | `releases/store/<ver>/<key>/`, в git само manifest | ВИЗУАЛ |
| `is_default_for_legacy` | bool, точно един `true` (beagle) | да | сесията | клиент | ПОВЕДЕНИЕ (миграция на съществуващи кучета) |

Извън матрицата (глобално за приложението): bundle id, package name, product id и цена, ASSN/RTDN, Firebase, DNS, правни документи (един текст с умбрела-името, §11.8), App content въпросник, app-level ARB ключове (`appName`, `tagline`, `shareApp*`, `subscriptionRequiredBody`, `termsAcceptanceBody`, `communityQrPrivacyNote`, `meetupMessageHint`, `noMeetupsHint`, `nearbyDogs`/`noNearbyDogs`) — пренаписани породно-неутрално с умбрела-името, без `{breed}`.

Гейтове по схемата:
- `scripts/pack_lint.dart`: задължителни полета, 18 езика без липси, N факта еднакво, референции на source id, `min < max`, монотонна крива; бюджет на търсещата повърхност по локал — name (≤ 30) + subtitle (≤ 30) + keywords (≤ 100, без интервали след запетаи) и че `name_in_search[lang]` на всички пакети се побират; изход таблица по език, exit 1 при преливане. `content/breeds/<key>/facts/MISSING.yaml` — lint пада, ако език е в MISSING и файлът съществува, или ако MISSING е непразен за порода ≠ beagle.
- `test/arb_placeholder_test.dart`: нито един app-level ключ не съдържа `{breed}`; всеки per-dog ключ го съдържа на всичките 18 езика.
- `test/beagle_strings_golden_test.dart`: 20-те ключа × 18 езика, рендирани с текстовете на beagle, са равни на замразения snapshot `test/golden/beagle_strings.json` от днешните ARB.
- `test/pack_behavior_test.dart`, параметризиран по всички папки в `content/breeds/`: `varieties > 1` → екран за вариант; `applies_to_sex` → избор на пол; куче с порода без пакет → низ `breedDataUnavailable`, без crash.

## 5. Един проект, 7 flavors — какво от това се строи при T1

**При T1 flavors не се строят.** Един `applicationId` (`build.gradle.kts:40`), една схема Runner, един pbxproj, `PRODUCT_BUNDLE_IDENTIFIER` на 6-те места не се пипа. Промените на клиента:
- Преименуване: iOS `CFBundleDisplayName` в Info.plist, Android `android:label` през `strings.xml` × 18 езика; `appName` × 18 в ARB. Иконата остава една (D2 решава дали умбрела-името иска нова).
- Пакети: `content/breeds/<key>/` → `scripts/gen_breed_assets.dart` → `assets/breed/<key>/*.json` (в git, детерминизъм доказан с двойно пускане и еднакъв sha), глоб `assets/breed/` в pubspec.
- Модели: `beagle_reference.dart` → `breed_reference.dart` (зареждане от JSON, `BreedSizeVariant`), `beagle_facts.dart` → loader от assets; `lib/breed/pack_resolver.dart` — `PackResolver.forDog(dog)`; всеки pack-задвижен widget приема null.
- `--dart-define`: остават `API_BASE_URL` и ново `BUILD_ENV=test|prod`; няма `BREED_KEY`. Grep гейт в CI: `grep -rnE "breedKey\s*==\s*'" lib/` = 0 реда (клиентският §10.12); `scripts/distinctness_allowlist.txt` с изключенията (`com.heppsu.my_beagle`, `BeagleHeightVariety`, `beagleFactTitle`, …), за да не са устна уговорка.
- Общо за всички породи: целият UI, навигация, абонамент, общност, паспорт, карта — това е предимството на T1, не недостатък.

**Контингенция (само при T2/T3; документирана, за да е ясно какво НЕ се строи):** Android `flavorDimensions += "breed"`, `productFlavors` с `applicationId com.heppsu.my<Breed>`, `resValue app_name`, `android/app/src/<flavor>/{res/mipmap-*, google-services.json, res/values/strings.xml}`; iOS `ios/Flutter/<flavor>.xcconfig` (`PRODUCT_BUNDLE_IDENTIFIER`, `APP_DISPLAY_NAME`, `ASSETCATALOG_COMPILER_APPICON_NAME=AppIcon-<flavor>`), 3 × N конфигурации `Debug/Profile/Release-<flavor>`, N схеми, Podfile мапинг за всяка конфигурация, N `ExportOptions.plist`, N `LaunchScreen` storyboard-а, N App ID-та с Push capability и профили, N Firebase apps; `flutter build --flavor <key> --dart-define=BREED_KEY=<key>`; pubspec `assets: - path: … flavors: [<key>]` (Flutter ≥ 3.19). Плюс правило за куче от чужда порода в еднопородов бинарник (П1) и 7× артефакти на всеки цикъл. Това е „скъпата половина“ от §10.9 — при T1 не се плаща.

## 6. Дискът

### 6.1 Числа днес (проверено 12.09.2026)
Mac (билд машината): 228 GB, 180 GB заети, **9,6 GB свободни (95 %)**. ~/Library/Developer/Xcode 14 GB (DerivedData 2 GB), ~/Library/Caches 11 GB, Android SDK 9,1 GB, .gradle 6 GB, CoreSimulator 4,9 GB, MyBeagle/build 2,1 GB, releases/ 1,9 GB (7 файла), .pub-cache 1,1 GB. Xcode грешка 74 вече се е случвала. Арес: 193 GB, 7,4 GB заети (4 %) — общият бекенд не умножава нищо на сървъра; дисковият проблем е билд машината. При T1 умножителят ×7 изчезва (1× артефакти ≈ 111 MB на версия), но днешното състояние спира следващия билд преди изобщо да се стигне до породи — `disk_guard.sh` е първата промяна, не последната.

### 6.2 Какво се чисти веднага (ИВ РЕШАВА, D8 — трие от домашната директория, една стъпка наведнъж)
`scripts/disk_reclaim.sh --dry-run` печата списъка и преди/след; трие само от списъка:

| | какво | GB | бележка |
|---|---|---|---|
| ✅ | ~/Library/Caches (Xcode/CocoaPods/Homebrew кешове) | ~11 | регенерируем; част се връща при първия билд |
| ✅ | .gradle/caches (не wrapper) | ~6 | регенерируем |
| ✅ | DerivedData | ~2 | регенерируем |
| ✅ | MyBeagle/build | 2,1 | `flutter clean` |
| ✅ | releases/ извън последните 2 версии на платформа | ~1,3 | възпроизводими от git таг + скрипт; напускат Mac-а (6.3) |
| ⚠️ | CoreSimulator: `xcrun simctl delete unavailable`; runtime без устройство | до ~3 | runtime-ите от `scripts/devices.txt` (5-те резолюции) НЕ се трият |

Реалистично ≈ 20–25 GB печалба → ~30–35 GB свободни. Това НЕ достига прага за Xcode ъпгрейд (xip + разопакован + стар Xcode ≈ 40+ GB транзитно). Структурното решение е D8: външен SSD за `DerivedData`, `.gradle`, `releases/` (`BUILD_VOLUME`), по-голям диск или Android release билдове в CI.

### 6.3 Инварианти като гейтове (`scripts/disk_guard.sh`, извикван от `build_release.sh`; exit ≠ 0, никога само предупреждение)
- **G-DISK-1** преди билд: свободно ≥ 40 GB (`DISK_MIN_FREE_GB`, число от Ив — D8); при неуспех таблица кой директорий колко държи + командата за `--reclaim`. Обосновка: артефактите са ~111 MB, но архивът минава през DerivedData, `build/` (2,1 GB) и Archives; грешка 74 при 9,6 GB е факт; нов Xcode иска ≥ 40 GB транзитно.
- **G-DISK-2** преди iOS архив: `~/Library/Developer/Xcode/DerivedData/Runner-*` > 5 GB → трие се; `~/Library/Developer/Xcode/Archives` извън последните 3 версии → трие се; симулатори: само доклад.
- **G-DISK-3** `releases/`: след успешно копиране артефактът се rsync-ва към архив (Арес има 185 GB свободни, или външен SSD — D8), sha256 се сверява отдалечено, локалното копие се трие; `releases/` е празна след билд; ротация никога не трие артефакт, чийто sha носи `tested/<sha>` или production таг (`git tag --points-at`). Име на файла: `BeagleOwner-<ver>+<build>.aab|.ipa` (приложение + версия); тестови артефакти: `-test` суфикс.
- **G-DISK-4** теч: мери само `build/`, `releases/`, `Archives` — не целия диск (растежът на `.gradle`/`.pub-cache` не е теч): след билд сумата им ≤ преди + 300 MB; иначе exit 1 със списък на новите директории над 100 MB. `build/ios/archive/*.xcarchive` се трие след експорт на .ipa; `build/` се чисти след успешно копиране.
- **G-DISK-5** един Xcode на машината: `ls -d /Applications/Xcode*.app | wc -l` == 1; процедурата за ъпгрейд в `docs/UPGRADE.md` (≥ 45 GB свободни → нов Xcode → стар се трие → Flutter → CocoaPods) с командите, които освобождават мястото.
- `scripts/toolchain_check.sh` + `.tool-versions` (Flutter, Xcode, CocoaPods): `build_release.sh` спира при несъответствие; ъпгрейд на Flutter major е отделен PR със зелен CI, не страничен ефект на рилийз.
- Тест: `test/scripts/disk_guard_test.sh` с `DF_OVERRIDE_GB=5` → exit 1, `DF_OVERRIDE_GB=45` → exit 0; фалшива дървесна структура за `--reclaim`; фалшив `releases/` с 5 версии → остават 2 и таг-защитените.

`build_release.sh` (днес 58 реда, „не пуска тестове; не чисти“) става: `build_release.sh --env test|prod --platform android|ios|both` → чисто работно дърво + таг `tested/<sha>` (за prod) → `toolchain_check` → `disk_guard` → `gen_breed_assets` → `flutter analyze` + `flutter test` → `pack_lint` + `distinctness_check` → `gen_review_notes` свежест → билд → `scripts/env_gate.sh` (извлича `API_BASE_URL` от готовия артефакт с `unzip -p … | strings | grep -o 'https://[a-z-]*\.heppsu\.com'` и отказва release име при `-test` host; `test/scripts/env_gate_test.sh`) → копие + rsync + чистене → отчет със sha256. Никога не качва в магазина сам.

### 6.4 CI: hosted Linux, не self-hosted на Mac-а (РЕШЕНО; доставчикът и разходът — D9)
- `.github/workflows/ci.yml` (MyBeagle) на всеки PR: `dart format --set-exit-if-changed`, `flutter analyze` (статичен), `flutter test` (динамичен), `pack_lint`, `distinctness_check`, ARB пълнота (18 езика, 0 липсващи ключа), grep гейтът, свежест на генерираните файлове (`git diff --exit-code`), дебъг Android билд като smoke. `content-lint` job само при промяна под `content/`. MyBeagleApi: `dod.yml` от част 1 §3 като workflow. Това затваря DoD „CI със статичен и динамичен анализ“ и за двете репота (днес няма CI в нито едно).
- Защо не self-hosted на Mac-а: дискът е на 95 %, runner кешовете добавят гигабайти, машината е и билд машина на My Life Within, и правилото „self-hosted CI не е празна машина“ (production порт зает, тест не може да падне) вече ни е хващало с реален лог.
- Защо не hosted macOS за подписан билд: сертификатите, keystore.properties и App Store ключовете не напускат Mac-а; рилийз билдът остава ръчен през `build_release.sh` с гейтовете. Ив решава (D9) дали плаща hosted macOS минути за неподписан `flutter build ios --no-codesign` при промяна на `pubspec.lock`/`Podfile.lock` и седмично (`flutter-beta` job, allowed-to-fail, за ранно предупреждение преди рилийз деня); цена в EUR, когато я поиска.

## 7. Магазинни операции, генерирани от матрицата

Умножителите при T1: 1 листинг × 2 магазина × 18 езика, 1 IAP продукт, 1 App content въпросник, 1 privacy label, 1 ASSN/RTDN, 1 Firebase app, 1 DNS — всички днешни. Остава в пълен размер половината от §10.9, която е съдържание: N × 18 CPP/CSL страници и 5 резолюции скрийншоти. Днешното състояние (iOS листинг само bg/en/pt, Android само en при правило „всички езици, винаги“) е доказателството какво пропуска един човек без скрипт — затова качването е скрипт, а одобрението е таг.

| | операция | скрипт / ръчно | защо |
|---|---|---|---|
| ✅ | основен листинг × 18 езика (име, подзаглавие, описание, keywords, What's New) | `scripts/store_push.sh` през App Store Connect API + Google Play Developer Publishing API; отказва без таг `approved/<sha>` (думата на Ив = тагът) | „промени в магазините само с одобрение“ без клик; затваря 4/36 → 36/36 |
| ✅ | `scripts/store_listing_diff.sh` | тегли ЖИВИЯ листинг и пада при разлика с git | конфигурация ≠ процес: git не е конзолата |
| ✅ | скрийншоти | `scripts/store_screenshots.sh`: integration_test × 5 резолюции × 18 локала, assert за overflow/exception (това е и тестът „5 резолюции преди рилийз“); изход `releases/store/<ver>/` под ротацията, в git само manifest; пуска се при нов листинг и когато `git diff <last-tag>..HEAD -- lib/screens lib/widgets` не е празен | 2 × 18 × 5 × ≥ 4 = 720+ изображения на версия — ръчно неизпълнимо |
| ⚠️ | Apple Custom Product Pages × N породи | `store_push.sh`, ако ASC API има CPP endpoint-и — **проверка преди дизайн** (D3); до записа в `docs/STORE-ASO-FACTS.md` директориите `store/cpp/` са спецификация, не файлове | лимитите (70) и органичното показване са от вторични източници |
| ⚠️ | Play Custom Store Listings × N | ръчно в Play Console, освен ако има API (D3); проверка дали CSL сменя ИМЕТО и иконата | „ДА СЕ ПРОВЕРИ в Play Console“ — не се разчита |
| ✋ | преименуване (име × 18 × 2 магазина, подзаглавие, икона) | чернова от матрицата; активиране само с думата на Ив (D2); проверка за свободно име в ASC | магазинна промяна с одобрение |
| ✋ | правни документи с новото име × 18 | `gen_breed_assets.dart` попълва 3-те плейсхолдъра в 54-те файла; юрист/сесията потвърждава (§11.8) | сесията е сама — прегледът е мой, Ив потвърждава |
| ✋ | App content, privacy labels / Data safety при промяна на SDK | ръчно по референцията „Google Play Console въпросник“; `scripts/gen_store_checklist.sh` → `docs/store/rename-checklist.md` с чекбоксове; `store_push.sh` не подава при незатворен чекбокс | няма API за въпросника |
| ✅ | IAP, RTDN/ASSN, домейни, Firebase | нула промяна | T1 |
| ✅ | `store/review_history.yaml` `{version, store, date, outcome, guideline_codes[], note}` | Ив попълва четирите предишни ревюта на 1.2.x (една стъпка наведнъж); гейт в `build_release.sh`: при запис `rejected` с 4.3(b) или 2.x метаданни без последващ `approved` — не се билдва версия с промяна на името | историята на акаунта е данни, не спомен |
| ✅ | `scripts/store_lint.sh` | име/подзаглавие ≤ 30 знака и породен сигнал от `texts/` във всеки език; отказва да генерира `store/cpp\|csl/<key>/` за key ≠ beagle, докато името е „Beagle Owner“ в който и да е език или описанието не съдържа `display_name[lang]` на породата; `test/store_lint_test.sh` с родово име → exit 1 | без преименуване няма CPP/CSL за чужди породи |

Ив дава еднократно: ASC API ключ и Play service account (D9).

## 8. Ред на подаванията и план при отказ

Всяко подаване е ъпдейт на вече одобрено приложение — на ревю никога не отива „ново приложение“. Без срокове.

0. **Замразено до одобрен билд.** До одобрението на 1.2.7 от Apple: нищо в магазините, нищо в production, включително бекендът (средата, в която билдът под ревю говори). Всичко в feature branch. Паралелно, без магазинна промяна: D3 проверките (Play CSL име/икона; ASC CPP endpoint-и и лимити), D8 почистване, `disk_guard.sh`, `review_history.yaml`.
1. **Бекенд** (след одобрението): R0 → `dogs.breed_key` + `BREED_KEYS` в `apps.py` → обхват по D1. `MyBeagleApi/tests/test_client_127_compat.py`: записаните заявки на клиент 1.2.7 (без breed поле) минават непроменени, breed по подразбиране `beagle`. Тест на `tested/<sha>`, production с изричен sha от Ив. Първо бекендът, после билдът.
2. **Клиент 1.3.0 (MINOR)** — двигател за пакети с beagle като единствен пакет, `BreedSizeVariant`, per-dog/app-level ARB, golden тест, `PackResolver`, гейтове, CI, `store_push.sh` с основния листинг на 18 езика (store метаданни с одобрение, не обвързано с кода). Видима промяна: нула. Цел: пайплайнът за пакети минава истинско ревю и истински потребители без магазинен риск. ИВ РЕШАВА (D6) дали се пуска отделно или се слива с 1.4.0; препоръка: отделно — дефект на машинарията да се хване на версия, при която отказ по 4.3 е невъзможен.
3. **Клиент 1.4.0 (MINOR)** — избор на порода при добавяне на куче, миграция на съществуващите кучета (с тест), първата чужда порода с зелен `pack_lint` на 18 езика, преименуване (D2), описание с всички породи на 18 езика, `review_notes`. **Само това в подаването.** CPP/CSL съществуват като чернова, но се активират в ОТДЕЛНА стъпка след одобрението — така при отказ е ясно коя промяна е отказана. Защо преименуване + порода заедно: преименуване без нова порода е промяна без причина пред ревюъра; нова порода под „Beagle Owner“ е объркване пред потребителя.
4. **Следващи породи** — групират се по готовност (зелен `pack_lint` на всички 18 езика); рилийз, когато има ≥ 1 зелен пакет и рилийз е иначе дължим; не по принуда „една порода = един MINOR“. Всяка версия носи своите CPP/CSL чернови; активиране след одобрение.
5. **PATCH само при фиксиран дефект.** Цената на OTA-отказа (§7 на част 1) при T1: всяка сгрешена цифра в pack.yaml на една порода = PATCH през ревю на двата магазина за всички. Записва се тук, за да не се преоткрива при първата грешна цифра.

План при отказ (`docs/STORE-REJECTION-PLAYBOOK.md`, прилага се без ново решение):
- Отказ на 1.4.0 по 4.3(a)/Repetitive: няма обект — един отговор в Resolution Center / appeal с `review_notes` (без метрики): „single app aggregating breeds per 4.3(a)“.
- Отказ по 4.3(b): проблемът е различимост спрямо пазара, не породите — породите чакат; записва се в `review_history.yaml`; следващият билд отговаря на конкретната находка (name/subtitle/описание/review notes).
- Отказ по метаданни (2.x) заради името: старото име се връща в следващия билд; породите остават (те не са магазинна промяна). Нищо не се сваля, нищо не се губи.
- Ако 1.2.7 бъде отказано по 4.3(b): клон „първо различимост спрямо пазара“ — породите не са приоритет.
- Какво НЕ правим: не ресубмитваме същия бинарник с други думи; не пращаме `distinctness_report` на ревюъра; не активираме CPP/CSL преди одобрение; не създаваме втори bundle id „за да опитаме“ — това е T2 със същия риск като T3.
- При T3 (ако Ив го избере въпреки лещата): първата 4.3/Repetitive находка = незабавно оттегляне на ВСИЧКИ чакащи подавания и сливане към T1 — същата архитектура, но с находка в историята на акаунта, която „repeated“ клаузата брои.

## 9. Какво се променя в част 1 и какво остава

Променя се (като работа, не като документ; част 1 остава архив на разсъждението):
- §1 „девет фасади“ → една фасада. §3 идентичност от nginx host, env `*_<KEY>`, `dod.yml` брояч — не се строят; `dod.yml` брои 1. Регистърът `AppProfile` остава с един запис, `breed_keys` = 7 (§11.7 отговорено: група = всички). Трите таблици от §2 не се строят, освен ако D1(б) ги изисква.
- §4: обхватът в едно приложение е от кучето, не от сесията — D1; при (б) „нула редове нов сървърен код“ от §7.4 става „нов код в заявките за откриване“ и се казва честно.
- §6: една стойност на плейсхолдърите; правните документи получават новото име × 18 езика в 1.4.0.
- §7: ARB ключовете с порода се разделят на per-dog (с `{breed}` от `dog.breed_key`) и app-level (без `{breed}`); `texts/<lang>.yaml` носи пълните низове на порода и език, не 4 словоформи — склоняващите езици (български член, руски/полски падежи, немски род) не се възпроизвеждат от плейсхолдър.
- §9: R-1 изпълнен от топологията; R9 → порода №2 като пакет; нова R-0.5: `store_push.sh` като предусловие за 1.4.0.
- §10.9: закрито — flavors, xcconfig, икони × N, IAP × N, въпросници × N не се строят; листинги и скрийншоти се генерират и качват със скрипт.
- §11.1: отговорено (T1). §11.6: отпада. §11.7: `breed_keys` списък = всички.

Остава без промяна: П1–П4; `breed_key` контролирана стойност; §5 изцяло; §7 pack.yaml схема, `gen_breed_assets.dart`, OTA отхвърлена, `thirteenInch`/`fifteenInch`; §9 R0; §10.12 (плюс клиентският grep гейт: първата породно-специфична nullable колона в `dogs` или първото `if breed_key ==` в service слоя означава, че пакетът е сгрешен, не бекендът).

## 10. Решения за Ив

| № | решение | препоръка | цена на алтернативата |
|---|---|---|---|
| D0 | Топология: T1 (един bundle id) / T2 (два) / T3 (седем) | **T1** | T2/T3 = изрично поемане на риск върху акаунтите с My Life Within: „termination of individual or related Google Play Developer accounts“, „removal from the Apple Developer Program“; плюс 6 × (листинг × 2 × 18, IAP, App content, ревю опашка, Firebase, DNS) и 7× диск |
| D1 | Откриване в едно приложение: (а) между всички породи / (б) по породата на активното куче | (а) за 1.4.0, (б) като следващ MINOR, ако данните покажат нужда | (б) веднага = нов сървърен код в три заявки + UI за активно куче + правило за две породи в домакинство |
| D2 | Умбрела-име (× 18 езика, двата магазина), подзаглавие с породите, икона; ограничение: запазва породната специализация, не родово „Dog“ | име с породен сигнал; иконата остава | родово име = по-висока експозиция по 4.3(b); без преименуване = няма CPP/CSL за чужди породи (`store_lint.sh`) |
| D3 | Две проверки без магазинна промяна, една стъпка наведнъж: Play Console — CSL сменя ли име/икона, има ли API; ASC — CPP endpoint-и, реален лимит, keywords поле | да, преди какъвто и да е дизайн на `store/cpp\|csl/` | без тях ASO обещанието е условно; резултатът се записва с дата в `docs/STORE-ASO-FACTS.md` |
| D4 | Потвърждение: днешните продукти `plus_monthly` / `com.heppsu.myBeagle.plus.monthly` и цената остават единствени за всички породи (§11.2/3) | да | нов продукт = ново ревю на IAP + `subscriptionRequiredBody` × 18 |
| D5 | Факти: 40 или 100 на порода × 18 езика; кой пише/превежда; beagle 9 → 18 езика: машинен превод + преглед или човек (§11.4/5) | 40, проверими по източник; за beagle машинен превод + преглед с `reviewed_by` | 100 × 18 × 7 = 12 600 низа — доминиращият обем; без `reviewed_by` P-гейтът е доволен от машинен превод на стар източник |
| D6 | 1.3.0 отделно (без видима промяна) или слято с 1.4.0 | отделно | слято = дефект на машинарията се открива на подаването с преименуване, при петкратна история на ревюта |
| D7 | Породен акцентен цвят: да/не | не за 1.4.0 | да = още едно визуално поле × 7 за проверка на 5 резолюции |
| D8 | Диск: `disk_reclaim.sh` (списъкът в 6.2) — да/не; праг `DISK_MIN_FREE_GB` (препоръка 40); структурно: външен SSD за `BUILD_VOLUME` / по-голям диск / Android release в CI; архив на `releases/` на Арес или SSD | почистване да; външен SSD + архив на Арес | без структурно решение всеки рилийз започва с ръчно чистене, а Xcode ъпгрейд не минава G-DISK-1 |
| D9 | CI: GitHub Actions hosted ubuntu (или друг доставчик); hosted macOS минути за `--no-codesign` чек; ASC API ключ + Play service account за `store_push.sh` | ubuntu да; macOS чек да при промяна на lock файлове; ключовете да | без API ключове качването остава ръчно = днешните 4/36 листинга × 7 породи |
| D10 | Породен здравен модул (`health_flags` с поведение) — извън първата версия; ако да — отделен MINOR | по-късно | веднага = нарушава „0 реда сървърен код“ (напомняния по график) и §10.12; при един поддържащ остава наполовина |
| D11 | Правен текст с плейсхолдъри и новото име (§11.8): прегледът е на сесията (сесията е сама); Ив потвърждава, че приема това вместо външен юрист | потвърждение | външен юрист = разход в EUR, когато го поиска |
| D12 | `review_history.yaml`: Ив попълва четирите предишни ревюта на 1.2.x | да, преди 1.4.0 | без история гейтът за преименуване няма данни; повтаряме находка, която вече сме имали |

## 11. Какво НЕ правим сега

- Не създаваме нито един нов bundle id / Play пакет, App Store Connect запис, IAP продукт, App content въпросник, Firebase app, DNS запис или nginx host — T1 не ги иска; T2 и T3 са отхвърлени под лещата.
- Не строим flavors, xcconfig × N, `productFlavors`, схеми, ExportOptions × N, Podfile мапинг — „за всеки случай“ е мъртъв код и 7× диск.
- Не строим фасадите от §3, трите таблици от §2 и домейните от §11.6 на част 1.
- Не пипаме Beagle Owner, бекенда в production или магазините преди Apple да одобри 1.2.7 (замразено до одобрен билд).
- Не строим породен здравен модул, `health_flags`, напомняния по график, породен акцент (D7/D10).
- Не мерим Jaccard/Levenshtein/pHash — при T1 няма ревюърски обект за тях; гейтът е механичен (идентичност, хешове, референции, пълнота).
- Не пращаме `distinctness_report` или метрики на ревюър; review notes описват какво прави приложението.
- Не активираме CPP/CSL в същото подаване с преименуването; не разчитаме на CSL име/икона и на CPP лимити преди D3 да е записано в `docs/STORE-ASO-FACTS.md`.
- Не пускаме self-hosted runner на Mac-а; не подписваме в CI; не изнасяме сертификати и keystore.
- Не трием нищо от домашната директория без D8; не трием симулаторите от `scripts/devices.txt`.
- Не преименуваме `thirteenInch`/`fifteenInch`, не връщаме OTA за пакети, не добавяме породно-специфична колона в `dogs`, не пишем `if breed_key ==` в service слоя или в `lib/`.
- Не даваме срокове и оценки за време.
