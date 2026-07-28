# Инфраструктура

> **Стопанин на този файл: DevOps сесията.** Инфраструктурата (сървъри, Docker,
> nginx, TLS, ufw, cron, бекъпи, деплой скриптове, CI потоци) се променя през нея.
> Продуктовите сесии описват какво им трябва; промяната по `infra/`, `.github/`
> и по самите машини минава оттам. Причината е конкретна: тези файлове описват
> **две живи машини с клиентски счетоводни данни**, а редакция „на място“ от
> сесия, която не вижда целия стек, вече е чупила деплоя (виж „Известни счупвания“).
>
> Състоянието по-долу е **проверено на живо на 28 юли 2026, 23:30 EEST**.

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

Преместването е **направено** (28 юли 2026). Проверено: на Phobos върви само
`aifos-prod`; на Deimos вървят `aifos-preprod`, `aifos-demo` и `availo-dev`.
На Phobos са останали празните директории `/srv/aifos/preprod` и `/srv/aifos/demo`
със стар `release/` (v1.0.1-8-g308bc0c) — нищо не ги вдига, но чакат разчистване.

### Какво върви в момента (28 юли 2026, 23:30 EEST)

| Стек | Машина | Версия | Състояние |
|---|---|---|---|
| `aifos-prod` | Phobos | **v1.1.1** | db, api (healthy), nginx, certbot — работят |
| `aifos-preprod` | Deimos | v1.1.1-3-g22965f0 | работи, публично на 8080 |
| `aifos-demo` | Deimos | v1.1.1 | работи, публично на 8081 |
| `availo-dev` | Deimos | — (репо, клон `main`) | работи, публично на 8090 |

Заетост: Phobos 7,5 GB от 193 GB диск, 1,2 GB от 11 GB памет, натоварване 0,08.
Deimos 5,0 GB от 96 GB, 1,2 GB от 7,8 GB, натоварване 0,64. Мощността не е проблем
на нито една от двете.

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
ssh heppsu           # Phobos, root, само за администриране на машината
ssh heppsu-deploy    # Phobos, deploy, стопанин на приложението

# Deimos — засега БЕЗ псевдоним в ~/.ssh/config:
ssh -i ~/.ssh/id_heppsu_srv deploy@169.58.90.87
ssh -i ~/.ssh/id_heppsu_srv root@169.58.90.87
```

> **Псевдонимите `phobos-deploy` и `deimos-deploy`, които `deploy.sh` очаква, не
> съществуват в `~/.ssh/config`.** Заради това деплой скриптът пада още на първия
> `ssh`. Виж „Известни счупвания“ — това е първото, което трябва да се оправи.

Вход само с ключове. Паролите са изключени, root не приема парола, `AllowUsers`
пуска само `root` и `deploy`. Ако достъпът се загуби: панелът на Contabo →
*Reset credentials* → таб *SSH-Key* инжектира нов публичен ключ.

## Клонове и среди

| Реф | Среда | Машина | Кой го пуска |
|---|---|---|---|
| `dev` (HEAD) | pre-prod | Deimos | CI при push в `dev`, или ръчно |
| `main` | — | — | main е само подготовка за издание; от него се режат таговете |
| таг `vX.Y.Z` | production | Phobos | CI при таг, след ръчно одобрение |
| таг `vX.Y.Z` | demo | Deimos | ръчно, когато демото трябва да е ново |

Правилото е едно изречение: **на Phobos влиза само таг, а таг се реже само от
`main`.** Всичко останало живее на Deimos.

**Демото НЕ следва `dev`.** То е това, което се показва на клиенти, затова се
деплойва от същия таг, който е в production (или от предишния). Ако демото
проследяваше `dev`, един счупен комит в средата на деня щеше да проваля
демонстрация пред клиент — а точно това е средата, чиято единствена задача е да
не се чупи пред външен човек. Pre-prod е мястото, където `dev` има право да е
счупен.

Пътят на една промяна:

```
клон dev ──push──▶ CI: линтер, тестове, миграции от нула
                   └─▶ deploy.sh preprod  (Deimos, порт 8080)
                        └─ ръчна проверка
                             └─▶ merge dev → main
                                  └─▶ git tag vX.Y.Z
                                       └─▶ CI: одобрение
                                            └─▶ deploy.sh prod vX.Y.Z (Phobos)
                                                 └─▶ deploy.sh demo vX.Y.Z (Deimos)
```

Машината не се подава на ръка — `deploy.sh` я извежда от името на средата
(`prod` → `phobos-deploy`, `preprod` и `demo` → `deimos-deploy`). Така
„деплой на preprod" не може случайно да отиде на production сървъра.

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

### Какво реално има в cron (проверено)

| Машина | Потребител | Ред |
|---|---|---|
| Phobos | `deploy` | `30 4 * * * docker exec aifos-prod-nginx-1 nginx -s reload` (зареждане на подновения сертификат) |
| Phobos | `root` | празен |
| Deimos | `deploy` | `0 4 * * * /srv/aifos/demo/release/infra/demo/recreate.sh` |
| Deimos | `root` | празен |

**Ежедневният дъмп на production е спрял.** Последният е
`backups/daily/prod-20260726-030001.sql.gz` от 26 юли 03:00. Скриптът, който го е
правил, съществува само в `/srv/aifos/_legacy/infra/backup.sh` — в текущото репо
няма `infra/backup.sh`, а редът за него е изчезнал от crontab-а на `deploy` на
Phobos. Тоест днес production се пази само от дневната снимка на Contabo и от
дъмпа при деплой. Виж „Известни счупвания“.

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

**Всички стъпки са изпълнени на 28 юли 2026. HTTPS работи.** Проверено:

| Проверка | Резултат |
|---|---|
| DNS `heppsu.com`, `www`, `app` | → `169.58.72.254` |
| `https://heppsu.com` | 200, валидна верига |
| `http://heppsu.com` | 301 → `https://heppsu.com/` |
| `https://app.heppsu.com/api/v1/health` | `{"status":"ok","environment":"production"}` |
| Сертификат | Let's Encrypt, един за трите имена, издаден 28.07.2026, валиден до **26.10.2026** |

