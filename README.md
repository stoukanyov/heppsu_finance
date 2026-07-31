# AI Finance OS

AI-базирана финансова операционна система за управление на компании.
Счетоводството е ядрото, върху което се изграждат автоматизация, анализ, данъчен контрол,
прогнозиране и AI препоръки. Първоначален фокус: българско ДДС-регистрирано юридическо лице,
базова валута EUR, мултивалутност, приходи от Apple App Store / Google Play.

> Изискванията са дефинирани в master prompt-а на продукта (виж `docs/`). Този репозиторий е
> имплементацията, изграждана на вертикални срезове (MVP-first).

## Технологичен стек

| Слой | Технология |
|---|---|
| Backend API | Python 3.14 · FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 |
| База данни | PostgreSQL (prod) · SQLite (локален dev) |
| Web (по-късно) | React · Vite · TypeScript |
| Mobile (по-късно) | Flutter |
| Deploy | Docker Compose → Kubernetes-ready |

## Архитектура

Modular monolith с Domain-Driven Design. Всеки bounded context е отделен модул в
`apps/api/app/modules/`. Приоритет: API-first, Auditability by default, Human control за
критични действия. AI никога не осчетоводява окончателно и не одобрява само себе си.

Bounded contexts (пътна карта): Identity & Access · Companies (Tenant) · Accounting ·
Tax & VAT · Documents · OCR · Banking · Payments · Reporting · AI · Notifications ·
Workflows · Audit · Integrations · Subscriptions · Billing.

## Локален старт (без Docker)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r apps/api/requirements.txt
cd apps/api
uvicorn app.main:app --reload
```

API: http://127.0.0.1:8000 · Swagger: http://127.0.0.1:8000/docs

## Web UI (вграден, без Node)

Има вграден Single-Page интерфейс, сервиран директно от FastAPI (същия origin — без CORS,
без build стъпка). След стартиране на API-то отвори:

**http://127.0.0.1:8000/app/**

Покрива: вход/регистрация, избор на компания, AI Command Center (KPI + AI преглед),
счетоводство (сметкоплан, фискална година, нова операция, оборотна ведомост), документи
(качване + AI извличане), банки (сметки, импорт, автоматично съпоставяне).

> Пълноценен React + Vite + TypeScript frontend е планиран за когато има инсталиран Node;
> API-то е идентично. Засега вграденото UI е самостоятелно (vanilla JS) и не изисква нищо.

По подразбиране се ползва локален SQLite файл и таблиците се създават автоматично
(`AUTO_CREATE_TABLES=true`). За PostgreSQL задай `DATABASE_URL` и изключи авто-създаването
(миграциите се управляват с Alembic).

## Миграции (Alembic)

Схемата в production се управлява с Alembic (не с авто-създаване):

```bash
cd apps/api
alembic upgrade head          # прилага миграциите
alembic revision --autogenerate -m "описание"   # нова миграция след промяна в моделите
```

`docker compose up` автоматично изпълнява `alembic upgrade head` преди старта на API-то.
Новите модели трябва да се импортират в `app/db/registry.py`, за да ги вижда autogenerate.

## Тестове

```bash
cd apps/api
pytest -q
```

## Definition of Done

Функционалност се смята за завършена, когато:

1. има **unit тестове** и документация **в кода** (обяснява ЗАЩО и каква повреда пази) и
   **в този README**;
2. всичко, което стига до production, е минало през **CI** с трите проверки по-долу;
3. всеки намерен проблем има **тест, кръстен на повредата** — за да не бъде „оправен“ обратно.

Тестовете от точка 3 живеят в `apps/api/tests/test_infra_guardrails.py`. Всеки от тях
започва с описание на дефекта, който е причината да съществува.

## CI — какво пази какво

Три потока в `.github/workflows/`:

| Поток | Кога | Какво прави |
|---|---|---|
| `api.yml` | всяко бутане и PR | бърза обратна връзка: линтер + тестове на SQLite + миграции от нула |
| `integration.yml` | всяко бутане, PR и **портата на деплоя** | пълният набор срещу PostgreSQL, статичен анализ, динамичен анализ, пазач на миграциите |
| `deploy.yml` | таг / ръчно | разгръща — но само след зелен `integration.yml` |

`deploy.yml` вика `integration.yml` с `uses:`. Затова проверка, която трябва да пази
production, се добавя **в `integration.yml`**: проверка извън портата не пази нищо,
тя само оцветява значка.

**Статичен анализ** — кодът се чете, без да се изпълнява:

* `ruff` с правила за грешки, не за стил. Изборът е нарочно тесен — стотици
  предупреждения за подредба погребват трите, които значат нещо. Правилата и
  причината за **всяко** изключение са в `apps/api/ruff.toml` (кодът на API-то) и
  `ruff.toml` в корена (скриптовете в `infra/`, които се пускат срещу production).
* `bandit --severity-level medium` върху `apps/api/app`, `apps/api/scripts` и `infra`.
* `pip-audit` върху `requirements.txt` — уязвими зависимости.

**Динамичен анализ** — приложението наистина се вдига срещу временна PostgreSQL база
(схема от Alembic, както в production) и му се задават въпроси на живо: отговаря ли
`/health`, достъпна ли е базата, закачили ли са се маршрутите, получава ли непознат
`401`. Това хваща класа грешки, който при четене на код изглежда напълно наред:
рутер, който не се е регистрирал след разместване на импорти, или защита, която
съществува, но не е закачена за маршрута.

### Пускане локално

```bash
# статичен анализ (същите команди като в CI)
.venv/bin/ruff check apps/api infra
.venv/bin/bandit -q -r apps/api/app apps/api/scripts infra --severity-level medium

# целият набор тестове
cd apps/api && ../../.venv/bin/pytest -q

# същите тестове срещу PostgreSQL, както в CI
TEST_DATABASE_URL=postgresql+psycopg://test:test@localhost:5432/aifos_test \
  ../../.venv/bin/pytest -q

# динамичен анализ на живо: вдигни приложението и го питай
uvicorn app.main:app --port 8000 &
curl -fsS http://127.0.0.1:8000/api/v1/health
curl -fsS http://127.0.0.1:8000/openapi.json | python -c "import json,sys;print(len(json.load(sys.stdin)['paths']),'маршрута')"
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/v1/companies   # очаква се 401
```

Срещу вече разгърната среда се пуска `python infra/ci/smoke.py <адрес>`
(в production — задължително с `--read-only`: пълните проверки създават записи).

## Дати и часова зона

Никъде в кода не се вика `date.today()`. Той връща деня по часовника на **машината**,
а production сървърът работи в UTC — между 00:00 и 03:00 софийско време това е
**друг ден**. Сторно, осчетоводено в 00:30 на 1 август, така получава дата 31 юли и
влиза в юлския ДДС дневник, чиято декларация може вече да е подадена.

Вместо това се ползва `app.core.clock.business_today()`, който брои дните в зоната на
фирмата (`BUSINESS_TIMEZONE`, по подразбиране `Europe/Sofia`). Правилото се пази от
две страни: правилото `DTZ` на линтера и тест, който обхожда изходния код.

## Статус

Виж [STATUS.md](STATUS.md) за текущия прогрес по фазите и регистъра на решенията.
