# Beagle Owner — пълен brain-dump (14.09.2026)

По заявка на сесията „Dog Application“. Раздели 1–4, 7, 8 са написани от шест агента с четене на кода (file:line, „проверено с“ там, където е пускана команда); раздели 5, 6, 9, 10 — от сесията Beagle Owner по паметта и документите. Идентификатори, ключове и адреси нарочно липсват — в паметта на проекта (`memory/reference-store-api-procedures.md`, `memory/project-mybeagle-deploy.md`, `memory/reference-ssh-kliuchove-mashini.md`).

Свързани: `DOG-APPS-BRAINDUMP-2026-09-14.md`, `LESSONS-LEARNED-beagle-owner-2026-09.md`, `ARCHITECTURE-universal-dog-app.md`, `PLAN-universal-dog-app.md`.

---

## 1. Продуктът

### 1.1 Обща рамка

- **Клиент:** Flutter, `pubspec.yaml:20` → `version: 1.2.7+78` (проверено с: `sed -n 20p pubspec.yaml`, 19:40 UTC). 18 езика (`ls lib/l10n/*.arb | wc -l` → 18, 19:44 UTC). Бекенд адресът идва от `--dart-define=API_BASE_URL` (`lib/main.dart:44-47`); release без него спира още на старта (`lib/main.dart:62-67`).
- **Бекенд:** FastAPI, всички модули под `settings.API_V1_PREFIX` (`MyBeagleApi/app/main.py:100-116`); извън префикса са само `/get-app` (`app/modules/applink/router.py:31`) и `/legal/*` (`app/modules/legal/router.py:69-86`).
- **Тестове:** клиент 82 файла / 336 случая, бекенд 33 файла / 385 случая (проверено с: `find test -name '*_test.dart' | wc -l`, `grep -rhoE "^\s*(testWidgets|test)\(" test | wc -l`, `find tests -name 'test_*.py' | wc -l`, `grep -rhoE "def test_" tests | wc -l`, 19:45 UTC — броене по grep, не изпълнение).
- **Гейтове преди табовете** (`lib/screens/root_shell.dart:37-54`), в този ред: вход → приети условия → държава (онбординг) → активен абонамент/пробен период. Без фрийемиум: `entitlement.isPlus == false` заключва цялото приложение (`root_shell.dart:54`, `lib/screens/account/subscription_required_screen.dart:11-16`). `isPlus` е fail-open — неконфигуриран хъб или мрежова грешка не заключват (`lib/services/entitlement_store.dart:12-15, 27-29`).
- **Пет таба** (`root_shell.dart:151-157`): Начало, Досие, Календар, Наблизо, Общност — `IndexedStack`, всеки таб пази свой Scaffold. Календарът се презарежда с токен при всяко активиране (`root_shell.dart:117-121`).
- **Активно куче:** `DogStore.selectedDog`, сменя се от `DogSwitcher` (`lib/widgets/dog_switcher.dart:9-12`), споделено между Начало, Общност и Наблизо → Срещи.

### 1.2 Идентичност (регистрация, вход, имейл код, парола)

**Екрани:** `AuthForm` (`lib/screens/account/account_screen.dart:354-555`, показан и от `_AuthGate` в `root_shell.dart:61-99`), `VerifyEmailScreen` (`lib/screens/account/verify_email_screen.dart`), `ForgotPasswordScreen`, `ResetPasswordScreen`. Езикът е сменяем още преди вход (`root_shell.dart:92`, `lib/widgets/language_switcher.dart:31-34`). „Съобщи проблем“ е достъпен от екрана за вход (`account_screen.dart:542-550`).

**Уъркфлоу регистрация:** имейл + парола (≥8, `account_screen.dart:491-492`) + потвърждение на паролата само при регистрация (`:499-509`) → `POST /auth/register` (`lib/services/auth_api.dart:43`; `app/modules/identity/router.py:99`) → екран за 6-цифрен код, въведен в приложението, не линк в писмо (`account_screen.dart:398-405`) → `POST /auth/verify-email` (`auth_api.dart:64`; `router.py:136`) → връщане към вход с текст „регистрацията е готова“ (`account_screen.dart:407-412`). Повторно изпращане: `POST /auth/resend-verification` (`verify_email_screen.dart:86`; `router.py:156`).

**Уъркфлоу вход:** `POST /auth/login` (`auth_api.dart:55`; `router.py:223`) → fire-and-forget `sync()` за сваляне на кучетата на ново устройство (`account_screen.dart:425-430`). 401 отвсякъде → `AuthStore.expireSession` → екран за вход със снакбар (`lib/main.dart:163`, `root_shell.dart:74-83`).

**Забравена парола:** `POST /auth/password-reset/request` (`forgot_password_screen.dart:41-47`; `router.py:177`) → `ResetPasswordScreen` с код + нова парола → `POST /auth/password-reset/confirm` (`reset_password_screen.dart:79`; `router.py:199`).

**Прагове на бекенда** (`identity/router.py:35-92`): вход (двойка IP+акаунт, акаунт, IP), заявка за код (брои всяко обръщане, вкл. регистрацията — `:170-177`), харчене на код (отделен брояч, не се нулира от нова заявка). Грешките се превеждат в клиента през `lib/services/auth_error_text.dart`.

**Профил:** `GET/PATCH /auth/me` (`auth_api.dart:120,132`; `router.py:242,247`) — държава и име на собственика; `POST /me/accept-terms` (`auth_api.dart:149`; `router.py:272`); `GET/PUT /me/home-layout` (`router.py:280,285`).

### 1.3 Онбординг (условия, език, име, държава)

- **Условия** (`lib/screens/onboarding/terms_acceptance_screen.dart:9-18`): еднократен гейт след първия вход; линкът отваря публикуваните условия външно (`:48`), бутон „Приемам“ → `AuthStore.acceptTerms` (`lib/services/auth_store.dart:167`). Бекендът допълнително пази с `require_terms_accepted` създаването на места/отзиви и групови разходки (`app/modules/places/router.py:25,69`, `app/modules/social/router.py:213`).
- **Онбординг** (`lib/screens/onboarding/onboarding_screen.dart:10-19`): три стъпки, решавани от `switch` на `(_languageChosen, fullName)` (`:80-84`): език (`LocaleController.setLocale`, `:55`) → име на собственика (`setFullName`, `:42`; собственикът е акаунтът, не полето на кучето — `:32-35`) → държава, търсима, показвана на езика на приложението (`:141-145`; `setCountry`, `:65`). `RootShell` сам превключва към табовете, щом `country != null` (`root_shell.dart:48`). Държавата определя дали ЕС паспортът изобщо се предлага (`:16-19`).

### 1.4 Досие (таб „Досие“)

**Списък** (`lib/screens/dogs/dog_list_screen.dart:12-59`): всички кучета, икона към Акаунт (`:22-28`), FAB „Добави куче“ с два избора (`:62-99`): ново куче → `AddDogScreen`; „Присъедини споделено куче“ → `JoinSharedDogScreen`. Лимитът по брой кучета отпадна с цялостното заключване (`:81-84`).

**Добавяне** (`lib/screens/dogs/add_dog_screen.dart:17-20`): име, пол (задължителен, без подразбиране — `:32-34`), дата на раждане, снимка по избор → локален запис + изчакван `sync()` с видима грешка при неуспех (`:87-107`) → въпрос „да включим ли напомнянията?“ → `RemindersScreen` (`:117-141`). Ендпойнти през `SyncService`: `POST /dogs`, `PATCH /dogs/{id}`, `PUT /dogs/{id}/photo` (`lib/services/dogs_api.dart:23,28,38`; `app/modules/dogs/router.py:44,95,142`).

**Детайл** (`lib/screens/dogs/dog_detail_screen.dart:33-37`, тяло `:380-585`): карта „пълнота на профила“ (`:391`), профилна снимка със смяна/изчистване (`:393-397`; `DELETE /dogs/{id}/photo`, `dogs/router.py:178`), порода, височинна разновидност с диаграма къде се мери (`:405-410`, `:734-748`, `lib/widgets/beagle_measurement_diagram.dart`), редактируема дата на раждане (`:412-415`), собственик само за четене, води към профила (`:422`, `:47-49`), микрочип (`:424-431`), кръвна група (`:434-448`), бележки (`:450-456`). Изтриване на кучето от AppBar (`:382-386`; `DELETE /dogs/{id}`, `dogs/router.py:126`). Бутони надолу (`:489-576`): Родословие, Здраве, Ваксинации (Здраве, филтрирано към поставени — `:507-529`), Сподели с ветеринар, Съсобственост, Хранене, Изложби, Приятели.

**Hero снимка** (`lib/screens/dogs/hero_photo_adjust_screen.dart:10-15`): позициониране/мащаб на снимката за лентата в Начало (drag + pinch), отваря се от Начало (`lib/screens/home/home_screen.dart:312-318`).

**Тегло** (`lib/screens/dogs/weight_section.dart:16-21`, `WeightScreenBody`): отделна страница вътре в Здраве при филтър „тегло“ (`lib/screens/dogs/health_screen.dart:146-149`) — текущо тегло със степер, референтен диапазон по възраст (`lib/models/beagle_reference.dart:70,139`), четири зони, BCS, графика на историята, бележка. Записва се като `HealthEvent` тип `weight` през `POST /dogs/{id}/health-events`; единиците са локални за устройството, сървърът пази kg (`lib/screens/account/units_screen.dart:8-11`).

**Здраве** (`health_screen.dart:15-38`): списък на всички записи с филтър по тип; 12 типа (`lib/models/health_event.dart:6-17`), от които собственикът добавя 10 през лист (`health_screen.dart:311-324`) — двустъпков поток тип → форма (`:378-381`, ползван и от бързите действия на Начало). Полетата се показват според типа (`:487-516`: дозировка, честота, край, партида, полета за бяс). Запис → `POST/PATCH /dogs/{id}/health-events` (`lib/services/health_api.dart:34,78`; `app/modules/health/router.py:21,68`), после „най-добри усилия“ странични ефекти през `saveWithSideEffects` (`:646`; `lib/services/save_with_side_effects.dart:1-22`): локално напомняне и запис в системния календар при „дата на следващ…“ (`:701-708`), повтарящо се напомняне при медикамент (`:716-723`). Изтриване → `DELETE` + отмяна на напомнянето (`:81-82`).

**Хранене** (`lib/screens/dogs/nutrition_screen.dart`): профил — тип храна, марка, количество, хранения/ден, часове през time picker (`:47-50`), лакомства, добавки, алергии, бележки (`:33-40`) → `GET/PUT /dogs/{id}/nutrition` (`lib/services/nutrition_api.dart:10,16`; `app/modules/nutrition/router.py:20,33`); дневник на промените в диетата → `POST/GET …/nutrition/changes` (`nutrition_api.dart:30,41`; `router.py:47,61`); съвети за кученца до 1 г. с външни линкове (`:387-391`).

**ЕС паспорт** (`lib/screens/dogs/eu_pet_passport_section.dart:10-19`): само за държави в ЕС, превключвател „кратко / по официалния формат“ (`dog_detail_screen.dart:459-486`). Полета по Регламент 2026/705 + 2026/131; **живее само локално** (`PetPassportStore`, `lib/main.dart:132-133`), не минава през сървъра. Секции: собственик (телефон, подпис), описание, маркиране, произход (`:400-482`), ваксинации против бяс (четени от здравното досие, `:117-120`, `:486`), тестове за антитела (`:501`), ехинокок (`:510`), клиничен преглед (`:519`). Не е официален документ — формулировката е „по официалния ЕС формат“ (памет `project-my-beagle.md:557-563`).

**Родословие** (`lib/screens/dogs/pedigree_screen.dart`): `GET /dogs/{id}/pedigree?generations=3` (`lib/services/pedigree_api.dart:11`; `app/modules/dogs/router.py:80`), родители до 2 поколения нагоре (`:130-132`), редакция на родител през лист → `PATCH /dogs/{id}` (`:38-58`). Видимост за чужди кучета: публично разрешение или приятелство (`app/modules/dogs/service.py:139-148`).

**Изложби** (`lib/screens/dogs/shows_screen.dart`): събитие, дата, място, категория, класиране, награда (`:237-275`) → `POST/PATCH/DELETE /dogs/{id}/show-results` (`lib/services/shows_api.dart:26,54,70`; `app/modules/shows/router.py:20,47,64`).

**Съсобственост** (`lib/screens/dogs/co_ownership_screen.dart:13-16`): „Покажи QR за покана“ → `POST /dogs/{id}/invite` (`dogs_api.dart:52`; `dogs/router.py:193`) → QR (`:258`); другото устройство сканира в `JoinSharedDogScreen` (`lib/screens/dogs/join_shared_dog_screen.dart:12-14, 64`) → `POST /dogs/join` (`dogs_api.dart:59`; `router.py:208`) — същото куче, не копие. Списък съсобственици `GET /dogs/{id}/co-owners`, премахване/напускане `DELETE /dogs/{id}/co-owners/{user_id}` (`co_ownership_screen.dart:67-89`; `router.py:233,246`).

**Споделяне с ветеринар** (`dog_detail_screen.dart:200-240`): диалог „официален формат / кратко досие“. Кратко → `ShareScreen`: линк с живот 7 дни (`lib/screens/dogs/share_screen.dart:80`) → `POST /dogs/{id}/share-links` (`lib/services/share_api.dart:22`; `app/modules/sharing/router.py:30`), копиране/нативен share (`:252-262`), списък и оттегляне (`DELETE …/share-links/{link_id}`, `router.py:59`). Публична страница без вход: `GET /share/{token}` HTML на 9 езика и `/share/{token}/data` JSON (`sharing/router.py:74-87`; `sharing/schemas.py:20`). Официален формат → текст през нативния share sheet с бяс-ваксините от досието (`dog_detail_screen.dart:242-260`).

### 1.5 Начало

`lib/screens/home/home_screen.dart:34-38`: hero лента със снимката на активното куче (`:265-330`), `DogSwitcher` при >1 куче (`:376`), икона към Акаунт (`:380`). При отваряне: диалог „Какво ново“ веднъж на версия, иначе факт за бийгли (`:56-78`; `lib/services/release_notes_service.dart:5-9`, `lib/services/beagle_fact_service.dart:5-8`; фактите са на 9 от 18 езика — `lib/models/beagle_facts.dart`, проверено с `grep -oE "'[a-z]{2}': \[" | sort -u`, 19:47 UTC).

**Табло** (`:608-616`): джаджи и бързи действия, добавяни/махани/преподредими (`_EditWidgetsList`, `:905-930`; лист за добавяне `:1043-1048`). Типове (`lib/models/home_widget_type.dart:12-24`): джаджи — здраве, тегло, ваксинации, предстоящо, факт; бързи действия — „На разходка в парка“ (`sendWalkAnnouncement`, `home_screen.dart:106`), доклад за ветеринар (`ShareScreen`), добави тегло, здравен запис, снимка, Наблизо, Общност (`:702-743`). По подразбиране всички са включени (`home_widget_type.dart:67-73`). Редът се пази локално и се синхронизира с `GET/PUT /me/home-layout` (`home_screen.dart:667-682`; `lib/services/home_layout_api.dart:10,16`).

### 1.6 Календар

`lib/screens/calendar/calendar_tab_screen.dart:11-15` → `HealthCalendarScreen` за активното куче (`:92`), нов екземпляр при смяна на кучето. Месечен календар (`table_calendar`) с всички случили се (`occurredOn`) и насрочени (`dueOn`) здравни дати от всеки тип (`lib/screens/dogs/health_calendar_screen.dart:10-15, 97`), зареждане през `GET /dogs/{id}/health-events` (`:60`), тап на запис → Здраве (`:158`). Без куче — покана за добавяне; несинхронизирано куче — `NeedsSyncPrompt` (`calendar_tab_screen.dart:78-84`). Бекендът има и `GET …/health-events/upcoming` (`app/modules/health/router.py:48`), но клиентът не го вика (`lib/services/health_api.dart` няма такъв метод).

### 1.7 Общност (таб „Общност“)

`lib/screens/community/community_screen.dart:10-12, 67` делегира на `FriendsScreen` за активното куче. `lib/screens/dogs/friends_screen.dart:26-29`, секции (l10n ключове `:530-950`):

- **Запознати кучета** — `GET /dogs/{id}/friends` (`lib/services/social_api.dart:67`; `app/modules/social/router.py:87`); детайлен лист (`:316`) със снимка/възраст, премахване (`DELETE /dogs/{id}/friends/{friend}`; `:280-299`), меню „…“ за докладване/блокиране (`:362`), „вижда се на картата“ при активно споделяне (`:391-401`).
- **QR запознанство** — „Моят код“ → `POST /dogs/{id}/introduction-token` (`:34-38`; `router.py:38`; токен 10 мин), QR (`:950-962`); „Сканирай“ → `_ScannerScreen` (`:976-1000`) → `POST /dogs/{id}/introductions` (`:56-65`; `router.py:53`). Приятелството е двупосочно от едно сканиране.
- **Сподели приложението** — линк `/get-app`, който пренасочва по User-Agent към съответния магазин (`share_api.dart:56`; `app/modules/applink/router.py:20-33`).
- **„На разходка“** — `POST /dogs/{id}/walk-announcements` (`:128-140`; `router.py:171`) до собствениците на запознатите кучета и стартира споделяне на локация за 30 мин, ако няма активно (`:84-89`).
- **Живо споделяне на локация** — 5/10/15/30/60 мин (`lib/models/location_share_duration.dart:9-13`), разрешение през `geolocator` (`:163-183`) → `POST /dogs/{id}/location-share`, спиране `DELETE` (`social_api.dart:157,170`; `router.py:130,150`). Картата на приятел: `flutter_map` с CARTO тайлове върху OSM данни (`:421-449`).
- **Push:** бекендът праща през FCM, но без Firebase работи в dry-run (`app/core/push.py:1-7`); клиентът **не** регистрира device token — `registerDeviceToken` (`social_api.dart:88`) не се вика от нито един екран (`grep -rn registerDeviceToken lib/screens` → 0, 19:44 UTC), `firebase_messaging` не е в `pubspec.yaml`. Тоест обявите се записват, но не пристигат.
- **Кучета наблизо:** `GET /community/nearby-dogs` (`router.py:272`) и `listNearbyDogs` (`social_api.dart:142`) съществуват, но табът „Бийгъли“ е премахнат от Наблизо на 03.09.2026 (`git show 279f210`, `lib/screens/places/nearby_screen.dart:10-13`); няма UI консуматор.

### 1.8 Наблизо (места, срещи)

`lib/screens/places/nearby_screen.dart:10-13, 27, 51-62`: сегменти Места / Срещи; `DogSwitcher` само при Срещи (`:35-38`).

