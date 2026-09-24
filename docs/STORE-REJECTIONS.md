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
| M1 | 15.09.2026 | **2.1(b) Performance** (My Life Within) | „the associated In-App Purchase products have not been submitted for review“ | подаване през API с 1 елемент (версията); абонаментите `READY_TO_SUBMIT` четени като „наред“ | групата + двата абонамента добавени от UI (Subscriptions → Add for Review → същата чернова); `tool/store/review_gate.py` брои елементите на подаването | подаването се проверява през API: група + абонаменти + версия |
| M2 | 17.09.2026 | **2.3.10 Accurate Metadata** (My Life Within, iPad Air) | „remove Google Play references“ — „Cancel any time in the App Store or Google Play“ в бележката за подновяване и в статията за абонамента | един низ за двете платформи в 10 езика | `{store}` в ARB с предлога вътре („im App Store“/„bei Google Play“), `storeName` по `defaultTargetPlatform`; тест през всички езици | никакво „Google Play“ в iOS низовете, никакво „App Store“ в Android — тест |
| M3 | 17.09.2026 | **3.1.2(c) Subscriptions** (My Life Within) | „a functional link to the Terms of Use (EULA)“ липсва в приложението и в метаданните | условия за ползване изобщо нямаше; екранът Pro сочеше само политиката | `docs/terms-of-use*.md` → heppsu.com, връзка в екрана Pro и в края на описанието на всеки език, бележките изброяват название/срок/цена/връзки | генерирани правни документи от първия ден (APP-BASELINE); тест: описанието съдържа terms-връзка |
| M4 | 21.09.2026 | **3.1.2(c) Subscriptions** (My Life Within, iPad Air M4) | „offers a free trial … but does not make it clear that a payment will be automatically initiated for the next subscription period … clearly indicate how long the free trial lasts and the amount that will be billed after“ | значка „First month free“ + сумата в плочката + обяснението в дребен сив текст ПОД бутона; нищо не свързваше трите в едно изречение над бутона | ред над бутона за избрания план: „Първият месец е безплатен, после {цена} на година. Таксува се автоматично, ако не спреш…“ (14 pt, получер); бутонът „Започни безплатния месец — после {цена}“; връзките (политика, условия, управление на абонамента) натискаеми; тест за текст, позиция и смяна на плана | правило: trial → едно изречение с (1) колко трае, (2) сумата от магазина, (3) „автоматично“, (4) периода — над бутона, четимо; Apple: „clearly indicate how long the free trial lasts and the price billed once the free trial is over“ |
| M5 | 24.09.2026 | **2.1 Information Needed** (My Life Within, iPad Air M3) | „What AI service process data? What type data is processed by AI service? What personal data is processed by AI service?“ | нашите собствени бележки изброяваха липси: „no analytics SDK, no advertising… **no AI service**, no cloud storage“ — ревюърът (или автоматичната проверка) вижда думите „AI service“ и пита; изброяването на липси чете като признание | редът започва с „NO artificial intelligence or machine learning of any kind: no AI service, no on-device ML model, no generative feature, no data sent to any AI provider“ + едно изречение какво СА прогнозите (средна стойност и разсейване, смятани на устройството); отговор в нишката с трите въпроса поотделно; без нов билд | в бележките не се изброяват липси с имена на технологии — пише се какво приложението ПРАВИ; ако темата е неизбежна (AI, реклами, тракери), веднага следва изречение какво е вместо това |
| — | 21.09.2026 | ITMS-90683 при качване (Dog Journey 0.1.0 (2)) | „Missing purpose string … NSLocationAlwaysAndWhenInUseUsageDescription“ — geolocator реферира API за постоянна локация | ключът липсваше, макар че искаме само „докато се ползва“ | ключът в Info.plist + 18 InfoPlist.strings | тестът за purpose strings носи и този ключ |
| A9 | 24.09.2026 | **2.1 Information Needed** (iPad Air, 1.2.8 (80)) | „We were unable to sign in with the following demo account credentials“ | демо акаунтът `applereview@heppsu.com` беше **изтрит на 21.09 в 18:49 UTC** с `DELETE /auth/me?reason=too_expensive` при наше тестване на изтриването — бекендът и таблицата `users` са общи за Beagle Owner и Dog Journey, а подаването вече беше в опашката | пресъздаване с `MyBeagle/tool/store/review_accounts.py create`; Reply + Resubmit | `review_accounts.py check` (чете данните от App Review Information, влиза в production, показва абонамент и данни) — **преди всяко подаване И след всяко тестване по акаунти срещу production**; демо акаунтите не се ползват за ръчно тестване |
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
0. `python3 "Business Partner/tools/store_gate.py" <репо>` минава зелено (механичните точки: магазинни имена по платформа, написани цени, правни връзки, trial изречение, purpose strings).
1. Билд `VALID`, версията `MANUAL` release.
2. Подаването има **3 елемента** (версия + абонамент + група) при първи абонамент; проверено през API, не по „готово“.
3. IAP с review screenshot и локализации.
4. **Два демо акаунта в production**: активен (с данни на всеки екран) и **с изтекъл абонамент**; и двата влизат — `python3 tool/store/review_accounts.py check` зелен **в деня на подаването и отново след всяко тестване по акаунти** (A9: акаунтът умря 27 минути след Resubmit); и двата в Notes. Демо акаунт не се ползва за ръчно тестване — нито за изтриване, нито за покупка.
5. Notes ≤ 4000: какво е ново от последния отказ, къде е всяка функция, външни услуги, регионални разлики, регулирана индустрия, UGC докладване/блокиране, изтриване на акаунт.
5б. В бележките НЕ се изброяват липси с имена на технологии („no AI service“, „no trackers“) — те задават въпроси (M5). Пише се какво приложението прави; при AI/ML изрично: няма никакъв, и какво е вместо него.
6. Описание на всички App Store езици с Terms + Privacy връзки; Privacy Policy връзка и вътре в приложението.
7. Цената от магазина, най-едрият текст на всеки екран от пътя на покупката; trial по-дребно под нея; нищо написано в ARB.
7б. При trial/intro оферта: над бутона едно четимо изречение — колко трае, сумата и периодът след това, „таксува се автоматично, ако не спреш“ — за избрания план; бутонът повтаря сумата (M4).
7в. Политика, условия и „управлявай/спри абонамента“ са **натискаеми** връзки на екрана за покупка (Apple „functional link“, Play „direct access to your cancellation process“ → Play Subscription Center).
8. Purpose strings на всички езици; кирилица извън `bg` в билда = 0.
9. Sandbox покупка от край до край срещу production бекенда — доказана с лог.
10. 5 резолюции/устройства реално прегледани; никакво съобщение за грешка извън l10n.
11. При отказ: Reply в нишката → поправка → Resubmit от UI → API: `WAITING_FOR_REVIEW`, елементи `READY_FOR_REVIEW`.
12. **2.3.10**: никакви имена/икони на други платформи в приложението и метаданните — името на магазина идва от `Platform`, никога от превода (тест: ARB без „Google Play“/„App Store“/„Android“ — и в двете приложения).
13. **4.3 / решение на Ив, 21.09.2026**: пред ревюърите никаква следа от общия бекенд, от Beagle Owner или от споделения абонамент — нито в Notes, нито в описанията, нито на екран, който демо акаунтът може да отвори (тест над `docs/store/*`; проверка на ASC/Play локалите преди качване).
14. **Само iPhone** (решение на Ив, 21.09.2026): `TARGETED_DEVICE_FAMILY = 1` и в двете приложения, без iPad оформления/скрийншоти/тестове. Ревюърът все пак може да отвори приложението на iPad (21.09.2026: iPad Air 11" M3) — Apple не дава опция за забрана; там то върви в iPhone-режим (прозорец с iPhone размер), тоест iPhone екраните са единствените, които трябва да са наред.

Google Play:
0. `tool/store_gate.py` (Business Partner/tools) минава зелено върху репото — механичните точки от този списък.
1. `verify_purchase` за Android работи срещу production (лицензиран тестер купува, сървърът потвърждава, `acknowledgementState=1`).
2. RTDN подписан и тестван (200).
3. Пробен период само на едно място (хъб **или** базов план).
4. App content въпросникът по шаблона; Data safety съвпада с реалните SDK-та.
5. Един package name за продукт — никакви варианти по порода/град/тема.
6. Play Subscriptions policy: преди покупката — цена, честота на таксуване, автоматично подновяване, кога и как пробният период става платен и как се отказва — **на самия екран, без допълнително действие**; в приложението има път към отказ (Manage in Google Play).

### Дословно от насоките (свалено 21.09.2026; източниците са в `reference-store-rules-that-stopped-us`)
| правило | цитат | механизъм при нас |
|---|---|---|
| Apple 2.3.10 | „don't include names, icons, or imagery of other mobile platforms or alternative app marketplaces in your app or metadata“ | ARB guard тест (BO `store_names_per_platform_test`, DJ `store_metadata_guard_test`); `listings_upload.py` отказва „Google Play/Android“ в ASC текст и „App Store/iOS/iPhone“ в Play текст |
| Apple 2.3.7 | „Metadata … should not include prices, terms, or descriptions that are not specific to the metadata type“; „should not … reference other apps“ | `check()` в `listings_upload.py`: без цена, без „Beagle“ |
| Apple 2.3.1(a) | „All new features … must be described with specificity in the Notes for Review“ | Notes се обновяват при всяко подаване (`review-notes-*.md`) |
| Apple 2.1(a)/(b) | „include demo account info (and turn on your back-end service!)“; „make sure [IAP] are complete … visible to the reviewer and functional“ | два демо акаунта в production, проверени с curl; подаване с 3 елемента |
| Apple 3.1.2(a) | „Subscriptions must work on all of the user's devices … Learn more about sharing a subscription across your apps“ | хъбът + леджърът; **не се обявява** пред ревюърите (т. 13) |
| Apple subscriptions page | „the amount that will be billed must be the most prominent pricing element in the layout“; „clearly indicate how long the free trial lasts and the price billed once the free trial is over“; „A way for current subscribers to sign in or restore purchases“; „links to your Terms of Use and Privacy Policy“ | тестове за prominence, trial бележка, Restore, LegalLinks на paywall-а |
| Apple subscriptions page | „verify that they're active subscribers before showing any subscription options“ (multi-app) | `PlusState.includedElsewhere` — без бутон за покупка |
| Apple 5.1.1(v) | „If your app supports account creation, you must also offer account deletion within the app“; „let people use it without a login“ | local-first; DeleteAccountScreen 🧪 |
| Apple 5.1.1(i) | „link to their privacy policy … within the app in an easily accessible manner“ | LegalLinks на paywall, регистрация, Акаунт |
| Apple 1.2 | „A mechanism to report offensive content … The ability to block abusive users … Published contact information“ | F11 преди пускане на глутницата |
| Apple 4.3(a)/(b) | „Don't create multiple Bundle IDs of the same app“; „indistinguishable from what's already widely available“ | различна IA, име с продуктов сигнал, никакво споменаване на BO |
| Play Subscriptions | „clearly and explicitly disclosing your offer terms, the cost … the frequency of your billing cycle, the automatic renewal terms“; „Users should not have to perform any additional action to review the information“ | `SubscriptionPrice` renewalNote на екрана |
| Play Subscriptions | „clearly disclose how a user can manage or cancel their subscription“ | бутон Manage in Google Play на Android |

---

## 4. Къде живее това
- Този файл (`Business Partner/docs/STORE-REJECTIONS.md`) е каналният запис; указател към него има в `~/.claude/CLAUDE.md`, за да го виждат всички сесии във всички репота.
- Историята по подавания на Beagle Owner и точните API извиквания са в паметта на Business Partner сесията (`reference-app-store-review-history-beagle-owner`, `reference-store-api-procedures`, `reference-store-rules-that-stopped-us`).

---

## 5. Правилата дословно — това, срещу което се проверява всеки билд

Извлечени от developer.apple.com (App Review Guidelines, „Auto-renewable
subscriptions“) и support.google.com (Play Subscriptions policy) на 21.09.2026.
Правилото се чете оттук, не се предполага.

### Apple
- **3.1.2(c) Subscription Information:** „Before asking a customer to subscribe, you should clearly describe what the user will get for the price… Ensure you clearly communicate the requirements described in Schedule 2.“
- **Sign-up screen (Apple, Auto-renewable subscriptions):** трябва да съдържа „Subscription name and duration, and the content or services provided during the subscription period; Full renewal price, shown clearly and prominently, and localized in available currencies; A way for current subscribers to sign in or restore purchases.“
- **Billing amount:** „In the purchase flow, the amount that will be billed must be the most prominent pricing element in the layout… breakdown price… or savings… should be displayed in a subordinate position and size.“
- **Free trials:** „In the purchase flow for a free trial, clearly indicate how long the free trial lasts and the price billed once the free trial is over.“ (→ M4: едно изречение над бутона)
- **3.1.2(a):** trial „by providing the relevant information set forth in App Store Connect“; абонаментът работи на всички устройства на човека; scam/bait-and-switch = сваляне от програмата.
- **3.1.2(b):** upgrade/downgrade без възможност човек неволно да се абонира за две вариации на едно и също (→ една група).
- **3.1.1:** отключване на функции само през In-App Purchase — никакви ключове, кодове, външни плащания.
- **2.3.10:** „don't include names, icons, or imagery of other mobile platforms or alternative app marketplaces in your app or metadata“ (→ A8/M2).
- **5.1.1(i):** политика за поверителност „in the App Store Connect metadata field and within the app in an easily accessible manner“, с какво се събира, с кого се споделя, как се трие.
- **5.1.1(v):** без акаунт, ако няма значими функции по акаунт; има ли регистрация — има и изтриване в приложението.
- **4.3(a)/(b):** без много Bundle ID-та на едно и също приложение; без неразличими клонинги.

### Google Play (Subscriptions policy)
- Преди покупка: „clearly and explicitly disclosing your offer terms, the cost of your subscription, the frequency of your billing cycle, the automatic renewal terms, whether a subscription is required to use the app, and any other material information.“
- „Users should not have to perform any additional action to review the information.“ (→ не под бутона, не след скрол, не в друг екран)
- Trial/intro: „clearly and accurately describe the terms of your offer, including the duration, pricing… how and when a free trial will convert to a paid subscription, how much the paid subscription will cost, and how a user can cancel.“
- Спиране: „clearly disclose how a user can manage or cancel their subscription“ с „direct access to your cancellation process“ — линк към Play Subscription Center от настройките или еквивалентна страница (→ `pro-manage-link`).
- Unacknowledged purchase → анулиране в 3 дни (P1); trial само на едно място (P2); Repetitive Content (P3).

### Механизъм
`tools/store_gate.py <репо> [--online]` в това репо; вика се преди всеки
`release_build`, червен ред спира билда. Останалото (демо акаунти, sandbox
покупка, 5 резолюции, RTDN, елементите на подаването) — чеклистът в раздел 3
и `tool/store/review_gate.py` в репото на приложението.
