# Инфраструктура

Production сървър: Contabo VPS, Ubuntu 24.04 LTS, 6 vCPU / 11 GB RAM / 193 GB.

## Среди

| Среда | Директория | Compose project | Порт | `ENVIRONMENT` |
|---|---|---|---|---|
| production | `/srv/aifos/prod` | `aifos-prod` | 80 / 443 | `production` |
| pre-prod | `/srv/aifos/preprod` | `aifos-preprod` | 8080 / 8443 | `staging` |
| demo | `/srv/aifos/demo` | `aifos-demo` | 8081 / 8444 | `staging` |

Трите среди се вдигат от **един и същ** `docker-compose.yml`. Разликите са само в
`.env` — така pre-prod тества точно конфигурацията, която отива в production.

`ENVIRONMENT` на демото е `staging`, а не `demo`: само стойност от
`PRODUCTION_ENVIRONMENTS` (`config.py`) включва fail-fast проверката, която отказва
стартиране с `SECRET_KEY` по подразбиране. Демото е публично достъпно и трябва да е
под същата защита.

**Демо средата не се бекъпва умишлено.** `backup.sh` приема само `prod` и `preprod`.
Демото съдържа само измислени данни и се пресъздава от нулата всяка нощ — бекъпът му
би бил само още едно място, където случайно попаднали реални данни оцеляват.

Подредба на всяка среда:

```
/srv/aifos/<env>/
├── .env        тайни (600) — извън release/, за да преживее rsync --delete
├── release/    кодът, разархивиран от git таг
├── storage/    оригиналните сканирани документи
└── backups/    дъмпове на базата
```

## Достъп

```bash
ssh heppsu           # root, само за администриране на машината
ssh heppsu-deploy    # deploy, стопанин на приложението
```

Вход само с ключове. Паролите са изключени, root не приема парола, `AllowUsers`
пуска само `root` и `deploy`. Ако достъпът се загуби: панелът на Contabo →
*Reset credentials* → таб *SSH-Key* инжектира нов публичен ключ.

## Деплой

```bash
./infra/deploy.sh preprod            # текущият HEAD към pre-prod
./infra/deploy.sh demo               # текущият HEAD към демо средата
./infra/deploy.sh prod v1.0.0        # конкретен таг към production
```

Деплойва се **само от git ref**, никога от работната директория — иначе в
production попада некомитнат или чужд код. За production скриптът отказва да
работи при мръсно работно дърво.

Какво прави наред:

1. Проверява ref-а и чистотата на дървото.
2. Пуска пазача на миграциите (`ci/check_migrations.py`).
3. Прави `git archive` от ref-а и го качва.
4. При първо пускане на средата генерира `.env` с нов `SECRET_KEY` и парола за базата.
5. **Бекъпва базата** и спира, ако бекъпът е празен или повреден.
6. Строи образа, пуска миграциите, вдига стека.
7. Health gate: при неуспех връща предишния образ и предупреждава за базата.

## Защити срещу загуба на данни и срив

| Механизъм | Файл | Кога |
|---|---|---|
| Пазач на разрушителни миграции | `ci/check_migrations.py` | CI + всеки деплой |
| Тестове срещу PostgreSQL | `ci/test-postgres.sh` | CI |
| Репетиция върху копие на реалната база | `ci/rehearse-migrations.sh` | преди production |
| Smoke тестове срещу разгърнатата среда | `ci/smoke.py` | след всеки деплой |
| Бекъп преди миграции | `deploy.sh` | всеки деплой |
| Нощен бекъп с проверка за цялост | `backup.sh` | 03:00 |
| Връщане на предишния образ | `deploy.sh` | при провален health check |
| Схемата от миграциите има очакваните DEFAULT-и | `tests/test_migrations_schema.py` | CI |

Разрушителна миграция минава само с изричен подпис във файла:

```python
# ALLOW-DESTRUCTIVE: колоната е дублирана от `x`, данните са мигрирани на 2026-07-01
```

**Важно за връщането назад.** Кодът се връща автоматично, базата — не.
Ако миграция е минала и после кодът се е върнал, схемата остава напред. Затова
редът е: репетиция → бекъп → миграция. Възстановяване:

```bash
gunzip -c backups/pre-deploy-<стамп>.sql.gz | \
  docker compose -p aifos-prod -f release/infra/docker-compose.yml \
    --project-directory . --env-file .env exec -T db psql -U aifos -d aifos
```

## Нощен бекъп

```bash
ssh heppsu-deploy 'crontab -l'
# 0  3 * * *  backup.sh prod
# 30 3 * * *  backup.sh preprod
# 0  4 * * *  demo/recreate.sh      ← пресъздава демото от нулата
```

14 дневни + 8 седмични копия, с проверка че дъмпът не е празен и архивът не е
повреден. **Това не е архив извън машината.** Преди реална работа е задължително
копие на друго място — при загуба на VPS-а тези бекъпи изчезват заедно с него.

## HTTPS

Сега работи само на HTTP по IP. За сертификат трябва домейн, насочен към
`169.58.72.254`. След това:

```bash
ssh heppsu-deploy
cd /srv/aifos/prod
docker compose -p aifos-prod -f release/infra/docker-compose.yml \
  --project-directory . --env-file .env run --rm certbot \
  certonly --webroot -w /var/www/certbot -d ДОМЕЙН --agree-tos -m ПОЩА --no-eff-email
```

После в `release/infra/nginx/conf.d/aifos.conf` се разкоментира HTTPS блокът и
пренасочването, домейнът се попълва и nginx се презарежда. Подновяването е
автоматично (certbot контейнерът проверява на 12 часа).

## CI/CD

| Поток | Файл | Какво прави |
|---|---|---|
| API | `.github/workflows/api.yml` | линтер + тестове на SQLite + миграции от нула |
| Интеграция | `.github/workflows/integration.yml` | тестове срещу PostgreSQL, пазач на миграциите, bandit, pip-audit |
| Деплой | `.github/workflows/deploy.yml` | main → pre-prod → smoke → (одобрение) → production от таг |

Нужни secrets: `DEPLOY_SSH_KEY`, `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_KNOWN_HOSTS`.
Средата `prod` в настройките на хранилището трябва да изисква ръчно одобрение.

## Какво още не е направено

- HTTPS (чака домейн).
- Архив извън сървъра.
- Наблюдение и известяване при срив (сега няма нищо — падне ли API-то, ще се
  разбере при следващото влизане).
- Политика за ретеншън на данните (GDPR × ЗСч) — виж `docs/BACKLOG.md`.
- Защита пред pre-prod: средата е публично достъпна с отворена регистрация.
