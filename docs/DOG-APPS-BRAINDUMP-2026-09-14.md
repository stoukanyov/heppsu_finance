# Кучешките приложения на Heppsu — brain-dump за нова сесия (14.09.2026)

Написано по заявка на сесията „Dog Application“. Първо предупреждението, после осемте точки. Идентификатори, ключове и адреси на машини нарочно не са тук — те са в паметта на проекта (`~/.claude/projects/-Users-iv-Documents-Development-Business-Partner/memory/`, файловете `reference-store-api-procedures.md`, `project-mybeagle-deploy.md`, `reference-ssh-kliuchove-mashini.md`).

## ⚠️ Предупреждение преди всичко

Ново ОТДЕЛНО кучешко приложение е точно това, което Apple 4.3(a) и Google Play „Repetitive Content“ наказват на ниво developer акаунт (засяга и My Life Within). Ив реши на 13.09.2026: ЕДНО ново приложение за всички породи (Universal Dog App) вместо породни клонинги. Ако „Another Dog Application“ е именно то — всичко по-долу е готово. Ако е трето приложение — прочети `docs/ARCHITECTURE-multi-breed-2-stores-and-delivery.md` §1–§2 и го покажи на Ив, преди да пишеш код.

## 1. Кои приложения

- **Beagle Owner** (вътрешно „My Beagle“ — вътрешното име не влиза в production). Клиент: `/Users/iv/Documents/Development/MyBeagle` (Flutter, applicationId/bundle `com.heppsu.myBeagle`). Бекенд: `/Users/iv/Documents/Development/MyBeagleApi` (FastAPI + Postgres + Alembic); production `mybeagle.heppsu.com` на Арес; тестова среда `test.mybeagle.heppsu.com` на Деймос. Аудитория: собственици на бийгъли; 18 езика; 173 държави (без FR, RU, BY, MM). Монетизация: абонамент Plus €0,99/месец, 30 дни безплатно от нашия хъб (не от стора); продукти `plus_monthly` (Play) и `com.heppsu.myBeagle.plus.monthly` (App Store).
  Статус 14.09.2026: Google Play 1.2.7 (78) live; App Store 1.2.7 (78) WAITING_FOR_REVIEW от 11.09 (пето подаване след 4 отказа/оттегляния); бекенд production `577bc45`. **Замразено** до отговора на Apple: нищо в production и в магазините.
- **Universal Dog App** (име TBD — решение Р15 на Ив): едно приложение за всички породи (pure / mixed / unknown), нова идентичност (5 таба Today / Health / Nearby / Pack / My Dog; Journey като център; „Living Companion“ визуална система), общ бекенд с Beagle Owner, безплатна миграция, един абонамент на човек. Beagle Owner остава наследен продукт и получава само 1.3.0 (облачно копие на локалните данни + ядро + дефекти) — нищо ново продуктово, иначе 4.3.
- „Още 6–8 породни приложения“ — **отхвърлени** (13.09). Маркетингът по порода: Apple Custom Product Pages (до 70, deep link iOS 18+, ключови думи в търсенето), Play Custom Store Listings (до 50, по ключови думи), кампанийни линкове `go.heppsu.com/<breed>` с `breed_hint` в онбординга.

## 2. Концепция и функционалности

**Beagle Owner (в production):** регистрация с имейл код; досие на кучето (снимка, тегло с референтна крива по AKC, здраве: ваксини/посещения/събития, хранене, ЕС паспорт — САМО локално в телефона); календар/напомняния (локални); Nearby (курирана база ветеринари/хотели/паркове, OSM/CARTO карта); социални: QR запознанство куче↔куче (токен 10 мин), приятели, живо споделяне на локация 5–60 мин само с приятели, „кучета наблизо“ OFF по подразбиране с точност град/държава (квантизация на сървъра), „В парка съм“ push, групови разходки + RSVP; съсобственост (QR/линк, отменяем); споделяне с ветеринар (линк); родословие (родители/деца; видимо при публично разрешение или приятелство); изложби; докладване + двупосочно блокиране; изтриване на акаунт; тикетинг към Control Center; 100 факта (само 9 от 18 езика). **Няма**: чат, owner профили, търсене на хора, форуми.

