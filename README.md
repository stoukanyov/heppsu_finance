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

## Статус

Виж [STATUS.md](STATUS.md) за текущия прогрес по фазите и регистъра на решенията.
