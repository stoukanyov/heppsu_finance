# Отказите на магазините — каталог за всички приложения

Всяка грешка, която App Store или Google Play ни е върнал, с дословния текст,
причината в нашия код/процес и поправката. Важи за **всяко** приложение на Heppsu
(Beagle Owner, My Life Within, Universal Dog App и следващите) — правилата са на
магазина, не на проекта. Преди всяко подаване се минава чеклистът в края.

Източник на записите: Beagle Owner, 06.09–17.09.2026 (7 подавания, 6 отказа /
оттегляния). Нов отказ на което и да е приложение → нов ред тук, същия ден.

---

## 1. Apple App Store — какво ни върнаха

| # | дата | guideline | дословно (съкратено) | причината при нас | поправката | как да не се повтори |
|---|---|---|---|---|---|---|
| A1 | 07.09.2026 | **2.1 Information Needed** | screen recording на регистрация / покупка / UGC докладване и блокиране / изтриване на акаунт; цел и аудитория; как се стига до функциите; външни услуги; регионални разлики; регулирана индустрия; **демо акаунтът не влиза** | демо акаунтът от App Review Information не съществуваше в production | клип с времена по секунди; демо акаунт в **production** с данни; бележките в Notes (≤ 4000 знака) отговарят на всичките въпроси | шаблонът `MyBeagle/store/apple-review-reply-2026-09-07.md`; preflight проверява, че демо акаунтът влиза в production |
| A2 | 10.09.2026 | **2.1(b) Performance** | „the in-app purchase products … have not been submitted for review“ | абонаментът беше MISSING_METADATA (без review screenshot) и не беше елемент на подаването | IAP скрийншот през API; подаването = версия + абонамент + група (3 елемента) | `postflight --expect-items 3`; първият абонамент се подава заедно с бинарник; елементи се добавят **само от UI** |
| A3 | 10.09.2026 | **2.1(b) Performance** | „an error occurred when tapping Activate payment“ | клиентът искаше от StoreKit `plus_monthly` вместо `com.heppsu.myBeagle.plus.monthly`; бекендът чакаше StoreKit 1 разписка, а `in_app_purchase_storekit ≥ 0.4.11` праща StoreKit 2 JWS | карта plan code ↔ store product id; `SignedDataVerifier` за JWS + SK1 fallback | sandbox покупка от край до край **преди** всяко подаване с промяна в billing |
| A4 | 10.09.2026 | **Guideline 4 Design** | „permission requests are not in the app's language“ | purpose strings в Info.plist на български, `knownRegions=en` — всеки ги виждаше на български | `ios/Runner/<lang>.lproj/InfoPlist.strings` × всички езици | тест по съдържание на билда (кирилица извън `bg` = 0) |
| A5 | 11.09.2026 | **3.1.2 Subscriptions** (автоматична проверка, ревюто не започва) | „no functional link to the Terms of Use (EULA) in the app metadata“ | в нито едно от 17-те описания нямаше връзка; custom EULA не беше зададена | връзки Terms + Privacy в края на описанието на всичките App Store езици (17, без български) и на екрана за абонамент | preflight: всяка локализация на описанието съдържа двата URL |
| A6 | 14.09.2026 | **3.1.2(c) Subscriptions** | „The billed amount … is not clearly and conspicuously displayed … must be the most clear and conspicuous pricing element in the layout. Any other pricing elements, including free trial, introductory pricing … must be displayed in a subordinate position and size“ | заглавие „Започни с 30 дни безплатно“ без сума; сумата сива под името на плана; „Активирай плащането“ без цена; „0.99 EUR“ за ревюър, когото StoreKit таксува в $0.99 | сумата **от магазина** (`ProductDetails.price`, валутата на storefront-а), най-едрият текст на екрана (32 pt получер), trial под нея по-дребно, на трите екрана на пътя | тестове за размер/позиция на цената; никаква написана цена в ARB/описания/условия |
| A7 | 17.09.2026 | **2.1 Information Needed** | „we need access to a demo account with an **expired subscription** to review the entire purchase flow“ | имахме само демо акаунт с активен абонамент | втори демо акаунт в production с изтекъл абонамент (`status=expired` в хъба); двата в Notes, първият в demo полетата; Reply в нишката; Resubmit от UI | preflight: **два** демо акаунта — активен (пълен с данни) и изтекъл; и двата влизат в production |
| A8 | 21.09.2026 | **2.3.10 Accurate Metadata** (iPad Air) | „remove Google Play references“ — екранът Абонамент, „Manage in App Store/Google Play“ | един низ за двете платформи; 3.1.3(b) беше покрит само в бележката за подновяване, не в бутона | `billingManageInStore` с `{store}` от `Platform.isIOS`; 1.2.8 (80) | тест: никой ARB низ не съдържа „Google Play“ дословно — името на магазина идва от платформата (и в Dog Journey същото правило 🧪 `paywall_test`) |
| — | 21.09.2026 | ITMS-90683 при качване (Dog Journey 0.1.0 (2)) | „Missing purpose string … NSLocationAlwaysAndWhenInUseUsageDescription“ — geolocator реферира API за постоянна локация | ключът липсваше, макар че искаме само „докато се ползва“ | ключът в Info.plist + 18 InfoPlist.strings | тестът за purpose strings носи и този ключ |
| — | 29.08.2026 | ITMS предупреждение при качване | липсващо usage description | Info.plist | добавено | — |
| — | 06.09.2026 ×2 | самооттегляне | грозно съобщение за грешка; дефекти на телефона („нали каза, че всички тестове минават“) | текст на грешките извън l10n; „готово“ без екран на устройство | l10n; 5 резолюции/устройства преди подаване | никакво подаване без реален екран на устройство |
| — | 10.09.2026 | самооттегляне (2 мин) | подаване с **1 елемент** от 3 | упътване по памет за екран, който не бях виждал | Ив добави абонамент + група през UI | състоянието на подаването се проверява през API, не по „готово“ |

