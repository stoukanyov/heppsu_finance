# Факти за архитектурата „още 6 породи“ — събрани на 13.09.2026, всяко с източник

## 1. Политики на магазините — дословно

### Apple App Store Review Guidelines, 4.3 Spam
URL: https://developer.apple.com/app-store/review/guidelines/ (изтеглено 13.09.2026)

(a) „Don't create multiple Bundle IDs of the same app (for example, submitting a separate map app for every city in the world instead of a single worldwide map that allows users to search any city). This practice results in unnecessary apps, which makes it hard for users to find the apps they want. If your app has different versions for specific locations, sports teams, universities, etc., consider submitting a single app and providing the variations using in-app purchase.“

(b) „Don't submit apps that are indistinguishable from what's already widely available. Opportunistically creating variants of existing app categories or popular apps degrades App Store discovery, reduces overall app quality, and harms both users and developers. […] Repeated submissions of this kind may lead to removal from the Apple Developer Program.“

Няма подточка (c).

### Google Play — Spam policy → Repetitive Content
URL: https://support.google.com/googleplay/android-developer/answer/9899034 (изтеглено 13.09.2026)

Определение: „We don't allow apps that merely provide the same experience as other apps already on Google Play.“
Примери за нарушения: „Copying content from other apps without adding any original content or value.“ / „Creating multiple apps with highly similar functionality, content, and user experience.“
Препоръка: developers „should consider creating a single app that aggregates all the content“.

### Google Play — Enforcement Process
URL: https://support.google.com/googleplay/android-developer/answer/9899234

„Repeated or serious violations (such as malware, fraud, and apps that may cause user or device harm) of these policies or the Developer Distribution Agreement (DDA) will result in termination of individual or related Google Play Developer accounts.“
„When your developer account is terminated, all apps in your catalog will be removed from Google Play and you will no longer be able to publish new apps. This also means that any related Google Play developer accounts will also be permanently suspended.“

Следствие: Beagle Owner и My Life Within са в СЪЩИТЕ developer акаунти (Apple team Heppsu, Play developer account Heppsu). Спам находка не е отказ на едно приложение — е риск за всички продукти.

### Известни прецеденти (от търсене; вторични източници, не официални)
- Класическият пример в Play документацията и в блоговете: „Weather Forecast for New York / Los Angeles / Miami“ — един и същ код, различно име на града = Repetitive Content. Породата е същият клас вариация като „locations, sports teams, universities“ в Apple 4.3(a).
- Play Developer Community нишки за „Repetitive Content Policy for apps with same name“ / „violation“: отказът обикновено идва при второто-третото подобно приложение от същия акаунт; помага реална функционална разлика и различно съдържание, не преименуване.

## 2. ASO вътре в ЕДНО приложение — какво дават магазините днес

### Apple Custom Product Pages (CPP)
- От 30.07.2025 CPP могат да получават ключови думи и да се показват ОРГАНИЧНО в резултатите от търсене в App Store; от 29.10.2025 лимитът е 70 страници на приложение. Всяка комбинация от ключови думи е уникална за една страница. (източници: apptweak.com, respectaso.com, adapty.io — блогове на ASO инструменти, 2026)
- CPP сменя скрийншоти, app previews и promotional text. НЕ сменя името, иконата и подзаглавието на приложението.

### Google Play Custom Store Listings (CSL)
- От Google I/O 2024: таргетиране по ключови думи в Play търсенето („Custom store listings by keywords“); до 50 листинга (100 за Play партньори); таргетиране и по държава, състояние на потребителя, Google Ads кампания, уникален URL. (източници: mobileaction.co, phiture.com, apptweak.com, 2025–2026)
- CSL позволява различни текстове и графики за листинга; дали позволява различно ИМЕ на приложението — ДА СЕ ПРОВЕРИ в Play Console преди да се разчита на това.

