# Deploy наръчник — AI Finance OS

Ръководство за production внедряване на **Ubuntu 24.04 LTS** с Docker Compose и
автоматичен HTTPS чрез Caddy. Приложението се пуска в контейнери; хостът е само Docker host.

> Стъпките с `sudo` изискват администраторски достъп. Замени `finance.example.com` с реалния
> ти домейн и стойностите на паролите/ключовете със силни, уникални стойности.

---

## 0. Преди да започнеш

- Сървър с Ubuntu 24.04, публичен IP, минимум 2 vCPU / 4 GB RAM (препоръчано 4 vCPU / 8 GB).
- Домейн (или поддомейн) с **A запис**, сочещ към IP на сървъра.
- SSH достъп като потребител с `sudo`.

---

## 1. Първоначална подготовка на сървъра

```bash
sudo apt update && sudo apt upgrade -y
sudo timedatectl set-timezone Europe/Sofia

# Непривилегирован потребител за деплой (ако още нямаш такъв)
sudo adduser deploy
sudo usermod -aG sudo deploy
# Прехвърли SSH ключа си и влез като deploy оттук нататък
```

### Защитна стена (ufw)

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

> **Не** отваряй порт 5432 (PostgreSQL) и 8000 (API) към интернет — те остават вътрешни за Docker.

---

## 2. Инсталиране на Docker

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker   # или излез и влез отново
docker --version && docker compose version
```

---

## 3. Клониране на проекта

```bash
cd /opt
sudo mkdir -p ai-finance-os && sudo chown $USER:$USER ai-finance-os
git clone <твоя-git-remote> ai-finance-os
cd ai-finance-os
```

Ако нямаш git remote, копирай директорията на проекта на сървъра (напр. с `rsync`/`scp`).

---

## 4. Конфигурация (.env)

Създай `/opt/ai-finance-os/.env` (използва се от docker-compose):

```dotenv
# Силна произволна стойност (напр. openssl rand -hex 32)
SECRET_KEY=СМЕНИ_МЕ_С_ДЪЛЪГ_СЛУЧАЕН_НИЗ

# База данни (същите креденшъли се ползват от db и api контейнерите)
POSTGRES_USER=aifos
POSTGRES_PASSWORD=СМЕНИ_МЕ_СИЛНА_ПАРОЛА
POSTGRES_DB=aifos

# AI (по избор) — за реален Claude вместо stub
ANTHROPIC_API_KEY=sk-ant-...

# Схемата се управлява с Alembic
AUTO_CREATE_TABLES=false
ENVIRONMENT=production
```

Генериране на `SECRET_KEY`:

```bash
openssl rand -hex 32
```

> **Fail-fast:** при `ENVIRONMENT=production` (както и `prod` / `staging`) приложението
> **отказва да стартира**, ако `SECRET_KEY` е празен, е оставен на стойността по
> подразбиране `dev-secret-change-me`, или е под 32 байта. Грешката се появява веднага в
> `docker compose logs api`, а не при първата заявка. В `local` / `development` / `test`
> дефолтът си остава удобен и не пречи.
>
> `JWT_ALGORITHM` се проверява във всички среди — позволени са само `HS256`, `HS384`,
> `HS512`. Стойност `none` се отхвърля (класическа `alg=none` атака); при декодиране
> алгоритъмът винаги идва от конфигурацията, никога от самия токен.

### Ограничаване на опитите за вход (brute force)

`POST /auth/login` е ограничен с плъзгащ прозорец в паметта на процеса — по **комбинация
от клиентски IP и имейл**. При изчерпан праг връща `429` с header `Retry-After`; успешният
вход нулира брояча. Настройки (по избор в `.env`):

```dotenv
RATE_LIMIT_ENABLED=true                 # по подразбиране true
LOGIN_RATE_LIMIT_ATTEMPTS=5             # неуспешни опита...
LOGIN_RATE_LIMIT_WINDOW_SECONDS=900     # ...за 15 минути
RATE_LIMIT_TRUST_PROXY_HEADER=true      # зад Caddy — реалният IP е в X-Forwarded-For
```

> `RATE_LIMIT_TRUST_PROXY_HEADER` включвай **само** когато API-то не е директно достъпно
> от интернет (при описаната тук схема с Caddy това е така). Ако е директно достъпно,
> header-ът е подправяем и ограничението се заобикаля.
>
> Броенето е за процес: с `--workers 2` реалният праг е до 2× зададения. За точен общ
> лимит при много процеси/машини се сменя само хранилището (напр. Redis) в
> `apps/api/app/core/rate_limit.py`.

### Обвързване на compose с .env

Обнови `docker-compose.yml`, така че `db` и `api` да четат от `.env` (пример за env стойностите):

```yaml
services:
  db:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes: [ "pgdata:/var/lib/postgresql/data" ]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 5s
      timeout: 5s
      retries: 10

  api:
    build: ./apps/api
    restart: unless-stopped
    environment:
      DATABASE_URL: postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
      AUTO_CREATE_TABLES: "false"
      SECRET_KEY: ${SECRET_KEY}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      ENVIRONMENT: production
    command: sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2"
    expose: [ "8000" ]        # само вътрешно за Docker мрежата
    depends_on:
      db: { condition: service_healthy }