### Правила на Apple, в които още не сме се ударили, но ни ограничават
- **3.1.2(a)** — един абонамент може да е споделен между наши приложения, не към чужди. Правото се решава на нашия сървър (хъбът).
- **3.1.3(b)** — никакъв Play линк или „купи го другаде“ в iOS пътя.
- **4.3(a) Spam** — „Don't create multiple Bundle IDs of the same app“ (дословният пример: отделно приложение за всеки град) → едно приложение за всички породи, вариациите през CPP/IAP, не през отделни bundle-и.
- **4.3(b)** — „indistinguishable from what's already widely available… may lead to removal from the Apple Developer Program“ → име с продуктов сигнал, различна информационна архитектура.
- **5.1.1(v)** — акаунт се иска само за функции, които наистина го изискват.
- **5.1.1(i)** — Privacy Policy връзка **вътре** в приложението, не само в ASC.

### Оперативни факти за App Review (доказани)
- Ревюърът чете **Notes** в App Review Information, влиза с демо акаунта в **production**, регистрира и собствен акаунт през Hide My Email (`…@icloud.com`), купува в **Sandbox** — сървърът трябва да приема Sandbox транзакции (production бекенд, който проверява само срещу Production, дава `INVALID_ENVIRONMENT`).
- Демо акаунт с изтекъл абонамент: регистрация през API → `email_verified_at` в базата (кодът отива в несъществуваща кутия) → пробен период през API → в хъба `status='expired'`, период в миналото, събитие за следа → проверка `GET /me/billing` → `entitled:false`.
- Автоматичната проверка за 3.1.2 гледа **метаданните** (описание / custom EULA), не бинарника.
- **UNRESOLVED_ISSUES**: подаването не може да се подаде пак и елементите му не се пипат през API (409) — само бутонът „Resubmit to App Review“ в ASC. Метаданните (описание, бележки) се редактират през API и при REJECTED версия.
- IAP review screenshot не може да се сменя, докато абонаментът е елемент на живо подаване (409 `MEDIA_ASSET_DELETE_NOT_ALLOWED`).
- App Store Server API срещу production дава 401 до първата публикация; срещу sandbox работи.
- Всеки отказ получава **Reply в нишката преди Resubmit** — след Resubmit нишката е заключена. Чернова: `store/apple-review-reply-<дата>.md` в репото на приложението.
- Notes ≤ 4000 знака; App Store езици — 17, без български.