**Места** (`lib/screens/places/places_list_screen.dart:10-16`): две карти — Ветеринар и Хотел за кучета (`:60-87`) → `NearbyServiceListScreen` (`lib/screens/places/nearby_service_list_screen.dart:13-17`): разрешение за локация (`:79-87`), радиус със слайдер в km/mi (`:40-42, 119-129`), търсене по име с debounce (`:73-75`) → `GET /places?lat&lng&radius_km&search&category` (`lib/services/places_api.dart:31`; `app/modules/places/router.py:30`). Без звезди в списъка (OSM данните нямат реални рейтинги, `:15-17`). Детайл (`lib/screens/places/place_detail_screen.dart`): `GET /places/{id}`, отзиви `GET/PUT/DELETE /places/{id}/reviews` (`:30, 54, 64`; `router.py:52,64,80,93`), докладване на отзив с блокиране (`:71-79`). Общият справочник (карта, добавяне — `AddPlaceScreen`, `lib/screens/places/add_place_screen.dart:11`) е скрит от интерфейса от 03.09.2026 (`places_list_screen.dart:12-16`; `grep -rn "AddPlaceScreen()" lib` → 0), бекендът `POST /places` (`router.py:21`) остава.

**Срещи** (`lib/screens/places/meetups_tab.dart:13-15`): списък `GET /group-walks` (`lib/services/meetups_api.dart:28`; `social/router.py:223` — гео-филтърът е по избор, клиентът праща без координати, `meetups_tab.dart:35`), създаване през лист (съобщение, място/точка на карта, час) → `POST /dogs/{id}/group-walks` (`:74-84`; `router.py:208`), RSVP/отказ → `POST/DELETE /group-walks/{id}/rsvp` (`:45-62`; `router.py:244,259`), меню за докладване на разходка (`:238`).

### 1.9 Акаунт

Отваря се от иконата в AppBar на всеки таб (`dog_list_screen.dart:22-28`, `home_screen.dart:380`, `nearby_screen.dart:39-45`, `community_screen.dart:27-33`, `calendar_tab_screen.dart:33-43`) и от заключения екран (`subscription_required_screen.dart:25-27, 52-55`). `lib/screens/account/account_screen.dart:236-349`: имейл, име на собственика (`PATCH /auth/me`, `:249-270`), „Синхронизирай“ (`:272-275`), после:

- **Поверителност** (`privacy_screen.dart`): показване в общността (`:60-63`), точност на локацията none/country/city (`:68-79`, `lib/models/privacy_settings.dart:5-8`) + избор на точка на карта (`:86-98`, `lib/widgets/map_location_picker.dart`), публично родословие (`:106-109`) → `GET/PUT /me/privacy-settings` (`lib/services/privacy_api.dart:10,16`; `app/modules/privacy/router.py:14,22`).
- **Известия** (`notifications_screen.dart:58-77`): групови разходки, приятел в парка, новини за кучето → `GET/PUT /me/notification-preferences` (`social_api.dart:119,130`; `social/router.py:190,198`). (Без регистриран device token настройката няма ефект на практика — вж. 1.7.)
- **Напомняния** (`reminders_screen.dart:8-19`): 5 категории (разходка, хранене, ваксинация, грууминг, медикамент), изцяло локални, не се синхронизират (`lib/services/reminder_service.dart:6`).
- **Абонамент** (`billing_screen.dart:18-28`): `GET /me/billing` (`lib/services/billing_api.dart:13`; `app/modules/billing/router.py:24`); „Абонирай се“ → `POST /me/billing/subscribe` стартира 30-дневния пробен период от хъба без покупка (`:101-108`; `router.py:34`); „Активирай плащането“ в trialing/past_due → StoreKit/Play покупка (`:140-157`) → `POST /me/billing/verify-purchase` (`:205`; `router.py:62`); Restore (`:405-416`); линкове към условия и политика до цената (`:602-613`). Уебхуци от магазините: `POST /webhooks/appstore`, `/webhooks/google-play` (`app/modules/billing/webhooks_router.py:23,36`). Заключен екран (`subscription_required_screen.dart:28-35, 82-85`): текстът различава „никога не е имал абонамент“ от „изтекъл“.
- **Мерни единици** (`units_screen.dart:8-12`): метрични/имперски, локално.
- **Съобщи проблем** (`report_problem_screen.dart:11-14`): категория bug/incident/recommendation (`lib/models/ticket_ref.dart:5-8`), заглавие, описание, контакт → `POST /tickets` без вход, релей към Control Center, ограничение по IP (`lib/services/ticket_api.dart:20`; `app/modules/tickets/router.py:1-3, 18-27, 41-51`); `GET /tickets/config` показва дали хъбът е реално свързан (`:31-39`). При `ENABLE_DEBUG_LOG` — бутон за изпращане на локалния лог (`:147-163`).
- **Изход** с потвърждение (`:127-145`); **Изтриване на акаунта** с потвърждение + незадължителна анонимна анкета „защо“ (`:147-233`) → `DELETE /auth/me?reason=` (`auth_api.dart:111-112`; `identity/router.py:257-268`), после локалните кучета се изчистват (`:179`). Публична страница за изтриване: `GET /legal/delete-account` (`legal/router.py:85`).

### 1.10 Докладване и блокиране

Общ лист `lib/widgets/moderation_actions.dart:9-17`: причина + детайли + „също блокирай“ (`reportAndMaybeBlock`, `:31-64`) → `POST /reports` и `POST /users/{id}/block` (`lib/services/moderation_api.dart:50,62`; `app/modules/moderation/router.py:27,40`); блокиране без доклад (`confirmAndBlockUser`, `:81`); меню „…“ (`ModerationMenuButton`, `:125`) върху приятелски профил (`friends_screen.dart:362`), групова разходка (`meetups_tab.dart:238`), отзив (`place_detail_screen.dart:74`). Блокирането е двупосочно и филтрира приятели/срещи/отзиви на сървъра. Бекендът има `DELETE /users/{id}/block` и `GET /me/blocked-users` (`router.py:57,66`), но клиентът няма екран за отблокиране (`unblockUser`/`listBlockedUserIds` в `moderation_api.dart:65,69` не се викат от екран). Стаф преглед: `GET /moderation/reports`, `POST /moderation/reports/{id}/action` (`router.py:74,82`), само за стаф потребител.

### 1.11 Статус на функционалностите

| | Какво | Решение / източник |
|---|---|---|
| ✅ production | Всичко от 1.2–1.10 по-горе, с уговорките: push не пристига (без device token, dry-run), ЕС паспорт само локално, „кучета наблизо“ и общ справочник на места без UI | код 1.2.7+78; Play live, App Store в ревю (памет `project-my-beagle.md:566-567`) |
| 🔜 1.3.0 | **Облачно копие**: тих upsert при sync на локалното — незкачени кучета (`client_dog_id`), `heightVariety`, hero, снимки след първата, ЕС паспорт → `travel_documents` със съгласие преди първия PUT, единици/език, напомняния; екран „Облачно копие“; tombstones; ред „Още от Heppsu“ при `store_live` | `Business Partner/docs/PLAN-universal-dog-app.md:243-247` (F14) |
| 🔜 1.3.0 | **Ядро**: обвивка над `packages/dog_core` (невидимо за потребителя), flavor `test` | `PLAN-universal-dog-app.md:271-276` (F17), `:105` (Ф0.12) |
| 🔜 1.3.0 | **Дефекти**: `client_dog_id`, tombstones, `lib/widgets/dog_switcher.dart:63`, чуждо куче без насоки → банер; правни документи; `min_client_version` → 426 за 1.2.x | `PLAN-universal-dog-app.md:273-276` |
| 🟡 беклог, не е изрично в F17 | snapshot на името на родителя при изтриване; тестови акаунти за изтриване; UCrop portrait lock; edge-to-edge Android 15; цената от StoreKit; `catch (_)` без лог; факти на 9/18 езика | памет `project-my-beagle.md:572`; `docs/DOG-APPS-BRAINDUMP-2026-09-14.md:54` |
| ❌ отхвърлено | Нищо ново продуктово в Beagle Owner (риск 4.3) — всичко ново отива в Universal Dog App | Ив, `DOG-APPS-BRAINDUMP-2026-09-14.md:13` |
| ❌ отхвърлено | Таб „Бийгъли“ (карта с приблизителна локация на други кучета) | Ив, 03.09.2026, `git show 279f210`, `nearby_screen.dart:10-13` |
| ❌ отхвърлено | Per-feature paywall (Родословие/Изложби/официален паспорт/второ куче) → заменен с цялостно заключване | Ив, 01.09.2026, `subscription_required_screen.dart:13-16` |
| ❌ отхвърлено | Още 6–8 породни приложения (форк на клиента, flavors по порода) | Ив, 13.09.2026, `BRAINDUMP:14, :45` |
| ❌ отхвърлено | Чат, профили на собственици, търсене на хора, форуми | `BRAINDUMP:18`; `community_screen.dart:10-12` |
| ❌ отхвърлено | CMS/OTA таблици за съдържание; миграция чрез import с idempotency ключове | `BRAINDUMP:45-46` |
| ⏸ отложено (не за Beagle Owner) | Нативна Apple/Google карта (изисква API ключ + билинг); общ справочник на места с добавяне/карта | `friends_screen.dart:434-437`, `places_list_screen.dart:12-16`; при „нищо ново“ реално отива в Universal |

---

## 2. Клиентът (Flutter)

### Структура на директориите (`lib/`)

Проверено с: `find lib -type d` + `ls`, 19:40 UTC. 142 .dart файла, от които 20 в `lib/l10n/` (18 ARB + генерирани класове, ~46 000 реда генериран код, следен в git). Ръчно писан код: 22 840 реда в 122 файла.

| Директория | Файлове | Какво съдържа |
|---|---|---|
| `lib/` | 3 | `main.dart` (bootstrap, DI композиция), `app.dart` (`MyBeagleApp` → `MaterialApp`), `app_scope.dart` (`InheritedWidget` DI) |
| `lib/config/` | 2 | `build_config.dart` (гард срещу localhost в release), `splash_config.dart` |
| `lib/l10n/` | 20 | 18 × `app_<lang>.arb`, `l10n_extensions.dart` (`context.l10n`), генерирани `app_localizations*.dart` |
| `lib/models/` | 27 | immutable домейн модели: `dog.dart`, `eu_pet_passport.dart`, `health_event.dart`, `entitlement.dart`, `meetup.dart`, `place.dart`, `beagle_facts.dart`, `beagle_reference.dart`… |
| `lib/screens/` | 1 | `root_shell.dart` — гейтове (вход → условия → онбординг → абонамент) + 5-табов `IndexedStack` |
| `lib/screens/account/` | 11 | акаунт, `billing_screen.dart`, парола/имейл верификация, известия, поверителност, тикет („Докладвай проблем“), `subscription_required_screen.dart` |
| `lib/screens/dogs/` | 15 | досие: списък/добавяне/детайл, здраве, календар на здравето, тегло, хранене, родословие, изложби, ЕС паспорт, съсобственост, споделяне, приятели |
| `lib/screens/places/` | 6 | Наблизо: карта, места, добавяне на място, срещи (`meetups_tab.dart`) |
| `lib/screens/home/`, `calendar/`, `community/`, `onboarding/` | 1+1+1+2 | Начало (джаджи), Календар таб, Общност, онбординг за държава + приемане на условия |
| `lib/services/` | 40 | 17 `*_api.dart` клиента над `api_client.dart`; локални хранилища (`dog_store.dart`, `pet_passport_store.dart`, `home_layout_store.dart`); `auth_store.dart`, `entitlement_store.dart`, `sync_service.dart`, `purchase_service.dart`, `store_product_ids.dart`, `secure_store.dart`, `secure_http_client.dart`, `reminder_service.dart`, `debug_log.dart` |
| `lib/theme/` | 1 | `app_theme.dart` (цветове, разстояния, типография) |
| `lib/widgets/` | 11 | `language_switcher.dart`, `dog_switcher.dart`, `map_location_picker.dart`, `needs_sync_prompt.dart`, `moderation_actions.dart`, `tab_switcher_scope.dart`, `whats_new_dialog.dart`… |

`README.md:29-37` описва структурата с `l10n/strings.dart`, който не съществува — секцията е остаряла (проверено с `ls lib/l10n/strings.dart`, 19:46 UTC).

### Пакети и версии

`pubspec.yaml:20` → `version: 1.2.7+78`; `environment.sdk: ^3.12.2`; `pubspec.lock` иска Flutter ≥3.44.0. Локалният инструмент: Flutter 3.47.2 stable / Dart 3.13.2 (проверено с `flutter --version`, 19:41 UTC).

Резолирани версии (проверено с `awk` върху `pubspec.lock`, 19:41 UTC):

| Пакет | pubspec | lock |
|---|---|---|
| `in_app_purchase` | ^3.3.0 | 3.3.0 (+ `in_app_purchase_storekit` 0.4.11+1, `in_app_purchase_android` 0.5.2) |
| `geolocator` | ^14.0.2 | 14.0.3 (android 5.0.3, apple 2.3.14) |
| `flutter_map` / `latlong2` | ^8.3.1 / ^0.10.1 | 8.3.1 / 0.10.1 |
| `flutter_secure_storage` | ^10.3.1 | 10.3.1 |
| `flutter_local_notifications` / `timezone` | ^22.3.0 / ^0.11.1 | 22.3.0 / 0.11.1 |
| `intl` + `flutter_localizations` | ^0.20.2 | 0.20.3 |
| `http` / `http_parser` / `crypto` | ^1.6.0 / ^4.1.2 / ^3.0.7 | 1.6.0 / 4.1.2 / 3.0.7 |
| `shared_preferences` | ^2.5.5 | 2.5.5 |
| `image_picker` / `image_cropper` | ^1.2.3 / ^12.2.1 | 1.2.3 / 12.2.1 |
| `mobile_scanner` / `qr_flutter` | ^7.4.0 / ^4.1.0 | 7.4.0 / 4.1.0 |
| `share_plus` / `url_launcher` / `package_info_plus` | ^13.3.0 / ^6.3.2 / ^10.2.1 | 13.3.0 / 6.3.2 / 10.2.1 |
| `table_calendar` / `add_2_calendar` | ^3.2.1 / ^3.1.1 | 3.2.1 / 3.1.1 |
| `uuid` / `path_provider` | ^4.6.0 / ^2.1.6 | 4.6.0 / 2.1.6 |
| dev: `flutter_lints` 6.0.0, `flutter_launcher_icons` 0.14.4, `flutter_secure_storage_platform_interface` ^2.0.3 | | |

Няма `firebase_*`, `provider`, `riverpod`, `bloc`, `go_router`, `integration_test` (проверено с grep в `pubspec.yaml`, 19:41 UTC). Платформи: Android `applicationId com.heppsu.myBeagle` (`android/app/build.gradle.kts:40`), iOS deployment target 15.0, само iPhone (`TARGETED_DEVICE_FAMILY = "1"`, `ios/Runner.xcodeproj/project.pbxproj:427-432`).

### State management

Само Flutter stdlib, без външен пакет (проверено с grep, 19:42 UTC):

- **DI**: `AppScope extends InheritedWidget` (`lib/app_scope.dart:31`) с 25 задължителни полета и статични `xxxOf(context)` достъпи (`app_scope.dart:94-133`). `updateShouldNotify` сравнява само `dogs`, `auth`, `sync` (`app_scope.dart:136-139`). Композицията е ръчна в `main.dart:134-186` (`_bootstrap`), подадена на `MyBeagleApp` (`app.dart:34`).
- **Състояние**: 8 класа `extends ChangeNotifier` — `AuthStore` (`auth_store.dart:11`), `DogStore` (`dog_store.dart:12`), `EntitlementStore` (`entitlement_store.dart:16`), `HomeLayoutStore` (`home_layout_store.dart:13`), `LocaleController` (`locale_controller.dart:16`), `PetPassportStore` (`pet_passport_store.dart:12`), `ReminderPreferences` (`reminder_preferences.dart:67`), `UnitsController` (`units_controller.dart:36`).
- **Слушане**: 27 употреби на `ListenableBuilder`/`AnimatedBuilder`; напр. `app.dart:118` (локал), `root_shell.dart:34-35` (`Listenable.merge([auth, entitlement])`). Останалото е `StatefulWidget` + `setState` и `FutureBuilder`.
- **Bootstrap**: `main.dart:56-76` пуска `_LoadingScreen` веднага и `_bootstrap()` асинхронно; `runZonedGuarded` + `FlutterError.onError` + `PlatformDispatcher.onError` към `DebugLog` (`main.dart:120-132`). В release без `--dart-define=API_BASE_URL` хвърля `StateError` (`main.dart:61-66`, `build_config.dart:19-22`).

### Навигация

Без рутер — 105 императивни `Navigator.push`/`MaterialPageRoute` (проверено с grep, 19:42 UTC). Корен: `RootShell` (`root_shell.dart:27`) е верига от гейтове: `!auth.isLoggedIn → _AuthGate` (:37), `!auth.termsAccepted → TermsAcceptanceScreen` (:43), `auth.country == null → OnboardingScreen` (:48), `!entitlement.isPlus → SubscriptionRequiredScreen` (:54), иначе `_TabShell` (:55). `_TabShell` е `IndexedStack` с 5 таба — Начало, Досие, Календар, Наблизо, Общност (`root_shell.dart:148-154`, `NavigationBar` :163-193); Календарът се презарежда чрез `_calendarRefreshToken` при активиране (:118, :157). `TabSwitcherScope` (`widgets/tab_switcher_scope.dart`) позволява превключване на таб отвътре. `didChangeDependencies` пуска `syncIfLocalStoreIsEmpty()` еднократно (:123-136).

### Локална база и sync модел

Няма SQLite/Hive — JSON файлове + SharedPreferences + Keychain:

| Какво | Къде | Синхронизира ли се |
|---|---|---|
| Кучета (`List<Dog>`) | `dogs.json` в documents dir (`dog_store.dart:22`), запис през tmp+rename (:180-192) | Да — `SyncService` |
| Снимки | `dog_images/<dogId>-<μs>.<ext>`, относителен път (`dog_store.dart:135-172`); `resolvePath` толерира стари абсолютни (:177) | Качване/сваляне при sync (`sync_service.dart:129-142`) |
| Избрано куче | само в паметта (`dog_store.dart:39-59`) | Не |
| ЕС паспорт | `pet_passports.json` (`pet_passport_store.dart:22`) | **Не** — изрично локален (:8-11) |
| Auth токен, локал | Keychain/Keystore през `SecureStore` (`auth_store.dart:12-13`, `locale_controller.dart:17`); iOS accessibility `first_unlock_this_device` (`secure_store.dart:20-26`), delete-преди-write (:43-46) | — |
| Ред на джаджите на Начало | SharedPreferences + `/me/home-layout` (`home_layout_store.dart:6-12, :39`) | Да |
| Напомняния/единици/„какво ново“ | SharedPreferences (`reminder_preferences.dart:79`, `units_controller.dart:49`, `release_notes_service.dart:13`) | Не |
| Здравни събития, тегло, родословие, изложби, места, срещи, приятели | **само сървър** — `health_api.dart:9`, `pedigree_api.dart`, `shows_api.dart`… (без локален кеш) | — |