volumes:
  pgdata:
```

> Забележка: смени `ports: ["8000:8000"]` на `expose: ["8000"]`, за да не е достъпен API-то
> директно от интернет — Caddy ще го проксира.

---

## 5. Reverse proxy с автоматичен HTTPS (Caddy)

Caddy получава Let's Encrypt сертификат автоматично. Добави услуга в `docker-compose.yml`:

```yaml
  caddy:
    image: caddy:2
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on: [ api ]

volumes:
  pgdata:
  caddy_data:
  caddy_config:
```

Създай `/opt/ai-finance-os/Caddyfile`:

```
finance.example.com {
    encode gzip
    reverse_proxy api:8000
}
```

Това е достатъчно — Caddy сам издава и подновява TLS сертификата.

---

## 6. Стартиране

```bash
cd /opt/ai-finance-os
docker compose up -d --build
docker compose ps
docker compose logs -f api   # проследи миграциите и старта
```

При старт `api` контейнерът изпълнява `alembic upgrade head` (създава схемата), после пуска uvicorn.

Проверка:

```bash
curl -s https://finance.example.com/api/v1/health
# → {"status":"ok",...}
```

Отвори в браузър: **https://finance.example.com/app/**

---

## 7. Резервни копия (PostgreSQL)

Ежедневен dump чрез cron:

```bash
mkdir -p /opt/ai-finance-os/backups
crontab -e
```

Добави ред:

```
0 2 * * * docker compose -f /opt/ai-finance-os/docker-compose.yml exec -T db pg_dump -U aifos aifos | gzip > /opt/ai-finance-os/backups/aifos-$(date +\%F).sql.gz
```

Възстановяване:

```bash
gunzip -c backups/aifos-2026-07-25.sql.gz | \
  docker compose exec -T db psql -U aifos -d aifos
```

> Пази копия и извън сървъра (S3/друг хост). Документите се съхраняват във volume — включи и
> `storage/` във външния бекъп, ако ползваш локално файлово хранилище.

---

## 8. Обновяване на приложението

```bash
cd /opt/ai-finance-os
git pull
docker compose up -d --build   # преизгражда и рестартира; миграциите се пускат при старт
docker compose logs -f api
```

---

## 9. Сигурност (чеклист)

- [ ] Силни, уникални `SECRET_KEY` и парола за БД (в `.env`, извън git — виж `.gitignore`).
      Проверява се автоматично при старт, когато `ENVIRONMENT=production`.
- [ ] `ENVIRONMENT=production` е зададено (иначе строгите проверки са изключени).
- [ ] Brute force защитата на `/auth/login` е включена и `RATE_LIMIT_TRUST_PROXY_HEADER`
      съответства на това дали има reverse proxy.
- [ ] Портовете 5432 и 8000 **не** са публични (само 80/443 през Caddy).
- [ ] SSH само с ключ (изключи парола: `PasswordAuthentication no` в sshd_config).
- [ ] Автоматични security ъпдейти: `sudo apt install unattended-upgrades`.
- [ ] Редовни бекъпи, тествано възстановяване.
- [ ] Ограничи `ANTHROPIC_API_KEY` до нужното; не го логвай (кодът не го прави).
- [ ] Мониторинг на дисковото пространство (Postgres volume, документи, бекъпи).

---

## 10. Отстраняване на проблеми

| Симптом | Проверка |
|---|---|
| `InsecureConfigurationError` при старт | Слаб/дефолтен `SECRET_KEY` или недопустим `JWT_ALGORITHM` — виж раздел 4 |
| `429` при вход | Изчерпани опити за този IP+имейл; изчакай `Retry-After` секунди |
| 502 от Caddy | `docker compose logs api` — стартирал ли е uvicorn; минали ли са миграциите |
| Миграциите падат | `docker compose exec api alembic current` / `alembic history` |
| Няма TLS | A записът сочи ли към сървъра; портове 80/443 отворени ли са (ufw) |
| БД грешки | `docker compose logs db`; здрав ли е `pgdata` volume |

За локална разработка без Docker виж `README.md`.
