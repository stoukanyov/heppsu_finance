# Инфраструктура

Две машини в Contabo, Ubuntu 24.04 LTS. Кръстени са на спътниците на Марс —
по-големият и по-близкият носи името на по-големия спътник:

| Машина | Contabo план | Ресурси | IP | Роля |
|---|---|---|---|---|
| **Phobos** | Cloud VPS 6 | 6 vCPU / 12 GB / 200 GB | `169.58.72.254` | production — само данните на клиенти |
| **Deimos** | Cloud VPS 4 | 4 vCPU / 8 GB / 100 GB | `169.58.90.87` | всичко останало: pre-prod, demo, Availo dev |

И двете са с Auto Backup от доставчика (снимка на цялата машина, дневно).
Тя връща машината към снощи; дъмпът преди миграция в `deploy.sh` е за връщане
на конкретна операция и остава нужен.

## Среди

| Среда | Машина | Директория | Compose project | Порт | `ENVIRONMENT` |
|---|---|---|---|---|---|
| production | Phobos | `/srv/aifos/prod` | `aifos-prod` | 80 / 443 | `production` |
| pre-prod | Deimos | `/srv/aifos/preprod` | `aifos-preprod` | 8080 / 8443 | `staging` |
| demo | Deimos | `/srv/aifos/demo` | `aifos-demo` | 8081 / 8444 | `staging` |

> Преместването на pre-prod и demo върху Deimos още не е направено — и двете
> вървят на Phobos. Виж „Разделяне на средите“ по-долу.

Трите среди се вдигат от **един и същ** `docker-compose.yml`. Разликите са само в
`.env` — така pre-prod тества точно конфигурацията, която отива в production.

`ENVIRONMENT` на демото е `staging`, а не `demo`: само стойност от
`PRODUCTION_ENVIRONMENTS` (`config.py`) включва fail-fast проверката, която отказва
стартиране с `SECRET_KEY` по подразбиране. Демото е публично достъпно и трябва да е
под същата защита.

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
| Дъмп преди миграции | `deploy.sh` | всеки деплой |
| Връщане на предишния образ | `deploy.sh` | при провален health check |
| Схемата от миграциите има очакваните DEFAULT-и | `tests/test_migrations_schema.py` | CI |

Разрушителна миграция минава само с изричен подпис във файла:

```python
# ALLOW-DESTRUCTIVE: колоната е дублирана от `x`, данните са мигрирани на 2026-07-01
```

**Важно за връщането назад.** Кодът се връща автоматично, базата — не.
Ако миграция е минала и после кодът се е върнал, схемата остава напред. Затова
редът е: репетиция → дъмп → миграция. За възстановяване виж „Бекъпи" по-долу.

## Бекъпи

**Няма собствен режим за бекъпи.** Планът при хостинг доставчика прави автоматични
копия на машината и това е източникът за възстановяване при загуба на сървъра.

Единственото, което системата пази сама, е **дъмп непосредствено преди миграции**
(`deploy.sh`, в `backups/` на средата). Той не е бекъп режим, а точка за връщане
за конкретна рискова операция: снимката на машината от снощи не помага, ако
миграция в 14:00 е повредила данни — с нея се губи целият ден. Дъмповете се
пазят последните 10 и се чистят автоматично.

Възстановяване от такъв дъмп:

```bash
gunzip -c backups/pre-deploy-<стамп>.sql.gz | \
  docker compose -p aifos-prod -f release/infra/docker-compose.yml \
    --project-directory . --env-file .env exec -T db psql -U aifos -d aifos
```

Cron съдържа само пресъздаването на демото:

```bash
ssh heppsu-deploy 'crontab -l'
# 0 4 * * *  demo/recreate.sh
```

## HTTPS

Домейнът е `heppsu.com`. Разпределението е:

| Име | Какво обслужва |
|---|---|
| `heppsu.com`, `www.heppsu.com` | презентационният сайт (статични файлове) |
| `app.heppsu.com` | AI Finance OS |
| по IP | AI Finance OS — `default_server`, за да не се чупят pre-prod, demo и мобилното приложение |