**`SyncService.sync()`** (`sync_service.dart:33-122`): един `GET /dogs`, после за всяко локално куче — `serverId == null` или осиротял (сървърът не го знае) → `POST /dogs` (:62-76); сървърът по-нов от `serverUpdatedAt` → издърпва (съсобственик, :80-101); иначе `PATCH` (:103-105). Накрая сваля непознатите сървърни кучета с нов локален UUID (:108-119). Политика: локалното печели освен при по-нов `updated_at` (:20-25).

**Известни слабости (от кода, непроверено на живо):**
- *Дубликат при повторен POST*: `dogs_api.dart:22-25` праща `POST /dogs` без идемпотентен ключ/локално id в тялото (`_toApiBody`, :96-113). Ако отговорът се изгуби след като сървърът е записал, `serverId` остава `null` и следващият sync създава второ куче. Същото „лекуване на сираче“ (`sync_service.dart:47-64`) съзнателно създава ново копие при смяна на среда/отменена съсобственост.
- *Няма tombstones*: изтриване е `DELETE` + локално `delete()` в момента (`dog_detail_screen.dart:320-358`); при мрежова грешка кучето се трие само локално и се връща при следващ sync (:344-356, документиран компромис). Изтрито от друго устройство куче не се маха локално — `sync()` няма клон „сървърът вече не го има → изтрий“ (само „осиротяло → качи наново“).
- Sync не е автоматичен при всяка промяна — вика се от логин формата, `_TabShell` при празно хранилище и `NeedsSyncPrompt`.

### Локализация (l10n)

- `l10n.yaml`: шаблон `app_bg.arb`, `nullable-getter: false`, генерирана `AppLocalizations`. 18 ARB × 705 ключа, всички с еднакъв брой (проверено с `grep -c` по файл, 19:43 UTC): bg, cs, da, de, el, en, es, fr, hu, it, ja, ko, nb, nl, pl, pt, ro, sv. Достъп през `context.l10n` (`lib/l10n/l10n_extensions.dart`). `i18n-drafts/` пази 8 чернови (вкл. `tr`, `zh`, които не са в приложението).
- `test/localization_completeness_test.dart`: (1) статично сканира `lib/screens` и `lib/widgets` за литерали в `Text(`, `hintText:`, `labelText:`, `helperText:`, `tooltip:`, `semanticLabel:` (:84-86), прескача редове с `context.l10n` (:91), allowlist за автоними (:26-53); (2) сравнява **набора от ключове** между ARB файловете (:125-146).
- **Къде НЕ се проверява**: (а) списъкът в теста е само 9 езика — `['bg','en','pt','de','es','fr','it','hu','el']` (:134); cs/da/ja/ko/nb/nl/pl/ro/sv не се сравняват по ключове (codegen-ът с `nullable-getter: false` би паднал при липсващ ключ, но не при празен/непреведен); (б) нищо не проверява **съдържанието** — празни стойности или копирани от английски; евристика (стойност == en, >3 букви; python върху ARB, 19:46 UTC) дава 2–36 съвпадения на език (fr 36, da 26, de 23, nl 20), преобладаващо когнати като „Normal“/„Email“, 0 празни; (в) низове в `lib/services` (напр. SnackBar текстове от API съобщения) и `SnackBar(content: Text(e.message))` (`dog_detail_screen.dart:337`) са извън обхвата; (г) allowlist-ът за `language_switcher.dart` е мъртъв — файлът вече ползва `Text(name)` от променлива (`language_switcher.dart:77`).
- **Вероятен дефект (от кода, непроверено на живо)**: `main.dart:112` инициализира intl данни само за 9 локала; `health_calendar_screen.dart:103` подава `Localizations.localeOf(context).languageCode` на `TableCalendar`, който вика `DateFormat.yMMMM(locale)` (`table_calendar-3.2.1/lib/src/widgets/calendar_header.dart:43`); за неинициализиран локал `intl` хвърля `ArgumentError('Invalid locale')` (`intl-0.20.3/lib/src/intl_helpers.dart:246`). Календарът на 9-те нови езика (cs, da, ja, ko, nb, nl, pl, ro, sv) най-вероятно гърми. `test/health_calendar_screen_test.dart` тества само `Locale('bg')` (:112, :126).
- Други езиково зависими места: `beagle_reference.dart` (съвети за кученце, 18 езика, покрити от `puppy_tips_localized_test.dart:17-27`), `beagle_facts.dart`, `country_names.dart`; iOS permission низове — `ios_permission_strings_test.dart` (след отказ на Apple по Guideline 4, 10.09.2026).

### Push и известия

- **Няма Firebase/APNs/FCM** — без `google-services.json`/`GoogleService-Info.plist`, без firebase пакети (проверено с grep + ls, 19:44 UTC). `reminder_service.dart:6-7` изрично: „нарочно локални, не push от сървъра“.
- Локални напомняния: `flutter_local_notifications` + `timezone`; `ReminderService.init()` иска разрешения на iOS/Android (`reminder_service.dart:14-26`); id = `healthEventId.hashCode & 0x7fffffff` (:31-32); насрочва 9:00 местно време по текущия offset без DST преизчисляване (:37-42), `zonedSchedule` (:55).
- `SocialApi.registerDeviceToken()` → `POST /me/device-tokens` съществува (`social_api.dart:88-98`), но **не се вика никъде в `lib/`** — само от `test/social_api_test.dart:90-101`. Мъртъв клиентски път към бекенд endpoint.

### IAP интеграция

- `purchase_service.dart:17` — тънка обвивка над `InAppPurchase.instance`, мързеливо инстанцирана (:20-27); `buy()` ползва `buyNonConsumable` с `applicationUserName: userId` (iOS `appAccountToken`, Android `obfuscatedAccountId`, :46-49); `completePurchase` само при `pendingCompletePurchase` (:51-54); `openManageSubscriptions` към системните страници (:61-68).
- **StoreKit 2**: не се вика `enableStoreKit2()`/`enableStoreKit1()` (grep, 19:44 UTC) — `in_app_purchase_storekit` 0.4.0+ прави StoreKit 2 подразбиране (CHANGELOG 0.4.0), а `serverVerificationData` за SK2 е `jwsRepresentation` (CHANGELOG 0.4.2; `sk2_transaction_wrapper.dart:72`). Клиентът праща точно това поле (`billing_screen.dart:206`, `billing_api.dart:31-33`).
- **Ред на проверка** (`billing_screen.dart:163-219`): `purchaseStream` → `purchased`/`restored` → `_verifyAndComplete` → `POST /me/billing/verify-purchase` с `platform`, `product_id` (обратно мапнат към код на план), `verification_data` (`billing_api.dart:34-50`) → **`completePurchase` само след успешен отговор** (:214-215); при `ApiException` транзакцията остава незавършена (:216-218). `error`/`canceled` се завършват веднага (:171-181). Без токен — завършва без проверка (:196-199).
- `store_product_ids.dart:20-22`: изрична карта `plus_monthly → com.heppsu.myBeagle.plus.monthly` за iOS; Android ползва кода на плана директно (:26-31); обратна посока `planCodeFromStoreProductId` (:36-41).
- Таймаут 15 s за `isAvailable()` и `queryProduct()` (`billing_screen.dart:32, :140-150`); `restorePurchases()` при отваряне на екрана (:85-90) — от него идва `_storeAlreadyOwns` (:54-58). Два пътя: „Абонирай се“ = само `subscribe(planCode)` в хъба (пробен период без покупка), „Активирай плащането“ = магазин (:22-28).
- `EntitlementStore` е fail-open: `isPlus == true` при `null`/неконфигуриран/мрежова грешка (`entitlement_store.dart:27-31, :54-56`); слуша `AuthStore` (:35-44).

### Версиониране

- `pubspec.yaml:20`: `1.2.7+78`. SemVer от 06.09.2026 (`4bd3a17`, „PATCH расте при фиксиран дефект“). Пълна история: `git log --date=short --format='%h %ad %s' -- pubspec.yaml` (79 комита от `aa812b5`, 09.08.2026; общо 219 комита в репото; проверено 19:44 UTC). Тагове: само `v1.0.0` и `tested/ed90418`.
- Ключови точки: 1.0.0+21–26 говореха с localhost (`build_release.sh:3-5`); +31/+32 (29.08) splash; +33–+57 тестови билдове (31.08–04.09); +58 „първи production-кандидат“ (04.09); 1.0.1+64 → 1.0.3+66 (06.09); 1.1.0+67 име на собственика; 1.2.0+68–70 (07.09) тегло/модерация/име на план; 1.2.1–1.2.4 (+71–74, 07.09) заключен екран, езици на грешки, rate-limit текст; 1.2.5+75 (08.09) правилен App Store product id; 1.2.6+76/+77 (10.09) iOS permission низове на езика на приложението; 1.2.7+78 (10.09).
- Артефакти в `releases/` (gitignored): `MyBeagle-<version>.aab/.ipa` от 1.2.2+72 до 1.2.7+78 (проверено с `ls`, 19:45 UTC).

### Тестове

Проверено с: `flutter test --reporter compact`, 19:43 UTC — **336 минаха, 0 не минаха, 1 мин 45 с**. Разбивка (grep по `test(`/`testWidgets(`, 19:42 UTC): 263 unit `test(` + 73 widget `testWidgets(` = 336; 82 файла в `test/` + 3 в `test/fakes/` (`mock_backend.dart` — 198-редова in-memory имитация на my-beagle-api; `minimal_scope.dart` — `AppScope` за един екран; `in_memory_secure_store.dart`). 30 файла с widget тестове, 52 само unit.

- Golden: 0 (`matchesGoldenFile` няма). Integration: няма `integration_test/`, няма пакет.
- Извън Dart кода тестовете покриват и платформената конфигурация: `android_manifest_test.dart` (UCropActivity), `android_splash_screen_test.dart`, `ios_permission_strings_test.dart`, `localization_completeness_test.dart`, `floating_action_button_hero_tags_test.dart`.
- **Няма CI**: няма `.github/workflows`, `.gitlab-ci.yml`, `codemagic.yaml` (проверено с `ls`, 19:45 UTC). `flutter analyze`/`flutter test` са само в README.

### Device матрица за скрийншоти и store assets

`store/` (28 файла в git; проверено с `find` + `sips`, 19:45 UTC):