---

## 2. Google Play — какво ни спря

| # | дата | правило / факт | какво стана | поправката | как да не се повтори |
|---|---|---|---|---|---|
| P1 | 06–09.09.2026 | **Unacknowledged purchase** — покупка, непотвърдена в 3 дни, Google анулира и възстановява (`voidedReason 8`) | единствената реална покупка (0,99 €) падна с 503 на сървъра (`verify_purchase` за Android „не е имплементирана“), не беше acknowledged → refund след 3 дни | `googleplay_verification.py` със service account; RTDN през Pub/Sub към `/webhooks/google-play` | реална/лицензирана тестова покупка **преди** production; `voidedpurchases.list` след пускане |
| P2 | 09.09.2026 | 30 дни trial от хъба + 30 от базовия план на Play = 60 | оферта `free-trial-30d` активирана без да се погледне хъбът | офертата деактивирана; пробният период е само на едно място | промени в оферти/цени само с думата на Ив; един източник на trial |
| P3 | 13.09.2026 (проверено, не удар) | **Repetitive Content** — „Creating multiple apps with highly similar functionality, content, and user experience“ → „consider creating a single app“; **Enforcement**: терминация на **всички** свързани акаунти | планът за 7 породни приложения = нарушението по дефиниция; наказанието щеше да засегне и My Life Within | едно приложение за всички породи; ASO през Custom Store Listings | никакви „клонинги“ под нов package name |

### Оперативни факти за Play (доказани)
- App content въпросник (11 секции) минава от първи път, ако се следва `google-play-console-questionnaire` (памет на Business Partner сесията).
- Service account за `androidpublisher` иска „View financial data“ + „Manage orders and subscriptions“; правата се разпространяват ~20 минути.
- RTDN: org политиката `iam.allowedPolicyMemberDomains` блокира системния акаунт на Play — отменя се временно на ниво проект.
- Install Referrer работи само при инсталация от Play (вкл. internal track).

---

## 3. Чеклист преди подаване (за всяко приложение)

Apple:
1. Билд `VALID`, версията `MANUAL` release.
2. Подаването има **3 елемента** (версия + абонамент + група) при първи абонамент; проверено през API, не по „готово“.
3. IAP с review screenshot и локализации.
4. **Два демо акаунта в production**: активен (с данни на всеки екран) и **с изтекъл абонамент**; и двата влизат (проверено с curl същия ден); и двата в Notes.
5. Notes ≤ 4000: какво е ново от последния отказ, къде е всяка функция, външни услуги, регионални разлики, регулирана индустрия, UGC докладване/блокиране, изтриване на акаунт.
6. Описание на всички App Store езици с Terms + Privacy връзки; Privacy Policy връзка и вътре в приложението.
7. Цената от магазина, най-едрият текст на всеки екран от пътя на покупката; trial по-дребно под нея; нищо написано в ARB.
8. Purpose strings на всички езици; кирилица извън `bg` в билда = 0.
9. Sandbox покупка от край до край срещу production бекенда — доказана с лог.
10. 5 резолюции/устройства реално прегледани; никакво съобщение за грешка извън l10n.
11. При отказ: Reply в нишката → поправка → Resubmit от UI → API: `WAITING_FOR_REVIEW`, елементи `READY_FOR_REVIEW`.

Google Play:
1. `verify_purchase` за Android работи срещу production (лицензиран тестер купува, сървърът потвърждава, `acknowledgementState=1`).
2. RTDN подписан и тестван (200).
3. Пробен период само на едно място (хъб **или** базов план).
4. App content въпросникът по шаблона; Data safety съвпада с реалните SDK-та.
5. Един package name за продукт — никакви варианти по порода/град/тема.

---

## 4. Къде живее това
- Този файл (`Business Partner/docs/STORE-REJECTIONS.md`) е каналният запис; указател към него има в `~/.claude/CLAUDE.md`, за да го виждат всички сесии във всички репота.
- Историята по подавания на Beagle Owner и точните API извиквания са в паметта на Business Partner сесията (`reference-app-store-review-history-beagle-owner`, `reference-store-api-procedures`, `reference-store-rules-that-stopped-us`).