## 3. Клиентът днес (MyBeagle, проверено с grep на 13.09.2026)
- Android: `android/app/build.gradle.kts:22` namespace `com.heppsu.my_beagle`, `:40` applicationId `com.heppsu.myBeagle`; НЯМА productFlavors/flavorDimensions; versionCode от pubspec; signingConfig release от keystore.properties.
- iOS: `ios/Runner.xcodeproj/project.pbxproj` — PRODUCT_BUNDLE_IDENTIFIER на 6 места (3 конфигурации × Runner + RunnerTests), `com.heppsu.myBeagle`; PRODUCT_NAME = $(TARGET_NAME); AppIcon в asset catalog; НЯМА xcconfig на flavor, една схема Runner.
- `scripts/build_release.sh`: 58 реда; само `--dart-define=API_BASE_URL`; копира в `releases/MyBeagle-<ver>.aab/.ipa`; не пуска тестове; не чисти.
- Икона: flutter_launcher_icons от `assets/icon/icon.png`; сплаш `assets/images/splash_screen.png`; рисунка `assets/images/beagle_measurement.png`.
- Тема: `lib/theme/app_theme.dart` — една палитра (кафява, „следва оцветяването на бийгъла“).
- l10n: 733 ключа в app_en.arb, 20 споменават породата/марката (appName, tagline, planPlusMonthly, beagleFactTitle, shareApp*, nearbyDogs, noNearbyDogs, communityQrPrivacyNote, heightMeasurementWhyBody, weightOutOfRangeWarning, weightRangeDialogBody, defaultBreedBeagle, passportSharePreamble, subscriptionRequiredBody, termsAcceptanceBody, meetupMessageHint, noMeetupsHint); 18 езика.
- Справочни данни: `lib/models/beagle_facts.dart` (100 факта, днес само 9 от 18 езика), `lib/models/beagle_reference.dart` (2 размерни варианта по височина — специфично за бийгъла, крива на теглото 19 точки, прагове 0.10/0.20/0.30, puppyTips, източници AKC/National Beagle Club/Royal Canin/VCA/WSAVA).
- Store продукти: `lib/services/store_product_ids.dart` — Play `plus_monthly`, App Store `com.heppsu.myBeagle.plus.monthly`.
- Артефакти: .aab ≈ 80 MB, .ipa ≈ 31 MB на билд; releases/ = 1,9 GB (7 файла); build/ = 2,1 GB.
- Магазини: `store/` има листинг текстове и скрийншоти iOS само bg/en/pt, Android само en (при правило „всички езици, винаги“).

## 4. Дискът (проверено 12.09.2026)
- Mac (билд машината): 228 GB, 180 GB заети, **9,6 GB свободни (95%)**. ~/Library/Developer/Xcode 14 GB (DerivedData 2 GB), ~/Library/Caches 11 GB, Android SDK 9,1 GB, .gradle 6 GB, CoreSimulator 4,9 GB, MyBeagle/build 2,1 GB, releases 1,9 GB, .pub-cache 1,1 GB. Xcode грешка 74 (пълен диск) вече се е случвала.
- Арес (production): 193 GB, 7,4 GB заети (4%); docker images 1,85 GB, build cache 2,95 GB (1,87 reclaimable). Общият бекенд не умножава нищо на сървъра.
- Извод: дисковият проблем е билд машината. 7 приложения × 2 платформи × ~111 MB артефакти = ~780 MB на версионен цикъл само в releases/, плюс build/ и DerivedData, ако не са общи.

## 5. Част 1 на архитектурата (MyBeagleApi/docs/ARCHITECTURE-multi-breed.md, 879 реда, 09–10.09.2026) — решено и отворено