Стъпките остават описани по-долу като процедура за повторно пускане.

1. **DNS**: `heppsu.com`, `www` и `app` → A запис `169.58.72.254`.
   MX и TXT записите на пощата не се пипат.
2. **Сайтът на сървъра** (от репото `heppsu_website`): `./deploy.sh` там, или
   ```bash
   rsync -av --delete --exclude '.git' --exclude 'docs' \
     ./ heppsu-deploy:/srv/aifos/prod/website/
   ```
3. **Хостовете по HTTP** — още без сертификат, за да може certbot да мине:
   ```bash
   scp infra/nginx/sites-available/heppsu-http.conf \
     heppsu-deploy:/srv/aifos/prod/nginx-extra/heppsu.conf
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
     --project-directory . --env-file .env run --rm --entrypoint certbot certbot \
     certonly --webroot -w /var/www/certbot \
     -d heppsu.com -d www.heppsu.com -d app.heppsu.com \
     --agree-tos -m info@heppsu.com --no-eff-email
   ```
   Пробвай първо със `--dry-run`: Let's Encrypt ограничава до 5 неуспешни опита на час.

   **`--entrypoint certbot` е задължителен.** Без него `run` наследява entrypoint-а
   от compose файла (цикъла за подновяване), подадената команда се игнорира и
   контейнерът просто заспива — изглежда като „виси мрежата“, а не е.
5. **HTTPS**: същият файл се заменя с TLS вариантa и nginx се презарежда.
   ```bash
   scp infra/nginx/sites-available/heppsu-tls.conf \
     heppsu-deploy:/srv/aifos/prod/nginx-extra/heppsu.conf
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

**CI днес не е пускан по това състояние.** Локалният `dev` е с **42 комита пред
`origin/dev`** — нищо от инфраструктурната работа не е избутано, значи нито един
от трите потока не е виждал този код. Освен това `deploy.yml` пише в `~/.ssh/config`
само псевдонима `heppsu-deploy`, а `deploy.sh` търси `phobos-deploy`/`deimos-deploy` —
дори да се избута, деплой job-ът ще падне.

## Известни счупвания (към 28 юли 2026)

Подредени по това колко бързо болят:

1. **`deploy.sh` не може да стигне до нито една машина.** Търси псевдоними
   `phobos-deploy` / `deimos-deploy`, каквито няма нито в `~/.ssh/config`, нито в
   `deploy.yml` на CI. Заобикаля се с `AIFOS_HOST=…`, но това е точно променливата,
   която случайно праща preprod деплой към production сървъра — тя е за CI, не за ръка.
2. **Production няма ежедневен бекъп от 26 юли.** Останало е само дневното копие
   на цялата машина от Contabo и дъмпът, който `deploy.sh` прави преди миграции.
   Между двете има до 24 часа дупка върху счетоводни данни, които по ЗСч се пазят 10 г.
3. **Публикуваните от Docker портове минават покрай `ufw`.** На Deimos `ufw` няма
   правило за 8090, а `http://169.58.90.87:8090` отговаря 200 отвън — Docker пише
   правилата си в `DOCKER-USER`, преди веригите на ufw. Значи pre-prod (8080),
   demo (8081) и Availo dev (8090) са публични, и това *не* се управлява от ufw.
4. **`docs/DEPLOY.md` описва инфраструктура, която не съществува** (Caddy,
   `/opt/ai-finance-os`, `git pull` на сървъра). Файлът е отбелязан като остарял.
5. **Остатъци на Phobos:** `/srv/aifos/preprod` и `/srv/aifos/demo` с код от
   v1.0.1 и техните Docker volume-и след преместването върху Deimos.

## Какво още не е направено

- Наблюдение и известяване при срив (сега няма нищо — падне ли API-то, ще се
  разбере при следващото влизане). Това е най-голямата останала дупка: HTTPS,
  бекъпите и деплоят вече имат кой да ги счупи тихо.
- Собствен режим за бекъпи, който е част от репото, а не от `_legacy`.
- Политика за ретеншън на данните (GDPR × ЗСч) — виж `docs/BACKLOG.md`.
- Защита пред pre-prod: средата е публично достъпна с отворена регистрация.
- Псевдоними `phobos*` / `deimos*` в `~/.ssh/config` (файлът не е достъпен за
  редакция от Claude сесия — прави се на ръка).

## Разделяне на средите (направено)

Phobos вече носи само `aifos-prod`; `aifos-preprod`, `aifos-demo` и `availo-dev`
са на Deimos. Причината не беше мощност, а **обхват на щетата**:

- демото е нарочно публично и то е това, което непознати ще ръчкат;
- изтощена от seed или миграция машина не бива да влачи със себе си базата с
  клиентски счетоводни данни;
- на Phobos вече са отворени само 22, 80 и 443 (проверено с `ufw status`).

Остава разчистването на старите директории и volume-и на Phobos.