| Път | Брой | Резолюция | Език |
|---|---|---|---|
| `store/screenshots/ios/en/01-05` | 5 PNG | 1284×2778 (6.7" клас) | en |
| `store/screenshots/ios/bg/01-05` | 5 PNG | 1206×2622 (6.3" клас) | bg |
| `store/screenshots/ios/pt/01-05` | 5 PNG | 1206×2622 | pt |
| `store/screenshots/android/en/01-08` | 8 JPG | 831×1801 (нестандартна, свалена от устройство) | en |

Екрани: home, dossier/profile, calendar, community, map/co-ownership (iOS); splash, home, dossier-menu, nearby, profile, languages, community, calendar (Android). Различни устройства за en и bg/pt на iOS — не е една матрица; няма скрипт за автоматично снимане (изискването „минимум 4 екрана автоматично“ и „5 резолюции“ не е реализирано в репото). `store/play/CHECKLIST.md:127-129` — скрийншоти за другите 17 езика остават отворени.

Останалото в `store/`: `play/listing.md` (кратко/пълно описание за 18 локала, обновено 04.09.2026), `play/CHECKLIST.md` (статус на Play Console; съдържа името на service account-а — не се пренася тук), `play/feature-graphic.png`, `play/icon-512.png`, `apple-review-reply-2026-09-07.md` и `apple-review-reply-2026-09-10.md` (вторият още не е комитнат — `git status`, 19:46 UTC). Отделно `Andorid screenshots/` (8 Viber JPG от 06.09.2026, сурови) и `UI/beagle_owner_splash_schreen.png`.

### `scripts/build_release.sh`

Единственият скрипт в `scripts/`. `set -euo pipefail`, `cd` в корена (:16-17). Аргументи: платформа `android|ios|both`, среда `prod|test` (по подразбиране prod, :19-20). Средата задава `API_BASE_URL` — prod `https://mybeagle.heppsu.com/api/v1`, test `https://test.mybeagle.heppsu.com/api/v1` (:22-26). Взима версията от `pubspec.yaml` (:28), `flutter build appbundle`/`flutter build ipa --release --dart-define=API_BASE_URL=…` (:40, :47) и копира в `releases/MyBeagle-<version>[-test].aab|.ipa` (:41, :49) — тестовият суфикс пази prod артефакта от презапис (:31-36). Android и iOS последователно, не паралелно (:12-14). **Не подава `PINNED_CERT_SHA256`** — `secure_http_client.dart:20, :28` при празна стойност връща обикновен `http.Client()` без pinning (от кода). Не пуска тестове, не тагва, не качва в стора.

---

## 3. Бекендът (FastAPI)

### 3.1 Общ вид и стек

- Репо: `/Users/iv/Documents/Development/MyBeagleApi`, клон `dev`, HEAD `577bc45` (проверено с: `git -C … rev-parse --short HEAD; git branch --show-current`, 19:45 UTC). Последен комит 11.09.2026.
- Стек: Python 3.14 · FastAPI · SQLAlchemy 2.0 (sync) · Pydantic v2 · Alembic · PostgreSQL (prod) / SQLite (dev) — `README.md:9-11`; закрепени версии в `requirements.txt` (fastapi 0.139.2, sqlalchemy 2.0.51, alembic 1.18.5, pyjwt 2.13.0, bcrypt 5.0.0, app-store-server-library 3.1.2, google-api-python-client 2.187.0, markdown 3.10.3).
- Входна точка `app/main.py:20-42`: `create_app()` — CORS middleware (`app/main.py:27-33`), `Base.metadata.create_all` само при `AUTO_CREATE_TABLES` (`app/main.py:36-37`), рутери (`app/main.py:79-125`), `GET /api/v1/health` със `SELECT 1` срещу базата (`app/main.py:66-75`), статичен mount на снимките под `PHOTOS_URL_PREFIX` без авторизация — обфускация само чрез uuid4 име (`app/main.py:45-49`, `app/core/config.py:146-154`).
- Обем: 17 директории под `app/modules`, ~9 060 реда Python в `app/` (проверено с: `wc -l app/modules/*/*.py app/core/*.py …`, 19:45 UTC).
- Няма CI конфигурация в репото (няма `.github/`); статичният анализ е само `ruff.toml` (F, E9, W, B, UP, SIM, I). Няма bandit, няма pip-audit — нито в репото, нито в `infra/deploy.sh` (проверено с: `grep -rn "bandit\|pip-audit" .` без `.venv`, 19:44 UTC).

### 3.2 Модули и отговорности (`app/modules/*`)

| Модул | Отговорност | Ключови файлове |
|---|---|---|
| `identity` | акаунт, регистрация, имейл код, вход, сесии, password reset, изтриване, home layout, приемане на условия | `models.py`, `service.py`, `verification.py`, `password_reset.py`, `mailer.py`, `router.py` |
| `security` | само моделът `AuthThrottleEvent` (rate limit хранилище) | `models.py`; логиката е в `app/core/rate_limit.py` |
| `dogs` | CRUD на кучета, снимка, родословие (sire/dam до 6 поколения), съсобственост | `service.py`, `co_ownership.py`, `router.py` |
| `health` | здравни събития на куче (12 типа), `/upcoming` | `models.py:22-34` |
| `nutrition` | хранителен профил (1:1 с куче) + дневник на промените | `models.py:16-47` |
| `shows` | резултати от изложби | `models.py:16-29` |
| `sharing` | временни линкове за ветеринар (emergency/health/full), публичен HTML/JSON изглед | `service.py`, `html_view.py`, `router.py` |
| `social` | запознаване с QR токен, приятелства, живо споделяне на локация, device tokens, известия, групови разходки, „кучета наблизо" | `service.py` (~720 реда) |
| `places` | места (хотел, ресторант, парк, ветеринар…), рецензии, OSM импорт (`scripts/import_osm_places.py`, `infra/osm_import_cron.sh`) | `service.py`, `router.py` |
| `privacy` | настройки за видимост и квантизирана точка | `models.py`, `service.py` |
| `moderation` | доклади, блокиране, staff действия, audit log | `service.py`, `router.py` |
| `billing` | entitlement през Heppsu Subscriptions, проверка на покупки, webhooks | `service.py`, `client.py`, `appstore_*.py`, `googleplay_verification.py`, `webhooks_router.py` |
| `legal` | публични правни страници от Markdown | `router.py`, `docs/` |
| `tickets` | „Съобщи проблем" → Control Center | `client.py`, `service.py`, `router.py` |
| `applink` | `/get-app` → Play/App Store по User-Agent | `router.py:20-32` |
| `content` | **не съществува** — няма `app/modules/content`; няма и следа от `breed_key`/`app_key` в `app/` или `alembic/` (проверено с: `grep -rln "breed_key\|app_key" app alembic`, 19:45 UTC). Мулти-породната архитектура е само документ: `docs/ARCHITECTURE-multi-breed.md` (10.09.2026). |

### 3.3 Схема на базата (от `models.py`; регистър в `app/db/registry.py:2-12`)

Общи миксини: `UUIDMixin` (uuid4 PK), `TimestampMixin` (`created_at`/`updated_at` от БД) — `app/db/base.py:15-30`. SQLite включва `PRAGMA foreign_keys=ON` и Unicode `lower/upper` при connect (`app/db/session.py:19-45`).

| Таблица · модел | Колони от значение | FK |
|---|---|---|
| `users` · `User` (`identity/models.py:20-79`) | `email` (unique), `hashed_password`, `is_active`, `home_widget_order` (JSON), `email_verified_at`, `full_name`, `country` (ISO-2), `terms_accepted_at`, `is_staff` (без API за вдигане) | — |
| `user_sessions` · `UserSession` (`:82-102`) | PK `jti` (String 32) — същият в JWT | `user_id → users CASCADE` |
| `email_verifications` (`:105-123`) | `token_hash` (unique), `expires_at`, `consumed_at`, `attempts` | `user_id → users` (**без** ondelete; трие се ръчно в `delete_account`) |
| `password_reset_codes` (`:126-141`) | огледално на горното | `user_id → users CASCADE` |
| `account_deletion_feedback` (`:152-164`) | само `reason` (enum от 5) — нарочно без user_id/email | — |
| `auth_throttle_events` · `AuthThrottleEvent` (`security/models.py:10-46`) | `scope`, `client_ip`, `subject`, `occurred_at` (float unix), `cleared_at`; 3 композитни индекса | — (нарочно без FK) |
| `dogs` · `Dog` (`dogs/models.py:27-67`) | `name`, `sex` (enum), `breed` (default „Бийгъл"), `date_of_birth`, `owner_name`, `previous_owners` (JSON), `microchip_number`, `notes`, `blood_type`, `sire_name`/`dam_name`, `photo_filename` | `owner_id → users CASCADE`; `sire_id`/`dam_id → dogs SET NULL` |
| `dog_co_owners` (`:70-109`) | `revoked_at` (NULL = активен), UNIQUE(dog_id,user_id) | `dog_id → dogs CASCADE`, `user_id → users CASCADE`, `revoked_by_user_id → users SET NULL` |
| `dog_co_owner_invites` (`:112-135`) | `code_hash`, `expires_at`, `consumed_at` | `dog_id`, `created_by` CASCADE; `consumed_by` SET NULL |
| `health_events` (`health/models.py:37-86`) | `type` (12 стойности), `title`, `occurred_on`, `due_on`, `dosage`, `result`, `weight_kg`, `bcs`, `provider`, `frequency`, `ends_on`, `batch_number`, `manufacturer`, `is_rabies_vaccine` | `dog_id → dogs CASCADE` |
| `nutrition_profiles` (unique dog_id), `diet_change_log_entries` | свободен текст | `dog_id CASCADE` |
| `show_results` | `event_name`, `event_date`, `placement`, `award` | `dog_id CASCADE` |
| `share_links` (`sharing/models.py:33-47`) | `token` (unique), `scope` (emergency/health/full), `language`, `expires_at`, `revoked_at` | `dog_id CASCADE` |
| `privacy_settings` (`privacy/models.py:27-57`) | `show_dogs_in_community` (default False), `location_precision` (none/country/city, default none), `latitude`/`longitude` (закръглени при запис), `share_pedigree_publicly` (default False) | `user_id → users CASCADE`, unique |
| `introduction_tokens`, `friendships` (dog_a/dog_b), `location_shares` (unique dog_id, **сурови** координати, `expires_at`), `device_tokens` (`token` unique, `platform`), `walk_announcement_logs`, `notification_preferences` (`group_walks`, `friend_in_park`, `dog_updates`), `group_walk_events` (`location`, `message`, `scheduled_at`, `is_hidden`, `latitude`/`longitude` на организатора), `group_walk_attendees` | `social/models.py:27-201` | всички към `dogs`/`users` CASCADE |
| `places` (`places/models.py:53-110`) | `name`, `category` (enum), `address`, `phone`, `opening_hours`, `emergency_care`, `latitude`/`longitude`, `source` (user/osm), `external_id`, `is_hidden` | `added_by_user_id → users SET NULL` |
| `place_reviews` (`:116-134`) | `rating`, `comment`, `is_hidden` | `place_id`, `user_id` CASCADE |
| `reports` (`moderation/models.py:56-84`) | `target_type` (place/place_review/user/group_walk), `target_id` (без FK), `reason`, `details`, `status` (open/actioned/dismissed), `resolved_at` | `reporter_user_id CASCADE`, `resolved_by_user_id SET NULL` |
| `user_blocks` (`:90-107`) | `blocker_user_id`, `blocked_user_id` | и двете → users CASCADE |
| `moderation_audit_logs` (`:109-130`) | `action`, `target_type`, `target_id`, `reason` | `actor_user_id SET NULL` |

### 3.4 Миграции (`alembic/versions`, 32 ревизии, една глава `a3f61d0be274`)

Проверено с: скрипт по `revision`/`down_revision` през `.venv/bin/python`, 19:45 UTC.

1. `8111dbada249` начална схема: users, dogs
2. `207d90b497ca` родословие: sire/dam
3. `de1c0cc8b040` blood_type, health_events
4. `f0cfda1ced36` share_links за ветеринар
5. `37eeaf8e927b` хранене, изложби, privacy
6. `e50d9ac03cfe` запознаване на кучета, известия за разходка
7. `97d5ca0ae57b` notification_preferences, групова разходка
8. `2125482a7e35` места и рейтинги
9. `01b7ea2aac83` групови срещи с дата и RSVP + координати на места
10. `b26e27811fb3` координати в privacy_settings
11. `a969c32dfb17` потвърждение на имейл
12. `c4b1a6e2f7d3` език на споделения линк
13. `a30d2540f26f` provider/frequency/ends_on на здравен запис
14. `8176c8478f9f` BCS на тегло
15. `2f57ea45b19c` location_shares
16. `6d5efc831862` снимка на куче + home_widget_order
17. `958647ffe382` 6-цифрен код вместо линк, забравена парола
18. `c7e21a94f508` auth_throttle_events
19. `60269006bf33` country на собственика
20. `d5471760e44b` съсобственост: покана, съсобственици
21. `0b643d6ad8fb` места: phone, source, external_id
22. `888dc289b67a` opening_hours
23. `0cd57deadbfd` emergency_care
24. `006a796c280b` phone по-широко
25. `bf87cf3a6ce7` еднократно закръгляне на записани сурови координати
26. `4a4081385179` отменяем съсобственик (revoked_at)
27. `4c85e9d6c4e2` terms_accepted_at, reports, user_blocks, is_hidden
28. `25eaa8a32188` account_deletion_feedback
29. `3b5ced03d8bc` manufacturer, is_rabies_vaccine
30. `6f44af6f0a67` user_sessions (лимит на сесии)
31. `ddecabeb2910` full_name в users
32. `a3f61d0be274` докладвана разходка се скрива + носи точката на организатора

`tests/test_migrations_schema.py` пуска `alembic upgrade head` + `alembic check` срещу празна база при всеки run (`README.md:32-35`). В production схемата идва само от `migrate` услугата в `infra/docker-compose.yml:36`.

### 3.5 API повърхност (всичко под `/api/v1`, освен където е отбелязано; `app/main.py:79-125`)

**Без префикс (публични):** `GET /get-app` (`applink/router.py:31`); `GET /legal/privacy[/{lang}]`, `GET /legal/terms[/{lang}]`, `GET /legal/delete-account` (`legal/router.py:69-89`).

**identity** (`identity/router.py`): `POST /auth/register` (:99), `POST /auth/verify-email` (:136), `POST /auth/resend-verification` (:156), `POST /auth/password-reset/request` (:177), `POST /auth/password-reset/confirm` (:199), `POST /auth/login` (:223), `GET /auth/me` (:242), `PATCH /auth/me` (:247), `DELETE /auth/me?reason=` (:257), `POST /me/accept-terms` (:271), `GET/PUT /me/home-layout` (:279, :284). **Няма `POST /auth/logout`** (проверено с: `grep -rn logout app`, 19:45 UTC).

**dogs** (`dogs/router.py`): `POST /dogs` (:44), `GET /dogs` (:59), `GET /dogs/{id}` (:67), `GET /dogs/{id}/pedigree?generations=1..6` (:80), `PATCH /dogs/{id}` (:95), `DELETE /dogs/{id}` (:126), `PUT/DELETE /dogs/{id}/photo` (:142, :178; JPEG/PNG/WEBP, ≤8 MB), `POST /dogs/{id}/invite` (:193), `POST /dogs/join` (:208), `GET /dogs/{id}/co-owners` (:233), `DELETE /dogs/{id}/co-owners/{user_id}` (:246).

**health** (`/dogs/{dog_id}/health-events`): `POST`, `GET`, `GET /upcoming`, `PATCH /{event_id}`, `DELETE /{event_id}` (`health/router.py:21-85`).
**nutrition** (`/dogs/{dog_id}/nutrition`): `GET`, `PUT`, `POST /changes`, `GET /changes` (`nutrition/router.py:20-61`).
**shows** (`/dogs/{dog_id}/show-results`): `POST`, `GET`, `PATCH /{id}`, `DELETE /{id}` (`shows/router.py:20-64`).
**sharing**: `POST/GET /dogs/{dog_id}/share-links`, `DELETE …/{link_id}` (`sharing/router.py:30-59`); публични без auth `GET /share/{token}/data` (JSON) и `GET /share/{token}` (HTML) (`:74-86`).
**privacy**: `GET/PUT /me/privacy-settings` (`privacy/router.py:14-22`).
**social** (`social/router.py`): `POST /dogs/{id}/introduction-token` (:38), `POST /dogs/{id}/introductions` (:53), `GET /dogs/{id}/friends` (:87), `DELETE /dogs/{id}/friends/{friend}` (:117), `POST/DELETE /dogs/{id}/location-share` (:130, :150), `POST /me/device-tokens` (:162), `POST /dogs/{id}/walk-announcements` (:171), `GET/PUT /me/notification-preferences` (:190, :198), `POST /dogs/{id}/group-walks` (:208), `GET /group-walks?lat&lng&radius_km` (:223), `POST/DELETE /group-walks/{event}/rsvp` (:244, :259), `GET /community/nearby-dogs` (:272).
**places** (`places/router.py`): `POST /places` (:21), `GET /places?search&category&lat&lng&radius_km&emergency_care` (:30), `GET /places/{id}` (:52), `PUT/GET/DELETE /places/{id}/reviews` (:64, :80, :93).
**moderation** (`moderation/router.py`): `POST /reports` (:27), `POST/DELETE /users/{id}/block` (:40, :57), `GET /me/blocked-users` (:66); staff: `GET /moderation/reports` (:74), `POST /moderation/reports/{id}/action` (:82).
**billing** (`billing/router.py`): `GET /me/billing` (:24), `POST /me/billing/subscribe` (:34), `POST /me/billing/cancel` (:53), `POST /me/billing/verify-purchase` (:62); webhooks без auth: `POST /webhooks/appstore`, `POST /webhooks/google-play` (`webhooks_router.py:23, :36`).
**tickets**: `GET /tickets/config`, `POST /tickets` (без auth, rate limit по IP) (`tickets/router.py:31, :41`).

Гейтове: `get_current_user` (`app/api/deps.py:23-49`), `require_terms_accepted` само на `POST /places`, `PUT /places/{id}/reviews`, `POST /dogs/{id}/group-walks` (`places/router.py:25, :69`, `social/router.py:213`) — **не** на `POST /reports`, walk-announcements, introductions, share-links; `get_current_staff_user` (`deps.py:63-70`).

### 3.6 Автентикация (identity)

- **Регистрация** `identity/router.py:99-133`: `CodeRequestThrottle` брои всяко обръщане (:105-106), `register_user` (bcrypt, `app/core/security.py:18-19`, отрязване до 72 байта :14), издава 6-цифрен код (`verification.py:63-89`, TTL 30 мин :27, `MAX_ATTEMPTS = 5` :31, само SHA отпечатък в базата), праща писмо; при SMTP грешка 201 с `verification_email_sent=false` (:118-130). Вход е възможен и преди потвърждение (`identity/models.py:35-39`).
- **Имейл код** `POST /auth/verify-email` (:136-153): `CodeAttemptThrottle` — отделен брояч, за да не се нулира от нова заявка (:74-92); грешен опит → `db.commit()` за да се запази `attempts` (:142-147).
- **Вход** (:223-239): `LoginThrottle` преди проверката (:228); успех → `create_access_token` + `create_session`.
- **Токени/сесии**: JWT HS256, `exp` = `ACCESS_TOKEN_EXPIRE_MINUTES` = 30 дни, `jti = secrets.token_hex(8)` (`app/core/security.py:29-41`, `config.py:34`). Няма refresh токени (`config.py:31-33`). Всеки токен е ред в `user_sessions`; `get_current_user` отхвърля токен без жив ред (`deps.py:38-45`). **Лимит `MAX_ACTIVE_SESSIONS = 2`** — трето влизане трие най-старото (`identity/service.py:47-63`).
- **Password reset**: заявка (:177-196) — брои се преди да се знае дали имейлът съществува, `sent=True` и при несъществуващ; потвърждение (:199-220) — `password_reset.py:82-107`, TTL 30 мин, 5 опита, после директен вход с нова сесия. **Находка (от кода):** `password_reset.confirm` не трие съществуващите `UserSession` редове — старите устройства остават влезли след смяна на паролата; единствено лимитът от 2 изхвърля най-старата (`password_reset.py:104-107`, `service.py:50-63`).
- **Изтриване** `DELETE /auth/me` (:257-268 → `service.py:120-175`): отменя вътрешния entitlement в хъба, събира файловите имена на собствените снимки, трие `email_verifications` ръчно, `db.delete(user)` каскадира, после best-effort трие файловете.
- **Rate limit** (`app/core/rate_limit.py`): плъзгащ прозорец в базата, три прага `pair`/`subject`/`ip` (:10-21), 429 с `Retry-After` (:113-137). Успех маркира редовете `cleared_at`, не ги трие (:136-149). `client_ip` чете `X-Real-IP`/последния `X-Forwarded-For` само при `RATE_LIMIT_TRUST_PROXY_HEADER=true` (:188-206); nginx го подава (`infra/edge/mybeagle.heppsu.com.conf:44`), но стойността на флага живее в `.env` на сървъра — **непроверено оттук**. С default `false` IP-прагът е изключен (`config.py:52-56`, `LOGIN_RATE_LIMIT_IP_ATTEMPTS = 0`).
- Писма: `mailer.py` — шаблони за 18 езика (проверено с: regex над `_VERIFICATION_TEMPLATES`, 19:46 UTC), STARTTLS с `ssl.create_default_context()` (:310), празен `SMTP_HOST` = само лог (`config.py:129-134`).

### 3.7 Sync протокол за кучетата

Сървърната страна е чист CRUD без sync-специфични полета: `Dog` няма `client_dog_id`, няма `deleted_at`, `GET /dogs` връща само живите редове на собственика + активните съсобствени (`dogs/service.py:256-268`). Единственото sync поле е `DogOut.updated_at` (`dogs/schemas.py:61-66`). Алгоритъмът живее в клиента `MyBeagle/lib/services/sync_service.dart:33-126`:

1. `GET /dogs` → карта по server id (:43-44).
2. За всяко локално куче: ако `serverId == null` **или** серверът не го връща („сираче") → `POST /dogs` наново (:62-75); иначе ако `updated_at` на сървъра е по-нов от последно видения → издърпва (:78-101); иначе `PATCH /dogs/{id}` (:103-105).
3. Сървърни кучета без локално копие → свалят се (:108-118).

**Дефект 1 — дубликат без `client_dog_id`.** Няма идемпотентен ключ: `POST /dogs` (`dogs/service.py:238-253`) винаги създава нов ред. Ако клиентът получи 201, но не успее да запише `serverId` локално (прекъснат процес между :65 и :67), следващият sync качва същото куче втори път и сървърът няма как да го познае. Същото при смяна на среда/акаунт. Документът `docs/ARCHITECTURE-multi-breed.md` (§1, П1) описва точно този „цикъл за размножаване на данни".

**Дефект 2 — липса на tombstones.** Изтриване на сървъра (`DELETE /dogs/{id}`, `dogs/service.py:312-347`) е физическо; списъкът не носи „изтрити id-та". Второ устройство на същия акаунт (позволени 2 сесии) или съсобственик, който още има локално копие, вижда кучето като „сираче" и го **пресъздава** (`sync_service.dart:47-64` — авторът го приема съзнателно за отменена съсобственост, но ефектът е същият и за истинско изтриване). Клиентът трие локално само след успешен `DELETE` или 404 (`dog_detail_screen.dart:320-345`); няма механизъм да научи, че някой друг е изтрил кучето.

### 3.8 Privacy / visibility модел

- Настройки: `PrivacySettings` по подразбиране е „затворено" — `show_dogs_in_community=False`, `location_precision=none`, `share_pedigree_publicly=False` (`privacy/models.py:35-57`); ред се създава лениво при първо четене (`privacy/service.py:23-36`).
- Къде **се четат**: `show_dogs_in_community` + `location_precision` — само в `list_nearby_dogs` (`social/service.py:683-691`); `location_precision != none` — и в `_published_point` за групови разходки (`:463`); `share_pedigree_publicly` — в `_pedigree_visible_to` (`dogs/service.py:186-190`, четено едва от 10.09.2026; преди това „показан контрол, който не прави нищо" :174-176).
- Блокиране — две различни подзаявки в `moderation/service.py`: `blocked_user_ids` еднопосочно (:109-119) и `blocked_either_way_user_ids` двупосочно (:122-153), плюс `is_blocked_either_way` (:156-179, `.first()` заради взаимен блок).
  - Двупосочно: приятели (`social/service.py:193`), известие за групова разходка (:487), списък разходки (:596), родословие (`dogs/service.py:183`), запознаване (`social/service.py:146`).
  - Еднопосочно (личен филтър): рецензии на места (`places/service.py:172`), кучета наблизо (`social/service.py:695`).
  - **Не се прилага изобщо** за: публичния изглед `/share/{token}` (токенът е правото, `sharing/router.py:76-77`), `GET /places` (местата са общи), `MeetupOut.attendees` — имената на кучетата на всички записали се излизат без филтър по блок (`social/service.py:524-547`).
- Съответствие с част 1 §4.2.1 („формулировка, не защита"): `show_dogs_in_community=False` спира само картата „наблизо"; кучето продължава да се показва по име като организатор/участник в `GET /group-walks` и през родословието при приятелство/публично родословие — тоест настройката е конкретен превключвател за един канал, не общ режим „невидим в общността".

### 3.9 Квантизация на локацията

- При запис: `privacy/service.py:16-20, :43-46` — `round(x, 2)` (~1 км) **преди** setattr; суровата точка не влиза в базата. Миграция `bf87cf3a6ce7` закръгли старите редове.
- При четене за други: `social/service.py:660-674` `_round_for_precision` — `city` → 2 знака (no-op), `country` → 0 знака (~100 км).
- Изключение по дизайн: `location_shares` пази **сурови** координати за представени приятели за 5–60 мин (`social/schemas.py:10`, `service.py:255-295`), delete-on-read на изтеклите (:277-279). Груповата разходка носи вече закръглената точка на организатора (:451-469, :503).

### 3.10 Moderation

- Доклади: `POST /reports` за place/place_review/user/group_walk, проверка за съществуване без FK (`moderation/service.py:36-63`); `details` ≤ `MAX_REPORT_DETAILS_LENGTH` (`schemas.py:13`).
- Блокиране: идемпотентно, self-block отказан (:66-97); списък `GET /me/blocked-users`.
- Staff: `GET /moderation/reports` (limit 50, :17) и `POST …/action` с `hide_content` (сетва `is_hidden` на place/review/group_walk; за `user` → `InvalidActionForTargetError`) или `dismiss`, с ред в `moderation_audit_logs` (:190-235). `is_staff` се вдига само в базата (`identity/models.py:66-72`).

### 3.11 Billing

- Хъб: `SubHubClient` → `{SUBHUB_URL}/api/v1/...` с header `X-API-Key` (`billing/client.py:23-33`); методи `entitlement`, `plans`, `subscribe`, `cancel(at_period_end)`, `renewed`, `payment_failed` (:52-81). Абонатът е `str(user.id)` (`service.py:3-4`).
- `entitlement_for` — **fail-open**: без конфигурация `configured=false, entitled=true`; при недостъпен хъб — кеш/stale/fallback с `source` (`service.py:45-67`; TTL `SUBHUB_CACHE_TTL_SEC`, кеш в процеса).
- `verify_purchase` (`service.py:151-208`) — **fail-closed**: без `APPSTORE_*`/`GOOGLE_PLAY_*` → `PurchaseVerificationError` (:137-148, :163-168); iOS → `appstore_verification.verify` (JWS на StoreKit 2 или base64 разписка на StoreKit 1 → `transaction_id` → App Store Server API статуси; активни са 1 и 4; production първо, после sandbox — `appstore_verification.py:45, :55, :159-190, :193-244`); Android → `googleplay_verification.verify` (`purchases.subscriptionsv2.get`, ACTIVE/IN_GRACE_PERIOD или CANCELED с бъдещ `expiryTime` — `googleplay_verification.py:40-48, :153-179`). Успех → `client.renewed`, sandbox се логва като warning (:190-206).
- **Находка (от кода):** `verify_purchase` не сверява покупката с извикващия потребител — `external_account_id(subscription)` (Play `obfuscatedExternalAccountId`) се чете само в webhook пътя (`service.py:260`), а Apple `appAccountToken` само в `handle_appstore_notification` (:324-331). Валиден чужд `purchaseToken`/разписка, подаден от друг акаунт, би довел до `client.renewed(str(user_id))` за подалия.
- Webhooks (`webhooks_router.py`): винаги 200. Apple — подписът се проверява с root сертификати от `APPSTORE_ROOT_CERTS_DIR` и верификатор според средата на транзакцията (`appstore_notifications.py:43-136`); решение по `notificationType`/`subtype` (`service.py:302-360`). Google — RTDN само задейства `lookup(purchaseToken)`; решението е по **състоянието от Play**, не по типа от тялото (`service.py:225-299`, мотивирано :232-241).
- `cancel_for_account_deletion` (:100-131) — docstring-ът още твърди „тази интеграция изобщо не е имплементирана" (:106-107), остаряло след 07–10.09.2026.

### 3.12 Legal

- 37 файла в `app/modules/legal/docs`: `privacy.md` + 17 езикови варианта (общо 18), `terms` × 18, `delete-account.md` двуезичен (проверено с: `ls … | wc -l`, 19:44 UTC). Поддържани езици `legal/router.py:21-24`; рендер Markdown→HTML с `tables` разширение и вграден CSS shell (:26-58); ръчно копие от клиентското репо, не автоматична синхронизация (:1-7).

### 3.13 Tickets (Control Center)

- `POST /api/v1/tickets` без вход, rate limit само по IP (`tickets/router.py:18-28`, `TICKET_RATE_LIMIT_*`), релей към `{COCKPIT_TICKETS_URL}/api/tickets` с header `X-App-Token` (`client.py:18-29`); 503 при недостъпен/неконфигуриран хъб (:48-51). `GET /tickets/config` връща `configured` (:31-38) и е DoD проверка в `infra/dod.yml` (`dokladvane.config_url`). Схема: `category`, `title` 3–200, `body` ≤4000, `contact` ≤320 (`schemas.py:10-16`).

### 3.14 Security

- CORS: `allow_origins=settings.CORS_ORIGINS` (default `[]`), `allow_credentials=True` (`app/main.py:27-33`, мотив `config.py:36-43`).
- Security headers: в приложението **няма** middleware освен CORS (проверено с: `grep -rn add_middleware app`, 19:45 UTC); HSTS се слага от nginx (`infra/edge/mybeagle.heppsu.com.conf:31`), `client_max_body_size 12m` (:33), TLS 1.2/1.3 (:26). Няма CSP/X-Content-Type-Options/X-Frame-Options за публичните HTML страници (`/share/{token}`, `/legal/*`).
- Fail-fast за `SECRET_KEY` в production/staging: ≥32 байта, не default (`config.py:13-14, :167-186`).
- Пароли: bcrypt (`app/core/security.py:18-25`); кодове: SHA отпечатъци, TTL, брояч опити; съсобственически код TTL 15 мин (`dogs/co_ownership.py:28`).
- Rate limit — виж 3.6; хранилище общо за процесите (`rate_limit.py:3-8`).
- Снимки: публичен `StaticFiles` без auth, обфускация чрез uuid4 (`main.py:45-49`); файлът се трие при триене на куче/акаунт (`dogs/service.py:312-347`).
- Няма bandit/pip-audit (виж 3.1). `infra/dod.yml` още изисква етикети `security/<sha>` и `legal/<sha>` и `infra/deploy.sh:337-353` ги проверява; локално има 20 `security/*`, 20 `legal/*`, 47 `tested/*` етикета (проверено с: `git tag -l`, 19:45 UTC).

### 3.15 `config.py` настройки (имена, без стойности)

`PROJECT_NAME`, `API_V1_PREFIX`, `ENVIRONMENT`, `DATABASE_URL`, `AUTO_CREATE_TABLES`, `SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `CORS_ORIGINS`, `RATE_LIMIT_ENABLED`, `LOGIN_RATE_LIMIT_{ATTEMPTS,WINDOW_SECONDS,ACCOUNT_ATTEMPTS,IP_ATTEMPTS}`, `CODE_REQUEST_RATE_LIMIT_{ATTEMPTS,WINDOW_SECONDS,IP_ATTEMPTS}`, `CODE_ATTEMPT_RATE_LIMIT_{ATTEMPTS,WINDOW_SECONDS,ACCOUNT_ATTEMPTS}`, `TICKET_RATE_LIMIT_{ATTEMPTS,WINDOW_SECONDS}`, `RATE_LIMIT_TRUST_PROXY_HEADER`, `FIREBASE_CREDENTIALS_PATH`, `SUBHUB_{URL,API_KEY,TIMEOUT_SEC,CACHE_TTL_SEC}`, `APPSTORE_{ISSUER_ID,KEY_ID,PRIVATE_KEY_PATH,BUNDLE_ID,APP_APPLE_ID,ROOT_CERTS_DIR,ENVIRONMENT}`, `GOOGLE_PLAY_{SERVICE_ACCOUNT_JSON_PATH,PACKAGE_NAME}`, `COCKPIT_{TICKETS_URL,APP_TOKEN,TICKETS_TIMEOUT_SEC}`, `SMTP_{HOST,PORT,USERNAME,PASSWORD,FROM,USE_TLS}`, `PUBLIC_BASE_URL`, `MEDIA_ROOT`, `PHOTOS_URL_PREFIX` (`app/core/config.py:20-154`). Четат се от `.env` през pydantic-settings (:18); `.env` не е в репото.

### 3.16 Тестове

- Проверено с: `.venv/bin/python -m pytest -q -x -p no:cacheprovider`, старт 19:40:36 UTC, край 19:45:34 UTC — **399 минаха, 4 пропуснати, 0 не минаха**, 296 s. 34 тестови файла, 385 тестови функции по `grep -rE "def test_" tests | wc -l` (разликата до 399 е от параметризация).
- Пропуснатите 4 са `tests/test_infra_backup.py` — `skipif(platform.system() != "Linux")` (`:17-20`), т.е. `backup.sh` не се проверява на macOS.
- Шумът: 459 предупреждения, сред тях `InsecureKeyLengthWarning` от PyJWT — тестовият `SECRET_KEY` е 20 байта, под препоръчаните 32 (ефект само в тестове; production е защитен от `config.py:167-179`).

---

## 4. Инфраструктура и операции

### 4.1 Среди

| среда | машина | клон-източник | публичен адрес | вход (nginx) | compose проект |
|---|---|---|---|---|---|
| production | Арес | `origin/main` | `https://mybeagle.heppsu.com` | общ с Groomelle (`groomelle-edge-edge-1`) | `mybeagle-prod` |
| тест | Деймос | `origin/dev` | `https://test.mybeagle.heppsu.com` | общ с iamtester/Groomelle/Cockpit (`testhub-test-edge-1`) | `mybeagle-dev` |

- Изборът на машина/адрес по среда: `infra/deploy.sh:40-55` (`case "$ENV_NAME"`), входовете: `infra/deploy.sh:193-196`.
- Production отказва реф, в чието име има `dev`: `infra/deploy.sh:59-65`.
- На машината всичко е под `/home/deploy/mybeagle/<среда>/` (`REMOTE_ROOT`, `infra/deploy.sh:69`): `.env`, `repo/` (чекаут), а бекъпите — `/home/deploy/mybeagle/backups/<среда>` (`infra/README.md:23-29`). Защо `/home/deploy`, а не `/srv`: `infra/README.md:11-19` (няма нужда от root).
- Арес е споделен с Groomelle production — записано съзнателно като риск (диск/рестарт засягат и двата): `infra/README.md:5-9`.
- Приложението не публикува портове навън; излиза се само през входа (Docker-публикуван порт заобикаля ufw): `infra/README.md:31-34`, `infra/docker-compose.yml:3-6`.
- Third machine (Фобос) участва само като пазител на частния GPG ключ за бекъпите: `infra/backup.sh:62`.

Забележка: `infra/README.md:3` и `infra/deploy.sh:42,47`, `infra/backup.sh:66` съдържат IP адресите на машините в явен вид — не се цитират тук.

### 4.2 Docker Compose и услуги (`infra/docker-compose.yml`)

- Име на проекта: `${MYBEAGLE_PROJECT:-mybeagle-prod}` — идва от `.env` на машината, НЕ се извежда от `MYBEAGLE_ENV`, защото би преименувало живите контейнери (`infra/docker-compose.yml:8-15`).
- **`db`** — `postgres:17-alpine`, том `db-data`, healthcheck `pg_isready` на 10 s/10 опита, `restart: unless-stopped` (`:18-31`). `POSTGRES_PASSWORD` е задължителен (`:23`, `${…:?}`).
- **`migrate`** — същият образ като api, `command: alembic upgrade head`, `AUTO_CREATE_TABLES=false`, `restart: "no"`, върви след здрава `db` и ПРЕДИ api (`:33-49`). Схемата никога не се променя от процес, който обслужва заявки.
- **`api`** — `env_file: [../../.env]` (целият `.env` влиза, без изброяване една по една — `:56-58`), `ENVIRONMENT=${MYBEAGLE_ENV:-production}`, `AUTO_CREATE_TABLES=false`, `MEDIA_ROOT=/app/media` (`:59-65`). Томове: `media-data:/app/media` (снимките, иначе изчезват при всяко разгръщане и процесът дори не тръгва заради права — `:66-78`) и `appstore-secrets:/app/secrets:ro` (`:79-89`). `depends_on`: `db` healthy + `migrate` completed_successfully (`:90-94`). Healthcheck: `GET http://127.0.0.1:8000/api/v1/health`, 30 s, 5 опита, `start_period` 20 s (`:95-106`).
- Томове: `db-data`, `media-data` (в нощните копия), `appstore-secrets` (нарочно НЕ в копията — Apple преиздава ключа безплатно) (`:109-116`).
- Мрежа: `default` е външна, `${MYBEAGLE_EDGE_NETWORK:-groomelle-edge}` — мрежата на входа, за да го намира nginx по име без публикуван порт; на Деймос се подава друго име през `.env` (`:118-125`).
- **Няма `edge` услуга в този compose** — входът е чужд проект (виж 4.4).

### 4.3 Образът (`infra/api.Dockerfile`)

- `python:3.13-slim` закован (`:5`); несъвпада с `README.md:10` („Python 3.14") и локалното `.venv` (python3.14) — виж 4.15.
- Непривилегирован потребител `beagle`, uid 10001 (`:9`, `:35`).
- Слоеве: requirements → `app/`, `alembic/`, `alembic.ini`, `scripts/` (`:14-20`) — `scripts/import_osm_places.py` е вътре в образа.
- `/app/media` се създава с правилния собственик ПРЕДИ да стане точка на монтиране — иначе Docker го създава като root и процесът пада с `PermissionError` (`:22-33`).
- `uvicorn app.main:app`, 1 работник, порт 8000 (`:41`).

### 4.4 Входът (nginx) — `infra/edge/*.conf`

Два огледални файла, по един на среда:

| файл | server_name | upstream (по име в мрежата) |
|---|---|---|
| `infra/edge/mybeagle.heppsu.com.conf` | `mybeagle.heppsu.com` | `mybeagle-prod-api-1:8000` (`:39,42`) |
| `infra/edge/test.mybeagle.heppsu.com.conf` | `test.mybeagle.heppsu.com` | `mybeagle-dev-api-1:8000` (`:39,42`) |

Общи характеристики (редовете са еднакви в двата файла):
- Порт 80: `/.well-known/acme-challenge/` от `/var/www/certbot`, всичко останало → 301 към https (`:6-16`).
- Порт 443: HTTP/2, Let's Encrypt под `/etc/letsencrypt/live/<домейн>/`, `TLSv1.2`+`TLSv1.3` (`:18-26`), HSTS 1 година + includeSubDomains (`:31`), `client_max_body_size 12m` (`:33`).
- `resolver 127.0.0.11 valid=10s` + променлива за upstream: името се разрешава ПРИ ЗАЯВКА, за да не отказва nginx да тръгне, ако API-то го няма — иначе деплой на My Beagle би свалил и groomelle.com (`:35-39`).
- Проксира с `Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`, `proxy_read_timeout 120s` (`:41-48`).
- Файлът е ИЗВОР; живият блок се доставя ръчно в тома `/etc/nginx/tls/` на входа (`infra/README.md:98-99`), защото на 23.08.2026 чужд деплой изтри блока от `conf.d/` (`infra/README.md:93-96`). `docs/ARCHITECTURE-multi-breed.md:300-309` описва като бъдеща работа (R1) генериране и доставка от `deploy.sh`.
- Коментарът в `:28-30` за закачен сертификат (`PINNED_CERT_SHA256`) е обявен за остарял в `docs/ARCHITECTURE-multi-breed.md:326` — pinning е изключен в пуснатите билдове.

### 4.5 `infra/deploy.sh` — стъпка по стъпка

Употреба (`:30-35`): `deploy.sh dev origin/dev` / `deploy.sh prod origin/main <sha>`.

1. **Коренът е репото на скрипта**, не текущата папка (`:9-19`) — на 29.08.2026 `tested/` етикет кацна в чуждо репо.
2. Аргументи: среда, реф, одобрение (`$3` или `MYBEAGLE_ODOBRENIE`) (`:21-28`).
3. Избор на машина/ключ/адрес по среда; презаписваеми с `MYBEAGLE_SSH_HOST`, `MYBEAGLE_SSH_KEY`, `MYBEAGLE_PUBLIC_URL` (`:40-70`). Ключът е файл под `~/.ssh/` по машина (`SSH_KEY_DEFAULT`, `:43,48`); ако липсва, `ssh` върви без `-i` (`:72-73`).
4. Отказ на `prod` + реф с `dev` в името (`:59-65`).
5. **Локалният клон не се движи сам**: ако името съществува в `origin/`, взима се `origin/<реф>` (`:75-83`); `TARGET_SHA` = разрешеният комит (`:85-86`).
6. Само за `prod` (`:367-371`), в този ред:
   - **Предпазител 1 — `proveri_test`** (`:105-130`): дърпа `refs/tags/tested/*` от origin и иска `TARGET_SHA` да е ПРЕДШЕСТВЕНИК на някой `tested/<sha>` (`git merge-base --is-ancestor`, `:110`) — ancestry, не съвпадение, защото `main` и `dev` са различни комити. При отказ печата последните 5 тествани (`:121-128`).
   - **Предпазител 3 — `proveri_dod`** (`:240-365`): виж 4.6.
   - **Предпазител 2 — `poiskaj_odobrenie`** (`:145-176`): без одобрение печата кандидата, живия комит на машината (`git rev-parse HEAD` в `repo/`, `:147`) и `git log jivo..кандидат` (`:157`) и спира с точната команда за повторение (`:164`). Одобрението е sha (префикс), не флаг „да"; ако клонът се е придвижил, отказва (`:170-174`). Честно за границата: скриптът не различава Ив от сесия — оставя следа, не защитава (`:140-144`).
7. **Отдалечена част през `ssh … bash -s <<REMOTE`** (`:375-411`): проверява, че `$ROOT/.env` съществува (`:380-383`); `git fetch --prune --prune-tags --force --tags` — етикетите се ОГЛЕДАЛЯТ, иначе преместен таг убива деплоя мълчаливо („would clobber", `:386-393`); `checkout --detach` на целта (`:404-405`); `docker compose --env-file $ROOT/.env -f infra/docker-compose.yml build` → `up -d --remove-orphans` → `ps` (`:408-410`). Heredoc-ът е неквотиран нарочно и коментарът забранява нови необезопасени обратни кавички (`:395-402`) — има regression тест.
8. **Health gate отвън**: до 20 × 5 s срещу `${PUBLIC_URL}/api/v1/health` през публичния адрес (nginx+TLS+DNS+Docker мрежа, не само контейнера) (`:413-441`). При неуспех — `docker compose logs --tail 40 api` от машината и exit 1 (`:443-445`).
9. **`proveri_sasedite`** (`:191-224`): пита самия вход (`docker exec <вход> nginx -T`) кои `server_name` обслужва (`:198-201`), `curl`-ва всяко по https; 000/5xx = паднал съсед = деплоят пада (`:205-222`). 401/403/404 се броят за живи (`:208-209`). Ако имената не се четат — прескача с предупреждение (`:203`).
10. **Етикет `tested/<short>`** се слага и бута в origin само за `dev`, и само СЛЕД отговор отвън (`:424-435`); ако не успее, казва, че production ще откаже комита.

Живо: `tested/*` етикети — 47, `security/*` — 20, `legal/*` — 20 (проверено с: `git -C … tag -l 'tested/*' | wc -l` и аналогично, 19:40 UTC). Единственият версионен таг е `v1.0.0`.

### 4.6 `infra/dod.yml` — Definition of Done

Списъкът е във файл, не в скрипта, за да расте без да се пипа логиката и да се вижда в диф (`infra/dod.yml:7-8`). Как се чете от `deploy.sh`:

| секция | ключ | какво проверява | къде |
|---|---|---|---|
| `dokladvane` | `marshrut: /api/v1/tickets` | слабо ниво — маршрутът е в `openapi.json` на ТЕСТОВАТА среда; казва се на глас, че е слабо (`deploy.sh:288-297`) | `dod.yml:25-26` |
| `dokladvane` | `config_url: /api/v1/tickets/config`, `ochakva: '"configured":true'` | силно ниво — маршрут само за четене на теста връща очаквания низ (`deploy.sh:279-287`); празно `ochakva` е отказ, не зелено (`deploy.sh:275-278`, история с BSD `sed` на `:264-269`) | `dod.yml:27-28` |
| `sreda.zadaljitelni` | `COCKPIT_APP_TOKEN`, `COCKPIT_TICKETS_URL` | по ssh пита МАШИНАТА-цел дали ключът е в `$REMOTE_ROOT/.env` и е непразен (`grep -q '^K=..*'`), отговор „da/ne", всичко друго = „не мога да проверя" = отказ (`deploy.sh:302-333`); не чете стойности | `dod.yml:39-42` |
| `security_scan.etiket: security` | `security/<sha>` | ancestry-етикет от Security Officer (`deploy.sh:335-354`) | `dod.yml:52-53` |
| `pravno_revu.etiket: legal` | `legal/<sha>` | ancestry-етикет от Legal Officer | `dod.yml:62-63` |

Маршрутът `/api/v1/tickets/config` съществува: `app/modules/tickets/router.py:31-38` (`configured = service.get_client() is not None`).

Пропускане: само `DOD_PROPUSNI="<sha>:<причина>"`, sha трябва да съвпада с целта, печата се шумно (`deploy.sh:244-255`, `dod.yml:65-74`). От паметта: етикетите security/legal „паднаха" на 30.08.2026 като изискване — но в кода към днешна дата все още се проверяват (`deploy.sh:338`, `dod.yml:52-63`); непроверено дали това е разминаване или паметта е остаряла.

`docs/ARCHITECTURE-multi-breed.md:330-346` отбелязва, че при 9 приложения гейтът пита едно приложение и трябва да стане правило (`zadaljitelni_shablon`), не списък.

### 4.7 Тайни — къде живеят (само имена, не съдържание)

- `.env` в git е забранен: `.gitignore:7`; на машината — `/home/deploy/mybeagle/<среда>/.env`, 0600 (`infra/README.md:24`). `deploy.sh` отказва без него (`:380-383`), но никога не го чете, само `grep -q` за наличие (`:318`).
- Compose го подава два пъти: `--env-file` за интерполация на `MYBEAGLE_*`/`POSTGRES_*` (`deploy.sh:408-409`) и `env_file: [../../.env]` в контейнерите (`docker-compose.yml:41,58`).
- Ключове, които `app/core/config.py` очаква от средата: `SECRET_KEY` (задължително силен ≥32 байта в production/staging, иначе fail-fast при import — `:164-188`), `POSTGRES_*`/`DATABASE_URL`, `SMTP_*` (`:135-140`), `COCKPIT_TICKETS_URL`/`COCKPIT_APP_TOKEN` (`:125-126`), `SUBHUB_URL`/`SUBHUB_API_KEY` (`:87-88`), `APPSTORE_*` и `GOOGLE_PLAY_*` (`:100-115`), `FIREBASE_CREDENTIALS_PATH` (`:81`).
- AppStore `.p8` + Apple root сертификати: ИМЕНУВАН том `appstore-secrets`, монтиран `:ro` на `/app/secrets`, пълни се ръчно еднократно с `chown 10001` (`docker-compose.yml:79-89`); празен том = верификацията е изключена, не пада.
- Бекъп-тайни: частният GPG ключ е на Фобос, Арес има само публичния (`infra/backup.sh:60-62`); отпечатъкът на получателя е зашит като подразбиране в `GPG_RECIPIENT` (`:69`, не се цитира); ssh ключ за изнасяне `OFFSITE_KEY` под `~/.ssh/` (`:68`).
- Firebase service account JSON — само път в конфигурацията (`config.py:79-81`); Google Play service account JSON — само път (`config.py:104`).

### 4.8 Бекъпи (`infra/backup.sh`)

- Извор `infra/backup.sh`; на машината `/home/deploy/mybeagle/bin/backup.sh`, копира се ръчно, нарочно ИЗВЪН `repo/` (деплоят го пресъздава) (`infra/README.md:166-169`). Cron: `0 2 * * *` — в 2:00, преди Groomelle в 3:00 (`backup.sh:4-7`).
- `.env` се ЧЕТЕ със `sed`, не се `source`-ва (`SMTP_FROM=Име <адрес>` би било пренасочване) (`:21-27`).
- Спряна база = ПРОВАЛ, не „няма какво да се пази" (`:34-39`).
- `pg_dump --clean --if-exists | gzip -9` → `<среда>-<клеймо>.sql.gz` (`:41-43`); проверка размер ≥1 KB и `gzip -t` (`:45-53`).
- **Изнасяне (`iznesi`, `:74-125`)**: `gpg --encrypt` с публичен ключ (`:87`); проверява, че пакетът е за точния подключ на получателя, не по exit code (`:89-103`); `rsync` към `OFFSITE_HOST:OFFSITE_DIR` (Деймос, `/home/deploy/offsite/mybeagle`) (`:109-113`); сравнява размера отсреща (`:115-124`). Провал на изнасянето = провал на бекъпа (`:106-108`, `:127`). `MYBEAGLE_OFFSITE=0` го изключва и го казва на глас (`:78-85`). Честно: „извън машината" — да; „извън доставчика" — не (`:64-65`).
- **Снимки** (`:129-173`): том `${PROJECT}_media-data` → `tar.gz` през еднократен `alpine:3` контейнер, същото криптиране и изнасяне. Липсващ том НЕ е провал, освен ако базата помни снимки (`SELECT count(*) FROM dogs WHERE photo_filename IS NOT NULL`) — тогава файловете са в слоя на контейнера и ще изчезнат = ГРЕШКА (`:155-172`).
- Ротация: `KEEP_DAILY=14` (`:16`) локално за `.sql.gz`, `.gpg`, media (`:150-151`, `:179-180`) и на Деймос (`:175-177`).
- **Клеймо `LAST_SUCCESS`** — unix секунди, само при пълен успех (`:182-186`); Control Center го гледа, праг 26 часа.
- `docs/ARCHITECTURE-multi-breed.md:708` иска `pg_dump` непосредствено преди `alembic upgrade` в `deploy.sh` — днес НЯМА такава стъпка в `deploy.sh` (миграцията върви само на compose ниво, `docker-compose.yml:36-49`).

### 4.9 Седмичен OSM внос (`infra/osm_import_cron.sh`)

- На машината `/home/deploy/mybeagle/bin/osm_import.sh`, cron `0 5 * * 0` (неделя 5:00, извън прозореца 2:00–4:00) (`:4-6`).
- Вика `docker exec mybeagle-<среда>-api-1 python scripts/import_osm_places.py --global` (`:22,30`) — скриптът е в образа (`api.Dockerfile:20`); спрян контейнер = грешка (`:24-27`).
- Само production; идемпотентен по `(source='osm', external_id)` (`:8-14`). Кронът НЕ е активиран на никоя машина, докато функцията не е одобрена (`infra/README.md:219-223`).

### 4.10 Мониторинг и health

- `GET /api/v1/health` — `app/main.py:53-70`: `SELECT 1` срещу базата; при `SQLAlchemyError` → 503 `{"status":"unavailable"}` и `logger.error`; иначе `{"status":"ok"}`. Нарочно не е `app/modules/health` (здравното досие на кучето) — съвпадението на имената подведе първия деплой (`:56-59`).
- Кой го пита: compose healthcheck отвътре (`docker-compose.yml:101-106`), `deploy.sh` отвън през публичния адрес (`:418-420`), а `proveri_sasedite` пита `/` на всеки домейн на входа (`:207`).
- `LAST_SUCCESS` на бекъпа е второто наблюдавано клеймо (4.8).
- MON-001 (учението с реална авария) — в това репо няма следа (проверено с `grep -rn "MON-001"` в `.py/.sh/.md/.yml`, 19:43 UTC); от паметта: 09.08.2026, 31 сек. престой, човек уведомен за под 30 сек. — непроверено тук.
- Тестове: `tests/test_service_health.py:16,22` — ok при жива база, 503 при недостъпна.

### 4.11 Логове

- Няма собствена конфигурация на logging (стандартен `logging.getLogger`, uvicorn → stdout); четат се с `docker compose … logs api` (`deploy.sh:444`) и `docker exec <вход> …`/`docker logs` за nginx на входа.
- Логери: `app/main.py:17`, `app/core/rate_limit.py:49` („app.security.rate_limit"), `app/modules/identity/{mailer,router}.py` („mybeagle.identity"), `app/core/push.py:12`, `app/modules/{dogs,billing}/…` (общо 54 извиквания на logger в `app/`, проверено с grep, 19:43 UTC).
- Какво се логва: блокирани и неуспешни опити за вход/код с `subject`, `ip`, `retry_after` — „без чувствителни данни" (`rate_limit.py:271-278`, `:305-315`); неуспешно изпращане на писмо с адреса на получателя (`identity/router.py:129,172,194`); health грешка (`main.py:67`).
- **Какво НАРОЧНО не се логва**: Google Play `purchaseToken` — нито в грешка, нито в лог, защото `HttpError` носи целия URL с токена (`billing/googleplay_verification.py:128-136`); текстът на App Store изключението не влиза в отговора към клиента, но `transaction_id` СЕ логва (кратък, показван на купувача) (`billing/appstore_verification.py:200-209`); тайни от `.env` — `deploy.sh` изрично не ги чете (`dod.yml:37-38`).
- Без SMTP: писмото се логва като WARNING с целия текст вместо да излиза (`identity/mailer.py:286-293`) — само dev/test.

### 4.12 SMTP relay (концептуално)

- Конфигурация: `SMTP_HOST`, `SMTP_PORT=587`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS=True` (`app/core/config.py:129-140`). Празен `SMTP_HOST` = ConsoleSender поведение (не се преструва на изпратено).
- Код: `app/modules/identity/mailer.py:285-315` — `smtplib.SMTP` с timeout 20 s, `starttls(context=ssl.create_default_context())` (без context Python не удостоверява отсрещната страна — находка на Security Officer, 29.08.2026, `:303-310`), `login` само ако има `SMTP_USERNAME` (`:311-312`).
- Concept: през Google Workspace; `SMTP_USERNAME` трябва да е реалният профил, не псевдонимът (Google връща 535 на псевдоним) (`config.py:132-134`). От паметта: production релейва през Workspace по IP без парола, капанът е IPv4 срещу IPv6 — в кода това не личи (`SMTP_USERNAME` е незадължителен, `:311`), непроверено на машината.
- Rate limit пази ресурса „изпращане на писмо" (дневен таван на профила): 3 заявки/час на субект (`config.py:58-63`).
- Тестове: `tests/test_mailer_tls.py`, `tests/test_mailer_language.py`.

### 4.13 Infra тестове

Проверено с: `./.venv/bin/python -m pytest tests/test_infra_deploy.py tests/test_infra_backup.py tests/test_service_health.py -q` → **29 минаха, 4 пропуснати**, 78.8 s, 19:43 UTC. Общо в репото: 403 теста (`pytest --co`, 19:43 UTC).

**`tests/test_infra_deploy.py` — 27 теста.** Вдига истинско git репо с origin и пуска `deploy.sh` наистина; `ssh` и `curl` са подставени, но различават командите (`nginx -T`, `rev-parse`, `grep -q`, `/openapi.json`, `/config`) — стъб, който казва „ок" на всичко, би обезсмислил проверката за съседите (`:1-75`). Групи:

| група | тестове (ред) |
|---|---|
| Предпазител 1 (tested/) | `:163`, `:172`, `:182` (предшественик минава) |
| Предпазител 2 (одобрение) | `:206`, `:218` (друг комит не важи), `:230` |
| dev не иска нищо / бележи tested | `:244`, `:251` |
| стар предпазител dev-реф в prod | `:262` |
| съседи на входа | `:272` (паднал съсед спира), `:295` |
| DoD етикети | `:357`, `:370` (само единият не стига) |
| DoD пропускане | `:384` (точен комит), `:395` (шумно) |
| DoD докладване | `:412`, `:430` (слабото ниво се казва на глас) |
| независимост от текущата папка | `:464`, `:488` (dod.yml от своето репо) |
| fetch като огледало на етикети | `:517` |
| heredoc без необезопасени обратни кавички | `:589` (статичен), `:620` (regression, изпълнява се локално) |
| DoD ключове в `.env` на машината | `:704`, `:724`, `:775` (празен ключ ≠ пълен) |
| `ochakva` | `:740` (празно не минава), `:760` (BSD sed) |

**`tests/test_infra_backup.py` — 4 теста**, пропускат се извън Linux (`:18-21`, GNU coreutils), с подставен `docker` и `MYBEAGLE_OFFSITE=0`: липсващ том без снимки не е провал (`:91`), липсващ том СЪС снимки е провал (`:106`), празен том не е провал (`:121`), пълен том се архивира (`:131`). Изнасянето (gpg/rsync) се проверява само на живо срещу Арес (`:1-7`).

**`tests/test_service_health.py` — 2 теста** (виж 4.10).

Няма CI: `.github/` липсва (проверено с `ls -d .github`, 19:43 UTC); `docs/ARCHITECTURE-multi-breed.md:709` го изброява като R‑1 предусловие.

### 4.14 `infra/README.md` — резюме

224 реда, всичко на български. Покрива: защо Арес и цената на споделянето (`:3-9`); `/home/deploy` вместо `/srv` (`:11-19`); карта на пътищата (`:21-29`); без публикувани портове (`:31-34`); разгръщане и трите предпазителя — тест, одобрение, DoD, с историята зад всеки (`:36-134`); общите входове и инцидентът от 23.08.2026 (`:79-99`); схема само от миграции (`:136-141`); сертификат и мобилен клиент, `--reuse-key`, команда за отпечатък (`:143-162`); бекъпи и разминаването репо/машина от 24.08.2026 (`:164-201`); седмичен OSM внос (`:203-223`).

### 4.15 Разминавания, забелязани при четенето

- `infra/README.md:200-201` твърди „Копията не са изнесени извън машината… не е свършена", а `infra/backup.sh:55-125` вече изнася криптирано към Деймос и прави провала на изнасянето провал на бекъпа — README е остарял в този абзац (по-горе на `:166-181` същият README вече описва изнасянето).
- `README.md:10` казва Python 3.14, образът е `python:3.13-slim` (`infra/api.Dockerfile:5`), а `.venv` е 3.14 — production и локалните тестове вървят на различни версии.
- `README.md:45-63` описва само модулите identity/dogs и „Остава: свързване на клиента" — далеч зад действителните 16 модула (`app/main.py:74-91`).
- Коментарът за certificate pinning в `infra/edge/*.conf:28-30` е обявен за остарял (`docs/ARCHITECTURE-multi-breed.md:326`).
- `dod.yml` все още изисква `security/` и `legal/` етикети (`:52-63`), докато паметта казва, че са отпаднали на 30.08.2026; към момента `deploy.sh prod` ще откаже без тях.
- `deploy.sh` няма `pg_dump` преди миграция (иска се в `docs/ARCHITECTURE-multi-breed.md:708`).
- `RATE_LIMIT_TRUST_PROXY_HEADER` е `False` по подразбиране (`app/core/config.py:77`) и `LOGIN_RATE_LIMIT_IP_ATTEMPTS=0` (`:56`) — nginx подава `X-Real-IP` (`infra/edge/*.conf:44`), но дали production `.env` го включва, е непроверено (само машината знае).

---

## 5. Магазини

Пълната история на App Store ревютата (5 подавания, всеки отказ с Guideline код, причина и поправка), Google Play пътят, демо акаунтът и текущата процедура за подаване са в паметта: `memory/reference-app-store-review-history-beagle-owner.md` и `memory/reference-store-api-procedures.md`; правилата дословно — `memory/reference-store-rules-that-stopped-us.md`. Резюме: отказ #3 (2.1 Information Needed — демо акаунтът не съществуваше в production), #4 (2.1(b) IAP извън подаването; 2.1(b) грешка при плащане: product id + StoreKit 2 JWS; Guideline 4 разрешения на български), #5 (3.1.2 връзка към условията в описанието); самооттегляния 62, 63, 78-с-1-елемент. Чувствително: описанията × 17 с връзките, App Review Information (demo account, notes ≤ 4000), абонамент + група винаги в подаването, никакви оферти (30-те дни са от хъба).

## 6. Абонаменти

Хъб Heppsu Subscriptions (модул в Control Center): `POST /me/billing/subscribe` = 30-дневен пробен период на потребител; entitlement = хъбът (fail-open при недостъпен хъб — приет компромис). Проверка на покупка: `POST /me/billing/verify-purchase` → Apple: JWS (StoreKit 2) през `SignedDataVerifier` за средата на транзакцията (Sandbox/Production; Xcode/LocalTesting се отказват) → App Store Server API за същата среда; SK1 разписка: production → sandbox при 404. Google: `purchases.subscriptionsv2.get` с service account. Webhooks: `/api/v1/webhooks/appstore` (ASSN), `/api/v1/webhooks/google-play` (RTDN през Pub/Sub). Капани: App Review купува в SANDBOX; production Server API дава 401 до публикуване; unacknowledged Play покупка = refund след 3 дни (клиентът НЕ потвърждава при неуспешна сървърна проверка — нарочно). Доказана sandbox покупка: 11.09.2026 11:08 UTC.

---

## 7. Данни и съдържание

### 7.1 Породни справочни данни — `MyBeagle/lib/models/beagle_reference.dart` (425 реда)

| Какво | Къде | Стойности |
|---|---|---|
| Разновидности по ръст | `beagle_reference.dart:17-44` | `thirteenInch`: 0–9.07 kg, 0–33.02 cm; `fifteenInch`: 9.07–13.61 kg, 33.02–38.1 cm (точни преобразувания от 20/30 lb и 13/15 in) |
| Комбиниран диапазон | `beagle_reference.dart:168` | `(0, 13.61)` — когато собственикът не е избрал разновидност |
| Крива на теглото | `beagle_reference.dart:78-98` | 19 точки `(maxAgeMonths, kg)`: 3→4.5, 4→5.7, 5→6.8, 6→7.8, 7→8.6, 8→9.3, 9→9.8, 10→10.2, 11→10.5, 12→10.7, 24/36/48/60/72/84→11.0, 96→10.8, 108→10.7, 120→10.5 |
| Отвъд 120 м. | `beagle_reference.dart:102-107` | плоска, последната точка; не екстраполира |
| Прагове (`WeightStatus.classify`) | `beagle_reference.dart:118-124` | отклонение от референтното: ≤10 % `ideal`, ≤20 % `normal`, ≤30 % `attention`, >30 % `vetCheck` |
| Единна преценка (`assessWeight`) | `beagle_reference.dart:146-162` | възрастта има предимство; без възраст — по разновидност/комбиниран диапазон, само `normal`/`attention` |

Произход на кривата: коментарът на `beagle_reference.dart:62-69` казва изрично, че НЕ е публикувана статистика — работна референция, съставена от Ив на 18.08.2026 от AKC диапазона + Royal Canin таван (~13.5 kg). Разновидностите цитират AKC/NBCA стандарта (`beagle_reference.dart:26-30`).

Източници с URL — 7 константи `BeagleReferenceLink` на `beagle_reference.dart:211-244`: VCA ×3 (how-much-to-feed, puppy-raising, feeding-times), AKC breed page, National Beagle Club standard, Royal Canin breed page, WSAVA Body Condition Score.

Тест: `MyBeagle/test/beagle_reference_test.dart` — 5 теста (допиране на границите при 9.07, комбиниран диапазон, точки от кривата, плоскост над 120 м., четирите зони). Броят е от `grep`, не от пуснат `flutter test`.

### 7.2 puppyTips — `beagle_reference.dart:248-425`

- 4 съвета (`maxAgeMonths` 2, 6, 12, 12), всеки с `titleByLanguage`/`bodyByLanguage` на **18 езика** и `source` (VCA). Fallback към `en` при непознат език (`beagle_reference.dart:204-208`).
- Рендерират се в `lib/screens/dogs/nutrition_screen.dart:401-404` — скриват се при ≥12 м., показват се и без дата на раждане; линк към източника на `nutrition_screen.dart:439-442`.
- Преведени на 18 езика едва на 10.09.2026 (комит `82e084c`, след отказа на Apple по Guideline 4) — до тогава били само на български (`beagle_reference.dart:189-197`).
- Тест `test/puppy_tips_localized_test.dart` — 5 теста: всеки поддържан език има заглавие и текст, без кирилица извън `bg`, непразни, fallback `en`. Взима езиците от `AppLocalizations.supportedLocales`, т.е. нов език автоматично ще падне теста при липсващ превод.

### 7.3 beagle_facts.dart (943 реда)

- Клас `BeagleFacts` на `lib/models/beagle_facts.dart:11-20`, fallback към `en`.
- **9 езика × 100 факта**: bg (:24), en (:126), pt (:228), de (:330), es (:432), fr (:534), it (:636), hu (:738), el (:840). Проверено с `awk` по редовете на литералите, 19:40 UTC.
- **Липсват 9 от 18-те езика** на приложението: cs, da, ja, ko, nb, nl, pl, ro, sv — падат на английски (`AppLocalizations.supportedLocales` в `lib/l10n/app_localizations.dart:113-130`). Последна промяна на фактите: `b65e98c`, 30.08.2026 (6 нови езика).
- Тест `test/beagle_facts_test.dart` — 3 теста: точно 100 **само за bg и en**, дубликати/празни **само за bg и en**, fallback. Не проверява останалите 7 езика, нито покритие на 18-те (за разлика от puppy_tips теста).
- Ротация: `lib/services/beagle_fact_service.dart:12-20` — индекс в SharedPreferences, цикличен, без повторение до изчерпване; джаджата на Начало ползва `current()` (`:34-42`). Locale-регресия покрита в `test/beagle_fact_card_locale_test.dart`.

### 7.4 Nutrition (API) — `MyBeagleApi/app/modules/nutrition`

Няма справочно съдържание — само потребителски данни на куче:
- `NutritionProfile` (`models.py:16-37`): един ред на куче (`unique` на `dog_id`), 9 свободни полета — `food_type`, `food_brand`, `amount` (текст, „250г"), `meals_per_day`, `schedule`, `treats`, `supplements`, `allergies_intolerances`, `notes`.
- `DietChangeLogEntry` (`models.py:40-50`): растящ лог `changed_on` + `description`.
- Маршрути `router.py:13`: `GET/PUT /dogs/{dog_id}/nutrition`, `POST/GET /dogs/{dog_id}/nutrition/changes`. Достъп за собственик ИЛИ активен съсобственик (`service.py:17-29`, поправено 06.09.2026).
- Тестове: `tests/test_nutrition.py` — 6.

Здравните съвети за хранене (puppyTips) живеят изцяло в клиента (7.2), не в API-то.

### 7.5 Nearby базата — `MyBeagleApi/app/modules/places`

**Модели** (`models.py`):
- `PlaceCategory` (`:32-44`): 7 стойности — hotel, restaurant, cafe, park, veterinary, dog_hotel, other. Клиентът огледално в `MyBeagle/lib/models/place.dart:5-14`.
- `PlaceSource` (`:47-51`): `user` / `osm`.
- `Place` (`:54-116`): name, category, address, phone(255), opening_hours (свободен OSM синтаксис), `emergency_care`, notes, lat/lng (nullable — без координати само в списъка), source, external_id, is_hidden; `UniqueConstraint(source, external_id)` (`:59`) прави вноса идемпотентен; индекс lat/lng (`:63`).
- `PlaceReview` (`:119-137`): едно ревю на потребител на място (unique), rating 1–5 (`CheckConstraint`), comment, is_hidden.

**Откъде идват местата** — два пътя, **няма seed файл, фикстура или миграция с данни**:
- Проверено с `grep -ln "INSERT|bulk_insert|op.execute" alembic/versions/*.py` (само `ALTER TYPE` в `0b643d6ad8fb` и `UPDATE` за закръгляне в `bf87cf3a6ce7`) и `find . -name "*.json" -o -name "*.csv" -o -name "*.sql"` → 0 файла, 19:41 UTC.
- (а) Потребители през `POST /places` (`router.py:21`).
- (б) Bulk от OpenStreetMap (Overpass) през `scripts/import_osm_places.py` (387 реда): `amenity=veterinary → veterinary`, `amenity=animal_boarding → dog_hotel` (`:121-124`); по държава (`EUROPEAN_COUNTRY_CODES`, 45 кода, `:65-71`), `--global` за целия свят, `--city`/`--bbox` за град; `EXCLUDED_COUNTRY_CODES` = BY, IR, SY, KP, CU, MM (`:119`). Без рейтинги от OSM по лиценз (`:12-17`).
- Седмичен крон: `infra/osm_import_cron.sh` — неделя 5:00, `--global`, само production; `infra/README.md:219-223` казва, че кронът **не е активиран на нито една машина** към момента на писане. Живо състояние непроверено (без ssh).
- **Брой записи**: не се вижда от репото. Локалният `MyBeagleApi/my_beagle.db` има 0 реда в `places` (проверено с `sqlite3 -readonly`, 19:44 UTC). Production броят иска достъп до базата.

**Наблизо / emergency / ревюта** (`service.py`):
- `list_places` (`:68-118`): `lat`/`lng`/`radius_km` заедно → bbox предфилтър + haversine, сортирано по разстояние; `distance_km` в `PlaceOut` (`schemas.py:44`).
- `emergency_care` НЕ е в `PlaceCreate` (`schemas.py:13-19`) — само от OSM импорта, за да не се самопровъзгласява „спешен 24/7"; филтър `emergency_care=true` (`service.py:97-98`); клиент `lib/services/places_api.dart:26`.
- Ревюта: upsert/list/delete_own (`service.py:129-184`); скритите не влизат в средната (`:36-40`).
- Тестове: `tests/test_places.py` — 20. **Скриптът за импорт няма тест** (`grep -rln import_osm tests/` → 0).

### 7.6 Правни документи

**Файлове** (проверено с `ls`, 19:42 UTC):
- Клиент `MyBeagle/docs/legal`: 41 файла — `privacy.md` (bg) + 17 × `privacy.<lang>.md`, `terms.md` + 17 × `terms.<lang>.md`, `delete-account.md` (двуезичен bg+en в един файл, `:9` и `:55`), `support-contact.md`, `app-store-privacy-answers.md`, `play-console-answers.md`, `README.md`.
- API `MyBeagleApi/app/modules/legal/docs`: 37 файла = privacy ×18 + terms ×18 + `delete-account.md`.

**Сервиране** — `MyBeagleApi/app/modules/legal/router.py`:
- prefix `/legal` (`:18`), извън `/api/v1` (`tests/test_legal.py:45-48`); `GET /legal/privacy[/{lang}]`, `/legal/terms[/{lang}]`, `/legal/delete-account` (`:72-89`); без наставка = bg (`:65-70`); неподдържан език → 404 (`:75`); `_SUPPORTED_LANGS` = 18-те кода (`:22-25`).
- Markdown → HTML с `tables` extension (`:56`), общ HTML шел (`:26-48`).

**Версиониране**: няма номер на версия в документите — само ред 3 „В сила от: 29.08.2026" (локализиран) във всичките 36 privacy/terms файла, еднаква дата на всички езици (проверено със `sed -n 3p`, 19:43 UTC). Реалната версия е git: последни промени в клиента `50be3d2` (раздел 3, групови разходки), `8906902` (докладване/блокиране), `d93c97d` (03.09.2026: 30 дни → 0,99 €); в API `580115b`, `362ea00`, `305a1b3`.

**Огледално копие и паритет**:
- Всичките 37 API файла са **байт-идентични** с клиентските (проверено с `cmp` по двойки, 19:42 UTC).
- **Тест за паритет НЯМА** — нито в API (`tests/test_legal.py`: 7 теста, само рендер/таблица/§8 без „Plus"/404/маршрут), нито в клиента (`grep -rln "docs/legal" MyBeagle/test` → 0). Синхронизацията е ръчна по изричен дизайн (`router.py:1-8`). `.github/workflows` няма в нито едно от двете репота (`ls`, 19:43 UTC).

**Разминаване, което си струва внимание** (от кода, потвърдено с grep):
- Условията в приложението НЕ водят към бекенда, а към `heppsu.com/beagle-owner-terms[.bg|.pt].html` — `lib/services/legal_links.dart:29-37` и `lib/screens/onboarding/terms_acceptance_screen.dart:33-43`; 16 от 18 езика падат на английския HTML.
- Сайтът `heppsu_website/beagle-owner-terms.bg.html:58-60` (последна промяна `0186211`, 31.08.2026) все още описва „Планът Plus — основните функции са безплатни", докато `docs/legal/terms.md:81` и `/legal/terms` казват „30 дни, после 0,99 €, няма безплатна версия" (`grep -c Plus`: сайт 2, репо 0).
- Тестът `tests/test_legal.py:26-33` пази само API копието — не и страницата, която потребителят реално отваря от екраните за онбординг и абонамент (`billing_screen.dart:627`).
- Политиката е ОК: отива към бекенда на езика на екрана за всичките 18 (`legal_links.dart:42-45`).
- `docs/legal/README.md:14-37` е остарял: описва v2/v0.2 на 3 езика с незатворени чекбоксове, докато има 18 езика и hosted версия.

### 7.7 Release notes — `lib/models/release_notes.dart` + `lib/services/release_notes_service.dart`

- `currentReleaseNotes.version = '1.0.0+11'` (`release_notes.dart:19`), **9 езика**: bg, en, pt, de, es, fr, it, hu, el (`:21-85`), fallback `en` (`:14-15`). Съдържанието описва функционалност от 1.0.0 (9 вида здравни записи, статус на ваксинации, календар…).
- Приложението е на `1.2.7+78` (`pubspec.yaml:19`, проверено 19:40 UTC); последна промяна на бележките `b65e98c`, 30.08.2026.
- Показва се веднъж на стойност `version` (`release_notes_service.dart:12-19`, диалог `lib/widgets/whats_new_dialog.dart:12-13`) → от 1.0.0+11 насам „Какво ново" не е показвало нищо ново, а нов потребител вижда бележки за 1.0.0.
- Тест `test/release_notes_service_test.dart` — 3 теста за „веднъж на версия"; няма тест, който да обвързва `version` с pubspec или да иска 18 езика.

### 7.8 Store листинг — `MyBeagle/store`

- `store/play/listing.md` (601 реда): **18 локала** (`:9` bg … `:570` sv), обновено 04.09.2026 (`:3`); кратко ≤80 / пълно ≤4000 знака; вкаран в Play Console на 06.09.2026 (`store/play/CHECKLIST.md`, секция „Вече решено"). Внимание: `CHECKLIST.md` съдържа service-account адрес — не го цитирам.
- **App Store листинг текст няма** в репото (`grep -rln "App Store Connect|subtitle|promotional"` → само `docs/legal/app-store-privacy-answers.md` и `store/apple-review-reply-*.md`).
- Скрийншоти: `store/screenshots/ios/{bg,en,pt}` по 5 (3 от 18 езика), `store/screenshots/android/en` 8 (1 от 18).
- Отговори към App Review: `apple-review-reply-2026-09-07.md`, `apple-review-reply-2026-09-10.md` (вторият е untracked — `git status`, 19:44 UTC).

### 7.9 Обобщение на дупките (само данни/съдържание)

| Икона | Какво | Къде |
|---|---|---|
| ⚠️ | Условията, които приложението отваря (heppsu.com), описват стария Plus модел; API/репо копието — новия | `legal_links.dart:29-37`, `heppsu_website/beagle-owner-terms.bg.html:58` |
| ⚠️ | Факти на 9/18 езика; тестът покрива само bg/en | `beagle_facts.dart:24-840`, `test/beagle_facts_test.dart` |
| ⚠️ | Release notes замръзнали на 1.0.0+11 при 1.2.7+78, 9/18 езика | `release_notes.dart:19` |
| ⚠️ | Няма тест за паритет между двете копия на правните документи (днес са идентични) | `router.py:1-8`, `tests/test_legal.py` |
| ℹ️ | Nearby данните нямат seed — идват само от Overpass/потребители; импорт скриптът без тест; кронът неактивиран по README | `scripts/import_osm_places.py`, `infra/README.md:219-223` |
| ℹ️ | App Store листинг текст и скрийншоти за 15 езика липсват в репото | `store/` |
| ℹ️ | `docs/legal/README.md` статусът е остарял | `docs/legal/README.md:14-37` |

---

## 8. Качество


### 8.1 Тестова стратегия днес

**Клиент — `/Users/iv/Documents/Development/MyBeagle/test`** (проверено с: `find test -name '*.dart' | wc -l`, `grep -rhoE '^\s*(test|testWidgets)\(' test/ | wc -l`, 19:41 UTC): 85 Dart файла = 82 `*_test.dart` + 3 фалшификата в `test/fakes/` (`mock_backend.dart`, `in_memory_secure_store.dart`, `minimal_scope.dart`); 336 `test(`/`testWidgets(` извиквания в 16 `group(`. Няма integration/golden тестове, няма `test/scripts`. Категории:

| категория | файлове (брой тестове) | какво покриват |
|---|---|---|
| Регресии по находки на живо (датиран коментар на първия ред) | `save_with_side_effects_test.dart` (3), `sync_orphaned_server_id_test.dart` (1), `weight_save_test.dart` (1), `reset_password_resend_test.dart` (1), `home_screen_error_test.dart` (1), `dog_detail_screen_delete_test.dart` (2), `billing_trial_already_owned_test.dart` (2), `secure_store_test.dart` (1) | „Записите не се запазват в Здраве" (18.08), осиротял server_id (06.09), изтриване на куче преглъща 403 (03.09), Keychain errSecDuplicateItem |
| API клиенти срещу `MockBackend` | `dogs_api_test.dart` (7), `health_api_test.dart` (9), `places_api_test.dart` (12), `social_api_test.dart` (7), `share_api_test.dart` (7), `billing_api_test.dart` (5), `meetups_api_test.dart`, `nutrition_api_test.dart`, `privacy_api_test.dart`, `shows_api_test.dart`, `ticket_api_test.dart`, `api_client_test.dart` (4 — стар токен → излизане) | договорът клиент↔сървър, но срещу фалшификат, не срещу записани отговори |
| Store/services | `auth_store_test.dart` (18), `dog_store_test.dart` (17), `home_layout_store_test.dart` (16), `sync_service_test.dart` (6), `entitlement_store_test.dart` (6), `pet_passport_store_test.dart` (5), `reminder_service_test.dart` (5), `beagle_fact_service_test.dart` (5), `release_notes_service_test.dart` (3), `jwt_utils_test.dart` (4), `secure_http_client_test.dart` (1), `debug_log_test.dart` (1) | студен старт, локален кеш, freemium разрез, синхронизация |
| Екрани (widget тестове през harness) | `dog_list_screen_test.dart`, `co_ownership_screen_test.dart`, `account_screen_test.dart`, `billing_screen_test.dart`, `health_calendar_screen_test.dart`, `places_list_screen_test.dart`, `root_shell_subscription_gate_test.dart` (4), `root_shell_add_dog_fab_test.dart`, `subscribe_unlocks_immediately_test.dart`, `language_switcher_test.dart`, `floating_action_button_hero_tags_test.dart` | достъп след абонамент, FAB, bottom sheet скрол |
| Локализация | `localization_completeness_test.dart` (2), `auth_error_language_test.dart` (4), `billing_error_language_test.dart` (5), `puppy_tips_localized_test.dart` (5), `weight_unit_label_test.dart` (4), `weight_and_build_info_l10n_test.dart` (3), `beagle_fact_card_locale_test.dart`, `enum_labels_test.dart`, `validator_messages_test.dart` | проверява по ключове; глобът по `app_*.arb` и сканирането за кирилица извън l10n са планирани (Ф0.2a), не налични |
| Платформена конфигурация / стор | `android_manifest_test.dart`, `android_splash_screen_test.dart`, `ios_permission_strings_test.dart` (4 — Apple отказ билд 74), `build_config_test.dart` (3 — `--dart-define=API_BASE_URL`), `splash_config_test.dart`, `store_product_ids_test.dart` (4), `moderation_ugc_test.dart` (3 — Guideline 1.2) | статични проверки на манифести/plist/product ids |
| Домейн | `dog_test.dart` (21), `medication_interval_test.dart` (3), `vaccination_summary_test.dart` (5), `beagle_reference_test.dart` (5), `beagle_facts_test.dart` (3), `eu_pet_passport_test.dart` (5), `dog_completion_test.dart` (5), `country_search_test.dart` (10), `pedigree_node_test.dart`, `friend_dog_test.dart`, `units_controller_test.dart`, `locale_controller_test.dart` | възраст, интервали, теглови зони на бийгъла |

**Бекенд — `/Users/iv/Documents/Development/MyBeagleApi/tests`** (проверено с: `find tests -name '*.py' | wc -l`, `grep -rhoE '^\s*(async )?def test_' tests/ | wc -l`, 19:41 UTC): 35 файла = 34 `test_*.py` + `conftest.py`; 385 `def test_`, 7 `@pytest.mark.parametrize`. Всички вървят срещу **SQLite от нула**, не срещу Postgres: `tests/conftest.py:14` (`os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"`). Категории:

| категория | файлове (брой) | една линия |
|---|---|---|
| Автентикация/сигурност | `test_auth.py` (27), `test_rate_limit.py` (12), `test_email_verification.py` (14), `test_password_reset.py` (10), `test_cors.py` (1), `test_config.py` (4), `test_mailer_tls.py` (1), `test_mailer_language.py` (9) | 6-цифрени кодове, лимити за вход/кодове/тикети, CORS по подразбиране, STARTTLS |
| Домейн | `test_social.py` (41), `test_sharing.py` (28), `test_dog_co_ownership.py` (21), `test_places.py` (20), `test_dogs.py` (12), `test_health.py` (11), `test_pedigree.py` (9), `test_nutrition.py` (6), `test_shows.py` (5) | CRUD + права по маршрут |
| Билинг | `test_billing_verification.py` (17 — App Store), `test_googleplay_verification.py` (17), `test_billing.py` (9 — хъбът), `test_billing_webhooks.py` (8) | верификация на реални покупки, RTDN/ASN V2 |
| Поверителност/безопасност | `test_blocking_and_pedigree_leaks.py` (23 — 5 дефекта от прегледа на 10.09), `test_moderation.py` (9), `test_privacy.py` (7), `test_group_walk_visibility.py` (7), `test_account_deletion_photo_cleanup.py` (7) | блокиране, изтичане през родословие, изтриване на файлове |
| Инфраструктура | `test_infra_deploy.py` (27 — „двата предпазителя пред production"), `test_infra_backup.py` (4), `test_migrations_schema.py` (1 — create_all ≠ миграции), `test_migration_coordinate_rounding.py` (2), `test_service_health.py` (2), `test_legal.py` (7), `test_tickets.py` (7) | deploy.sh/dod.yml/backup.sh се изпълняват с подставен docker/ssh |

### 8.2 CI

- **Няма CI в нито едно репо** (проверено с: `ls .github/workflows` в двете, 19:40 UTC): `MyBeagle/.github` и `MyBeagleApi/.github` не съществуват; няма `.pre-commit-config.yaml`, `Makefile`, `pytest.ini`, `pyproject.toml`, `mypy.ini`, `.bandit`.
- `MyBeagle/scripts/build_release.sh` **не пуска** `flutter analyze`/`flutter test` (grep за `flutter (analyze|test)` в `scripts/*.sh`: 0 попадения).
- `MyBeagleApi/infra/deploy.sh:428-430` слага етикета `tested/<sha>` при dev деплой + health 200; grep за `pytest|ruff|bandit` в `deploy.sh`: 0 — „tested" значи „деплойнат", не „тестван".
- Единственият гейт пред production е `MyBeagleApi/infra/dod.yml` (функционални проверки: тикетинг маршрут + `config_url` с `"configured":true`), четен от `deploy.sh`.
- Броят тестове („303/313/328 минават") съществува само като текст в комитите (LESSONS-LEARNED I10) — числата по-горе са мои статични преброявания, не изпълнение.
- Client `README` не покрива екраните; тестът `test/readme_covers_screens_test.dart` (I10 мярка 6) липсва.

### 8.3 Git хукове

**`Business Partner/tools/claude-hooks/`** (4 файла, 127 реда общо) — Claude Code хукове, не git хукове:

| скрипт | събитие | какво прави |
|---|---|---|
| `guard_git.sh:16-34` | PreToolUse (Bash) | разпознава `git [-C път] commit`, намира репото от `-C`/`cd`/cwd; на `main`/`master` или detached HEAD → `exit 2` (командата се отказва). Ff-merge/push/тагове остават разрешени (I6) |
| `prompt_guard.sh:13-24` | UserPromptSubmit | инжектира задължителна първа стъпка при 4 шаблона: „не намирам/не виждам" → снимка на екрана; „готово/подадох" → провери ASC/Play API; „не работи/дефект" → лог от живата система преди хипотези; „production/коя версия" → „проверено с: <команда>, <час>". Никога не блокира (I3, I11, I12) |
| `memory_mechanism_check.sh:11-19` | PostToolUse (Write\|Edit) | `memory/feedback-*.md` без ред `^Механизъм:` → `exit 2` (I14) |
| `install.sh:16-32` | еднократно от Ив | копира трите в `~/.claude/hooks/` и добавя записите в `~/.claude/settings.json` (с резервно копие) |

Инсталация: проверено с `python3 -c 'json.load(~/.claude/settings.json)["hooks"]'` + `ls ~/.claude/hooks/`, 19:41 UTC — и трите са регистрирани (PreToolUse/UserPromptSubmit/PostToolUse) и присъстват в `~/.claude/hooks/`; съвпада с memory „инсталирани от Ив на 12.09".

**`.githooks` в репотата: няма** (проверено 19:40 UTC): `MyBeagle/.githooks`, `MyBeagleApi/.githooks` не съществуват; `git config core.hooksPath` е празен в двете; `.git/hooks/` съдържа само `*.sample`. Планираният `commit-msg` хук (I14 мярка B, Ф0.0) и `pre-commit` (файл > 5 MB, лични адреси) не са написани.

### 8.4 Статичен анализ

- **Клиент**: `MyBeagle/analysis_options.yaml:19` — `include: package:flutter_lints/flutter.yaml` по подразбиране, `rules:` секцията е празна (ред 32-34, само коментари); `analyzer.exclude` за `build/ android/ ios/ web/ windows/ macos/ linux/` (ред 11-18). `pubspec.yaml` dev_dependencies: `flutter_test`, `flutter_lints ^6.0.0`, `flutter_launcher_icons`, `flutter_secure_storage_platform_interface`. Няма `dart format` гейт, няма custom lint.
- **Бекенд**: `MyBeagleApi/ruff.toml` — `line-length = 120`, `target-version = "py312"`; `select = F, E9, W, B, UP, SIM, I` (ред 5-13); `ignore = B008, B904, UP042` (ред 14-22); `alembic/versions/*` изключен от E/F/I/UP/W (ред 25). **Няма** `S`-правила (security), **няма** bandit, mypy, pip-audit никъде в репото (grep 0 попадения в `*.md/*.sh/*.toml/*.txt/*.yml`). Единственият dev пакет е `pytest==9.1.1` (`requirements.txt:32`) + `cryptography` за TLS теста.
- Няма нищо, което да ги изпълнява автоматично (виж 8.2) — Ruff се пуска на ръка („Ruff намери две грешки, а аз вече бях къмитнал", I10).

### 8.5 Известни дефекти и технически дълг — пълен списък

**a) TODO/FIXME/XXX/HACK** (проверено с `grep -rnE '\b(TODO|FIXME|XXX|HACK)\b'` по двете репота, 19:41 UTC):
- MyBeagle: **0**.
- MyBeagleApi: **2**, и двата са исторически споменавания в docstring, не отворени маркери: `app/modules/billing/appstore_verification.py:3` и `tests/test_billing_verification.py:3` (описват поправения на 07.09 `verify_purchase`, който хвърляше винаги).

**b) `catch (_)` без лог в `MyBeagle/lib/`: 23** (проверено с `grep -rnE 'catch \(_\)' lib/` + `-A3`, 19:41 UTC). Нито един не вика `DebugLog`/`rethrow`; телата са само `setState` с l10n низ, коментар, нулиране на флаг или `return null`. Общата грешка `noNetworkConnection` маскира всичко (Keychain, 4xx, парсер). 17 файла:

| файл | редове | тяло |
|---|---|---|
| `lib/screens/account/account_screen.dart` | 84, 184 | l10n `noNetworkConnection`; ред 184 е „Изтрий акаунта" (I9: ред 115 има DebugLog, 184 — не) |
| `lib/screens/account/billing_screen.dart` | 158, 419 | `billingPurchaseError` |
| `lib/screens/account/reset_password_screen.dart` | 62, 93 | `noNetworkConnection` |
| `lib/screens/account/verify_email_screen.dart` | 71, 95 | `noNetworkConnection` |
| `lib/screens/account/forgot_password_screen.dart` | 51 | `noNetworkConnection` |
| `lib/screens/onboarding/onboarding_screen.dart` | 45, 68 | `noNetworkConnection` |
| `lib/screens/onboarding/terms_acceptance_screen.dart` | 63 | `noNetworkConnection` |
| `lib/screens/dogs/shows_screen.dart` | 218 | само `_saving = false` — потребителят не вижда нищо |
| `lib/screens/dogs/share_screen.dart` | 89 | само `_creating = false` — същото |
| `lib/screens/dogs/pedigree_screen.dart` | 63 | само коментар („следваща синхронизация ще го качи") |
| `lib/screens/dogs/dog_detail_screen.dart` | 348 | коментар; локалното изтриване продължава при мрежова грешка |
| `lib/widgets/moderation_actions.dart` | 70, 114 | SnackBar `noNetworkConnection` |
| `lib/services/api_client.dart` | 162 | коментар („тялото не е JSON") — приемливо |
| `lib/services/auth_store.dart` | 102 | коментар („локалният кеш остава меродавен") |
| `lib/services/entitlement_store.dart` | 54 | коментар — **fail-open** при мрежова грешка (I9) |
| `lib/services/jwt_utils.dart` | 13 | `return null` |
| `lib/services/debug_log.dart` | 65 | коментар — самият лог преглъща грешката си |

Свързано: 19 `FutureBuilder` срещу 6 `hasError` в `lib/` (проверено с grep, 19:41 UTC); `apiErrorText(` — 0 попадения (планираният помощник от I5 не съществува); `DebugLog.` се ползва на 36 места.

**c) `e.message` в `lib/screens`: 24** в 15 файла (проверено с `grep -rnE '\be\.message\b' lib/screens`, 19:41 UTC) — суровият сървърен текст (Pydantic JSON, кирилица на английски интерфейс) стига до UI: `friends_screen.dart` 6 (89, 117, 154, 206, 252, 309); `co_ownership_screen.dart` 2 (54, 103); `meetups_tab.dart` 2 (66, 94); `onboarding_screen.dart` 2 (44, 67); `account_screen.dart` 2 (114, 183 — през `genericErrorWithMessage`); по 1: `join_shared_dog_screen.dart:51`, `nutrition_screen.dart:130`, `dog_detail_screen.dart:337`, `weight_section.dart:206`, `health_screen.dart:742`, `report_problem_screen.dart:60`, `home_screen.dart:118`, `add_place_screen.dart:54`, `forgot_password_screen.dart:50`, `terms_acceptance_screen.dart:62`. Плюс 3 в `lib/widgets` (`needs_sync_prompt.dart:47`, `moderation_actions.dart:67,111`) = 27, числото от LESSONS-LEARNED и Ф0.2b; 28 общо в `lib/`.

**d) LESSONS-LEARNED раздел 2 — I1–I14** (`Business Partner/docs/LESSONS-LEARNED-beagle-owner-2026-09.md:133-301`), само заглавията:
- I1 (135) Платежната верига стигна до двата стора без нито една реална покупка
- I2 (149) „Готово" по зелени тестове и четене на код, без екран на устройство
- I3 (161) Билдът стига до Ив преди средата зад него да е проверена; тест и production билд споделят package name и локално хранилище
- I4 (173) Насоките на Apple се откриваха по една на отказ; известни блокери, отложени „в беклога", ставаха отказ
- I5 (183) Локализацията се проверява по ключове, не по съдържание
- I6 (195) Действия на живо без изрично одобрение — комити на main / detached HEAD и стор промени, при пет записани правила
- I7 (207) Продуктовите факти живееха на 5+ места и се разминаваха до последната секунда
- I8 (219) Версии и артефакти без механична връзка към git
- I9 (231) Тихи провали: празни catch блокове, fail-open интеграции и стъбове, които имитират
- I10 (243) Локалната среда не е production и няма CI, което да го хване — броят тестове е самоотчетен
- I11 (255) Инструкции към Ив за UI на стора/приложението по памет, и повече от една стъпка наведнъж
- I12 (267) Твърдения към Ив за външни системи без „проверено с" и отчети като дневник на сесията
- I13 (281) Тестове върху реалните канали, акаунти и файлове на Ив
- I14 (293) Правило в паметта ≠ мярка: изрични правила на Ив, нарушени след записването им, защото бяха текст без механизъм

Раздел 3 (ред 303-305): нито един урок не отпадна; 24 с verdict keep.

**e) PLAN-universal-dog-app.md §1 Фаза 0** (`Business Partner/docs/PLAN-universal-dog-app.md:87-107`) — дефектите на Beagle Owner, изброени за поправка:
- **Ф0.2b** (изрично): 23 `catch (_)`, 27 `e.message`, фактите за породата 9 → 18 езика (900 низа).
- **Ф0.2a**: три теста, които „ще паднат върху днешния код" — `localization_completeness` с glob по `app_*.arb`, `no_silent_catch`, `no_raw_server_message`, плюс `test_count_gate` (allowlist, не брояч).
- **Ф0.1**: naive/aware datetime (helper копиран 5 пъти, I10) → `app/db/types.py AwareDateTime` + статичен тест; миграции срещу Postgres от предишния head, upgrade→downgrade→upgrade; `alembic heads == 1`.
- **Ф0.6**: 8 зашити места на идентичност (keychain ключове, bundle, product ids, push заглавие, terms URL).
- **Ф0.10**: маршрути, които заобикалят visibility предиката (`test_visibility_all_routes.py` пада на днешния код — списък за R0).
- **Ф0.12**: тест и production билд споделят applicationId/bundle и Keychain (I3) → flavor `test` с `.test` суфикс.
- **Ф0.3**: липса на golden тестове (Home, Health, Weight, Friends, Nearby, Account, Billing, SubscriptionRequired, Onboarding × bg/en × 2 резолюции).
- **Ф0.0**: липсващи хукове и скриптове — `.githooks/commit-msg` + `pre-commit`, `regress.sh`, `ll_gate.sh`, `disk_guard.sh`, `asc.py submission-check`, `play_status.py track-check`.
- Приемен критерий (ред 107): CI зелен в двете репота, `tested/<sha>` само от CI-зелен sha, `ll_gate.sh = 0`.

**f) Беклог от паметта — „Статус 14.09.2026"** (`memory/project-my-beagle.md:565-572`), „открити и отложени, след одобрението":
1. snapshot на името на родителя в родословието при изтриване;
2. 6 мои тестови акаунта с домейн example.com в production за изтриване;
3. UCrop portrait lock;
4. edge-to-edge на Android 15;
5. цената на екрана за абонамент идва от бекенда, не от StoreKit.

Контекст от същия раздел: App Store 1.2.7 (78) WAITING_FOR_REVIEW от 11.09, замразено; Play 1.2.7 (78) live; бекенд production `577bc45` (`main`=`dev`) — съвпада с `git -C MyBeagleApi log -1` (`577bc45`, клон `dev`) и клиента `2e9c2e8` „Версия 1.2.7 (билд 78)", клон `dev` (проверено 19:41 UTC).

**g) Планирани в LESSONS-LEARNED/PLAN, но липсващи днес** (проверено с `test -e`, 19:41 UTC): `MyBeagle/test/no_silent_catch_test.dart`, `test/no_raw_server_message_test.dart`, `test/git_hooks_test.dart`, `test/readme_covers_screens_test.dart`, `MyBeagleApi/tests/test_no_cyrillic_in_api_errors.py`, `tests/test_infra_hooks.py`, `tests/test_legal_parity.py`, `tests/test_migrations_postgres.py`, `app/db/types.py`, `Business Partner/scripts/ll_gate.sh` (директорията `scripts/` не съществува), `.githooks/commit-msg` и `.github/workflows/ci.yml` в двете репота — всичките 14 липсват. От мерките на I9 вече са налични само `tests/test_email_verification.py`, `tests/test_password_reset.py` (mailer хвърля → `sent: false`) и `tests/test_infra_deploy.py` (стъбът изпълнява, не имитира).

---

## 9. Решения и отхвърлени алтернативи (Beagle Owner → влияние върху Universal Dog App)

- Без фрийемиум: всичко зад 30-дневния trial от хъба; никакви стор оферти. Universal наследява същия продукт/цена (Р4/Р10).
- Породата е свободен текст с default „Бийгъл“ → контролиран `breed_key` + компоненти (F1); Beagle Owner backfill → beagle.
- ЕС паспортът само в телефона (решение от 03.09) → сървърен в Universal с изрично съгласие (Р8).
- Локацията се квантизира на СЪРВЪРА (град ~1 км / държава ~100 км), community OFF по подразбиране — остава.
- Приятелството е куче↔куче, без owner профили, без чат — остава (BRD §28).
- Модерация: двупосочен блок, днес „формулировка, не защита“ (част 1 §4.2.1) → visibility слой за всички маршрути (F11).
- Sync: без `client_dog_id` (дубликати при retry), tombstones не пазят от възкресяване → поправки в R0.
- Съдържанието в билда (OTA отхвърлена в част 1) → git-като-CMS през API (Р1); Beagle Owner получава само seed.
- Един applicationId за test/prod (Zoe/Bailey инцидентите) → flavor `test` (Ф0.12).
- Версии без връзка към git (65 версии за 78 билда) → уникален номер от таг.

## 10. Числа (14.09.2026)

- Клиент: `1.2.7+78`; 18 ARB; 82 тестови файла / 336 случая (проверено с grep, 19:45 UTC — броене, не изпълнение); последно пълно изпълнение: 336 минават (10.09).
- Бекенд: 33 тестови файла / 385 случая по grep; последно изпълнение 399 минават, 4 пропуснати (11.09); production `577bc45` (проверено с /api/v1/health и контейнера, 12.09 19:49 UTC).
- App Store: 1.2.7 (78) WAITING_FOR_REVIEW, 3 елемента (проверено през ASC API 13.09 03:52 UTC). Google Play: 1.2.7 live (от паметта, 11.09).
- Потребители: 16 акаунта, 2 външни (от паметта, 10.09 — базата се чете само през API/лог).
- Билдове: 78 за 25 дни; production деплои на бекенда ≈ 20.
- LOC: клиент ~68 000 реда Dart, бекенд ~8 600 реда Python (от част 1, 10.09; непроверено днес).