**Universal Dog App (само документи, нула код):** онбординг език → държава → име → порода/mixed → възраст → пол → опционално → тур; Journey (8 етапа × 13 категории; mixed по размерен клас; без фалшива точност; без медицински диагнози); Health разширен (лекарства, състояния, алергии, документи, диета, female); Travel & ID (микрочип, документи, readiness по country rulesets); Notifications center + сървърни напомняния; Pack = днешното + филтър „моята порода / всички“; кампании по порода; миграция без копиране. Roadmap R0 → R8 в PLAN.

## 3. Стек и архитектура

- **Клиент:** Flutter (Dart ^3.12), `in_app_purchase` (StoreKit 2 по подразбиране — `serverVerificationData` е JWS, не разписка), 18 ARB, без Firebase в pubspec на Beagle Owner (device token не се регистрира), без deep links още. Планирано: монорепо `heppsu-dogs` — `packages/dog_core` + `packages/dog_ui` + `apps/beagle_owner` + `apps/universal` (pub workspace); CI на hosted Linux; golden тестове преди преместването.
- **Бекенд:** FastAPI, SQLAlchemy, Alembic (миграциите се проверяват срещу истински Postgres на тестовата среда — SQLite крие дефекти). Модули `app/modules/{identity,dogs,health,nutrition,places,privacy,sharing,shows,social,moderation,billing,legal,tickets,applink,security}`. За много приложения: идентичността идва от nginx Host → регистър в `app/core/apps.py`; породата виси на КУЧЕТО (`breed_key`), не на приложението. Справочно съдържание: YAML в git → JSON в образа → `/content` с ETag (git-като-CMS, без OTA система).
- **Общи компоненти:** Heppsu Subscriptions хъб (модул в Control Center; entitlement на потребител; хъбът НЕ тегли пари — магазините теглят, ние проверяваме: Apple App Store Server API + `SignedDataVerifier` за Sandbox И Production; Google `androidpublisher purchases.subscriptionsv2` + RTDN през Pub/Sub); Control Center (cockpit.heppsu.com) за беклог, тикети, рискове; SMTP през Google Workspace relay по IP (капан: IPv4/IPv6; псевдоним = 535); общ nginx на Арес за няколко домейна (Groomelle също) — пресъздаване може да свали съсед.
- **Деплой:** `MyBeagleApi/infra/deploy.sh dev origin/dev` (издава таг `tested/<sha>` след health); `deploy.sh prod origin/main <sha>` само с изричен sha от Ив; `main` само ff-merge от `dev`; работи се в `dev`. Secrets на production в docker volume (Apple `.p8`, Google service account, Apple root certs).

## 4. Ключови файлове (в `Business Partner/docs/`, освен ако е казано друго)

- `BRD_Universal_Dog_App_v1_BG.md`, `UX_UI_Universal_Dog_App_v1_BG.md` — продуктовата база от Ив (13.09).
- `/Users/iv/Documents/Development/MyBeagleApi/docs/ARCHITECTURE-multi-breed.md` — част 1 (общ бекенд).
- `ARCHITECTURE-multi-breed-2-stores-and-delivery.md` + `ARCHITECTURE-multi-breed-2-FACTS.md` — политиките дословно, диск, CI, матрица.
- `ARCHITECTURE-universal-dog-app.md` — техническият спец (инвентар file:line, 23 решения Р1–Р23, §11 кампании).
- `PLAN-universal-dog-app.md` v2 — план функционалност по функционалност с TDD система (§0), Фаза 0, карти F0–F17.
- `LESSONS-LEARNED-beagle-owner-2026-09.md` — 24 урока с доказателства.
- `tools/claude-hooks/` — `guard_git.sh` (без комит на main), `prompt_guard.sh`, `memory_mechanism_check.sh`; инсталирани от Ив.
- `/Users/iv/Documents/Development/MyBeagle/store/` — `apple-review-reply-2026-09-07.md`, `-10.md` (отговорите към Apple), листинги, скрийншоти; `docs/legal/` — правни документи × 18 (огледално копие в `MyBeagleApi/app/modules/legal/docs` — дума по дума еднакви).

## 5. Важни решения и защо

