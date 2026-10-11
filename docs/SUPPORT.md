# Докладване от потребителя → Control Center

„Съобщи проблем“ в уеб интерфейса: дефект, инцидент или предложение за
подобрение. Докладът се записва в базата на AI Finance OS и се препраща като
тикет към Control Center (`cockpit.heppsu.com`, модул тикети). Без тази функция
Definition of Done (`infra/dod.yml`, т. 1) отказва всеки production деплой.

Код: `apps/api/app/modules/support/` · уеб: `openSupportReport()` в
`apps/api/app/web/index.html` · тестове: `tests/test_support.py`,
`tests/test_support_web.py`, `tests/test_infra_deploy_gates.py`.

## Пътища

| | вход | какво прави |
|---|---|---|
| `POST /api/v1/support/report` | Bearer токен (влязъл потребител) | записва доклада, веднага опитва да го препрати |
| `GET /api/v1/support/config` | без вход | `{"configured": true\|false}` — настроено ли е препращането; стойностите не излизат |

Тяло на доклада:

```json
{"category": "bug", "subject": "3..200 знака", "message": "1..3500 знака", "page": "по избор, до 200"}
```

`category` е речникът на Control Center без превод: `bug` (дефект), `incident`
(нещо не работи сега), `recommendation` (предложение). Темата и текстът се
изрязват; само интервали е 422. `X-Company-Id` по избор — дружеството се
закача само ако потребителят е член в него.

Отговор `201`:

```json
{"id": "…", "forwarded": true, "status": "sent", "reference": "T-000123"}
```

`201` значи „записан при нас“. `forwarded` казва дали е стигнал до Control
Center. При `forwarded: false` (`status: pending`) уебът казва „Приехме доклада,
ще бъде препратен“ — **не** „изпратено“. `status: rejected` значи, че Control
Center е отказал съдържанието (400/422); докладът остава в базата за ръчен
преглед. Таван: `SUPPORT_REPORT_RATE_LIMIT` доклада за
`SUPPORT_REPORT_RATE_WINDOW_SECONDS` от един потребител → 429.

## Договорът с Control Center

От кода на Control Center (`app/api/tickets.py`, origin/main `6b4ec2d598e6`,
11.10.2026), не от предположение:

```
POST {COCKPIT_URL}/api/tickets
X-App-Token:    токенът на системата — aifos (prod) / aifos-preprod (preprod)
X-Submitter-IP: адресът на крайния подател
тяло:           TicketIn {category, title 3..200, body 1..4000, contact ≤320}
отговор:        201 {"reference": "T-000123", "status": "new"}
```

- `title` = темата; `body` = текстът + контекст в края (екран, дружество,
  среда, `AIFOS доклад: <id>`); `contact` = имейлът на профила (за отговор).
- `X-Submitter-IP` е адресът, който AIFOS вижда зад nginx — същият като за
  ограничението на входа (`rate_limit.client_ip`: `X-Real-IP` от nginx при
  `RATE_LIMIT_TRUST_PROXY_HEADER=true`). Пази се в реда, защото повторният опит
  е по-късно от фоновия цикъл. Control Center го зачита **само** ако системата е
  в неговия `COCKPIT_TICKET_PROXY_SYSTEMS`; иначе брои квотата си по адреса на
  сървъра ни (всички потребители заедно).
- Схемата е копирана в `tests/test_support.py` (`TicketIn`) и всеки изпратен
  payload се валидира срещу нея. Смени ли я Control Center — копието се сменя
  ръчно.

## Опашката

1. Докладът се записва (`support_reports`, статус `pending`).
2. Ако е настроено, заявката опитва веднага (таймаут
   `SUPPORT_FORWARD_TIMEOUT_SECONDS`).
3. Неуспешното остава `pending` с `next_attempt_at`. Фоновият цикъл
   (`forwarder.run_forwarder_loop`, пуснат от `main._lifespan` при старт, във
   всеки uvicorn работник) на всеки `SUPPORT_FORWARD_INTERVAL_SECONDS` праща
   чакащите, чийто ред е дошъл.