Решено (по секции):
- §1: „Един процес, една схема, девет фасади: съдържанието носи breed_key, идентичността на приложението се впечатва от nginx и се подпечатва в сесията при вход, а акаунтът, блокирането, местата, приятелствата и абонаментът остават умишлено общи.“ Четири принципа: П1 контекстът на приложението стеснява ОТКРИВАНЕТО на непознати, никога собствените данни/достъпа; П2 идентичността идва от ръба и ръбът е самопроверяем; П3 породата виси на КУЧЕТО, марката на АРТЕФАКТА, безопасността е глобална; П4 всяка проверка за видимост важи за всеки канал към същите данни.
- §2: регистър на приложенията в кода (`app/core/apps.py`, AppProfile) по две оси (git, среда); `breed_key` контролирана стойност; три нови таблици; какво НЕ получава breed/app_key.
- §3: бекендът разбира кое приложение пита от nginx host (`mypug.heppsu.com` + `mypug-test.heppsu.com`), env на всяка среда (`PUBLIC_BASE_URL_<KEY>`, `SUBHUB_API_KEY_<KEY>`, `COCKPIT_APP_TOKEN_<KEY>`), dod.yml брои приложенията.
- §4: обхват по порода за откриване (наблизо, разходки, запознанства); модерацията следва повърхността на контакта; глобален блок.
- §5: ЕДИН абонамент на човек за всички приложения (препоръка); по един Play пакет / App Store bundle / ASSN URL на приложение; RTDN към същия топик; `appstore_verification._client(bundle_id)`.
- §6: брандиране/писма/правни документи параметризирани (3 плейсхолдъра, 54 общи файла), push заглавие по приложение.
- §7: справочните данни ОСТАВАТ В БИЛДА, един източник в git: `content/breeds/<breed_key>/pack.yaml` (units, varieties[{code, applies_to_sex, weight_kg{min,max}, shoulder_height_cm{min,max}, source_ids}], combined_weight_kg, weight_curve[{max_age_months, reference_kg}], weight_thresholds{ideal,normal,attention}, sources[{id,url,publisher,retrieved_at}]) + `texts/<lang>.yaml` + `facts/<lang>.yaml` → `scripts/gen_breed_assets.dart` → `assets/breed/<key>/*.json`; OTA отхвърлена; enum BeagleHeightVariety → данни BreedSizeVariant; кодовете thirteenInch/fifteenInch не се преименуват; ARB ключовете с порода получават плейсхолдър.
- §7.4: добавяне на порода = pack + 18+18 текстови файла, ред в apps.py, DNS, env, Firebase app, магазини, „клиент: нов flavor (§10.9 — това е реалната работа)“. „Нула редове нов сървърен код.“
- §9: миграционен път R-1 (предусловия, вкл. Apple 4.3), R0 (днешни дефекти), R1..R8, R9 = приложение №2 като приемен тест.
- §10.12: прагове, при които архитектурата умира: трета nullable колона в dogs за едно приложение; първо `if app.app_key ==` в service слоя; приложение №3 → преразглеждане на общия процес.

Отворено (§10.9, §11):
- §10.9: магазинните операции — „скъпата половина, нерешена“: flavors, xcconfig, икони × N, launch screens × N, листинги N × 2 × 18, скрийншоти на 5 резолюции, IAP продукти с локализации, App content въпросници, ревю опашки; нула CI.
- §11.1: Apple 4.3 — „предхожда R-1“; алтернативата е едно приложение с избор на порода, при която `breed_keys` като списък прави отстъплението промяна на данни.
- §11.2/3: един абонамент и една цена за всички (препоръка: да).
- §11.4/5: кой пише 100 факта × 18 езика × N породи; приема ли се 40 вместо 100.
- §11.6: домейни `my<breed>.heppsu.com` + `my<breed>-test.heppsu.com`.
- §11.7: едно приложение = една порода, или група („Terrier Owner“)? — `breed_keys` е списък точно затова.
- §11.8: правният текст параметризиран — потвърждение от юрист.

## 6. Ограничения на Ив (правила, които важат)
- Български; без срокове/оценки за време; мерки = скрипт/тест/гейт; всички езици, винаги; промени в магазините само с негово одобрение; една стъпка наведнъж към него; SemVer; тест преди production с tested/<sha>; production само с изричен sha; Definition of Done: тестове + документация + CI със статичен и динамичен анализ.
- Днес няма CI в нито едно репо. Един поддържащ.