- **Едно приложение за всички породи** — Apple 4.3(a): „Don't create multiple Bundle IDs of the same app… If your app has different versions for specific locations, sports teams, universities, etc., consider submitting a single app“; Play терминира „individual or related“ акаунти.
- **Общ бекенд**, породата на кучето, идентичността от ръба; нито един `if app_key ==` в service слоя.
- **Един абонамент на човек** (Apple 3.1.2(a) го позволява между собствени приложения); „Manage subscription“ само при съвпадение магазин + платформа (3.1.3(b)).
- **Съдържанието като файлове в git**, сервирани от API-то. Отхвърлени: CMS/OTA таблици (втора система за доставка при един поддържащ), форк на клиента (двойни поправки), flavors по порода (пак 4.3).
- **Миграция без копиране** (същият акаунт). Отхвърлен: import с idempotency ключове.
- **Trial точно 30 дни от хъба**; никаква стор оферта (30 + 30 = 60 беше грешката от 09.09). Промени в магазините (оферти, цени, продукти) само с думата на Ив; черновата е ок.
- **Правило без механизъм не е мярка**: всяко правило в паметта носи ред „Механизъм:“ (тест/хук/скрипт).
- Тестове: „минават / не минават“, никога „падат“; дефект = регресионен тест, който не минава върху стария код; SemVer (PATCH само при фиксиран дефект); всички 18 езика винаги, вкл. писма, push, native ресурси; една стъпка наведнъж към Ив; без оценки за време; всичко в EUR.

## 6. PR #10, отворени задачи, известни капани

- Единственият „PR #10“ в паметта: Control Center (Cockpit) — fx събирач по дневния курс на ЕЦБ, конверсия преди агрегация. Няма PR #10 в кучешките репота.
- Отворени задачи по Beagle Owner (след одобрението на Apple): snapshot на името на родителя в родословието при изтриване на родител; 6 тестови `@example.com` акаунта в production за изтриване; UCrop portrait lock в манифеста; edge-to-edge на Android 15; цената на екрана за абонамент да идва от StoreKit; 23 `catch (_)` без лог и 27 сурови `e.message` в клиента; факти на 9 от 18 езика.
- Капани в кода: sync създава дубликат куче при повторен POST (няма `client_dog_id`); tombstones не пазят от възкресяване; ЕС паспортът живее само в телефона; App Store Server API дава 401 в production до публикуване (sandbox работи).

## 7. Пазар

Няма формален конкурентен анализ. Целеви пазар: ЕС + света (173 държави); UI копи English-first, локализирано на 18 езика; валута EUR (България е в еврозоната от 01.01.2026). Първи реални потребители: двама. Маркетинг по порода: Facebook групи → `go.heppsu.com/<breed>` → CPP/CSL (`ARCHITECTURE-universal-dog-app.md` §11).

## 8. Поуки и какво да преизползваш

- **Преизползвай:** бекенда изцяло (не втори), хъба за абонаменти, `deploy.sh` с tested/ гейта, legal модула, moderation/visibility предиката (след като стане слой), ARB инфраструктурата и l10n тестовете, скриптовете за ASC/Play API (описани в `reference-store-api-procedures.md`).
- **Най-скъпите поуки:** платежната верига стигна до двата стора без нито една реална покупка (тествай границата с истински подписан вход, не със стъб; App Review купува в SANDBOX); „готово“ по зелени тестове без екран на устройство (5 резолюции преди всеки билд към Ив); билд, който вика ендпойнт, какъвто средата няма (гейт към живия `/openapi.json`); локализацията се проверява по СЪДЪРЖАНИЕ, не по ключове (Guideline 4 отказ за български purpose strings); IAP се подава ЗАЕДНО с версията (3 елемента; Resubmit след отказ само от UI); връзки към Условия и Политика в описанието на стора (3.1.2, автоматична проверка); демо акаунтът за Apple трябва да влиза в PRODUCTION; unacknowledged Play покупка = refund след 3 дни; комити на main — hook ги отказва; версии без връзка към git (65 версии за 78 билда) — уникален номер от таг; никакви тестове върху реалните имейли/акаунти на Ив.
- Пълният списък с механизмите: `PLAN-universal-dog-app.md` §0 и `LESSONS-LEARNED-beagle-owner-2026-09.md` §2.