`conf.d/aifos.conf` е общ за всички среди и нарочно **не знае за домейна**.
Именуваните хостове и TLS се пускат само на production, като файл в
`/srv/aifos/prod/nginx-extra/`, който `aifos.conf` включва с
`include /etc/nginx/extra/*.conf;`. Празна директория не е грешка — затова
pre-prod и demo вървят непроменени.

### Ред на пускане

1. **DNS**: `heppsu.com`, `www` и `app` → A запис `169.58.72.254`.
   MX и TXT записите на пощата не се пипат.
2. **Сайтът на сървъра** (от репото `heppsu_website`): `./deploy.sh` там, или
   ```bash
   rsync -av --delete --exclude '.git' --exclude 'docs' \
     ./ heppsu-deploy@169.58.72.254:/srv/aifos/prod/website/
   ```
3. **Хостовете по HTTP** — още без сертификат, за да може certbot да мине:
   ```bash
   scp infra/nginx/sites-available/heppsu-http.conf \
     heppsu-deploy@169.58.72.254:/srv/aifos/prod/nginx-extra/heppsu.conf
   ssh heppsu-deploy 'cd /srv/aifos/prod && docker compose -p aifos-prod \
     -f release/infra/docker-compose.yml --project-directory . --env-file .env \
     up -d nginx && docker compose -p aifos-prod -f release/infra/docker-compose.yml \
     --project-directory . --env-file .env exec nginx nginx -t'
   ```
   Провери: `curl -I http://heppsu.com` → 200, `curl -I http://app.heppsu.com/api/v1/health` → 200.
4. **Сертификат** за трите имена наведнъж (един сертификат, `heppsu.com` е основното):
   ```bash
   ssh heppsu-deploy
   cd /srv/aifos/prod
   docker compose -p aifos-prod -f release/infra/docker-compose.yml \
     --project-directory . --env-file .env run --rm certbot \
     certonly --webroot -w /var/www/certbot \
     -d heppsu.com -d www.heppsu.com -d app.heppsu.com \
     --agree-tos -m info@heppsu.com --no-eff-email
   ```
   Пробвай първо със `--dry-run`: Let's Encrypt ограничава до 5 неуспешни опита на час.
5. **HTTPS**: същият файл се заменя с TLS вариантa и nginx се презарежда.
   ```bash
   scp infra/nginx/sites-available/heppsu-tls.conf \
     heppsu-deploy@169.58.72.254:/srv/aifos/prod/nginx-extra/heppsu.conf
   ssh heppsu-deploy 'cd /srv/aifos/prod && docker compose -p aifos-prod \
     -f release/infra/docker-compose.yml --project-directory . --env-file .env \
     exec nginx nginx -s reload'
   ```
   Ако сертификатът липсва, nginx **не тръгва** — файлът сочи към несъществуващи
   пътища. Затова стъпка 5 идва след стъпка 4, не преди нея.

Подновяването е автоматично (certbot контейнерът проверява на 12 часа).

След като HTTPS работи, в мобилното приложение се сменя адресът от IP на
`https://app.heppsu.com`, връща се ATS ограничението в `Info.plist` и се
попълват `CERT_PINS`.

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
- Наблюдение и известяване при срив (сега няма нищо — падне ли API-то, ще се
  разбере при следващото влизане).
- Политика за ретеншън на данните (GDPR × ЗСч) — виж `docs/BACKLOG.md`.
- Защита пред pre-prod: средата е публично достъпна с отворена регистрация.

## Разделяне на средите (предстои)

Днес Phobos носи и четирите стека: `aifos-prod`, `aifos-preprod`, `aifos-demo` и
`availo-dev`. Капацитетът стига (1,9 GB от 11 GB, натоварване 0,4 при 6 ядра) —
причината за разделянето не е мощност, а **обхват на щетата**:

- демото е нарочно публично и то е това, което непознати ще ръчкат;
- изтощена от seed или миграция машина не бива да влачи със себе си базата с
  клиентски счетоводни данни;
- след преместването на Phobos остават отворени само 22, 80 и 443.

Редът е: `provision.sh` върху Deimos → пренасяне на `preprod`, `demo` и
`availo-dev` → затваряне на 8080/8443, 8081/8444 и 8090 в `ufw` на Phobos.