| отговор на Control Center | какво става |
|---|---|
| 2xx | `sent` + номерът; **никога** не се праща пак (Control Center няма ключ за идемпотентност — пази се тук) |
| 400, 422 | `rejected` — повторението ще даде същото |
| 429, 5xx, 401/403/404, мрежа, таймаут | `pending`; изчакване 1, 2, 4… мин до `SUPPORT_FORWARD_MAX_BACKOFF_SECONDS`, не по-малко от `Retry-After` |

Няколко работника не пращат един ред двукратно: редът се заема атомарно
(`claimed_until`, един `UPDATE … WHERE`) преди изпращане. Умре ли процесът по
средата, заемането изтича и друг го поема.

Остатъчен риск: ако Control Center отвори тикета, а отговорът се изгуби по
пътя, пращаме пак → два тикета с един и същ `AIFOS доклад: <id>` в текста.
Пълното решение е ключ за идемпотентност в Control Center.

Колони за наблюдение: `forward_status`, `reference`, `attempts`, `last_error`
(без токена — само статус и кратък текст), `last_attempt_at`, `next_attempt_at`,
`sent_at`. Времената са `timestamptz` (UTC).

## Настройки (`.env` на средата)

| | по подразбиране | |
|---|---|---|
| `COCKPIT_URL` | празно | `https://cockpit.heppsu.com` (без `/api/tickets`) |
| `COCKPIT_APP_TOKEN` | празно | токенът на `aifos` / `aifos-preprod` от Control Center; само от средата |
| `SUPPORT_FORWARDER_ENABLED` | `true` | фоновият цикъл (в тестовете `false`) |
| `SUPPORT_FORWARD_INTERVAL_SECONDS` | `60` | оборот на цикъла (минимум 5) |
| `SUPPORT_FORWARD_TIMEOUT_SECONDS` | `10` | таймаут на една заявка |
| `SUPPORT_FORWARD_MAX_BACKOFF_SECONDS` | `3600` | таван на изчакването |
| `SUPPORT_REPORT_RATE_LIMIT` / `_WINDOW_SECONDS` | `5` / `3600` | доклади на потребител (= таванът на Control Center на подател за час) |

Празни `COCKPIT_*` → `configured: false`, нищо не излиза навън, докладите
чакат в базата и тръгват при първия оборот след като настройката се появи (и
рестарт на api). Извън локалната среда адрес `http://` се смята за ненастроен —
токен по чист HTTP през интернет е токен на всеки по пътя.

## Как се проверява

```bash
curl -s https://<среда>/api/v1/support/config        # {"configured":true}
```

Това пита и `infra/deploy.sh` на preprod преди production (`infra/dod.yml`).
Дали доклад е стигнал — в базата на средата:

```sql
SELECT forward_status, reference, attempts, last_error, created_at
FROM support_reports ORDER BY created_at DESC LIMIT 20;
```

Без тестови тикети срещу истинския Control Center — проверката на препращането
е в тестовете (подменен транспорт на httpx).

## При деплой

1. Миграцията `ffdb0650271c_support_reports` (стъпката `migrate` я пуска сама).
2. В Control Center: системите `aifos` и `aifos-preprod` в `COCKPIT_APP_TOKENS`
   и в `COCKPIT_TICKET_PROXY_SYSTEMS`. Без второто `X-Submitter-IP` се
   пренебрегва и таванът на Control Center (5 тикета на адрес за час) важи за
   ЦЕЛИЯ AIFOS — шестият доклад за часа чака в опашката.
3. В `/srv/aifos/<env>/.env`: `COCKPIT_URL` и `COCKPIT_APP_TOKEN`, рестарт на api.
4. `curl …/api/v1/support/config` → `{"configured":true}` на preprod, после prod.

Мобилното приложение (`heppsu-finance-mobile`, отделно репо) няма тази форма —
може да ползва същия `POST /api/v1/support/report`.
