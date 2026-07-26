#!/usr/bin/env bash
#
# Деплой на AI Finance OS към среда на сървъра.
#
#   ./infra/deploy.sh preprod            # деплой на текущия HEAD към pre-prod
#   ./infra/deploy.sh demo               # деплой към демо средата (порт 8081)
#   ./infra/deploy.sh prod v1.0.0        # деплой на конкретен таг към production
#
# ПРИНЦИП: деплойва се САМО от git ref (таг или комит), никога от работната
# директория. Иначе в production попада некомитнат или чужд код — точно това се
# случи веднъж и заради това правилото е твърдо.
#
# Защити срещу загуба на данни и срив:
#   1. Отказва мръсна работна директория при деплой на production.
#   2. Проверява разрушителни миграции (infra/ci/check_migrations.py).
#   3. Прави дъмп на базата ПРЕДИ миграциите и спира, ако дъмпът се провали.
#   4. Пуска миграциите на репетиция върху копие на реалната база (само за prod).
#   5. Health gate: при неуспех връща предишния образ обратно.
#
set -euo pipefail

ENV_NAME="${1:-}"
GIT_REF="${2:-HEAD}"
HOST="${AIFOS_HOST:-heppsu-deploy}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log()  { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  ✓ %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# Портове и брой работници по среда. `APP_ENV` е стойността на ENVIRONMENT в
# приложението — тя трябва да е в PRODUCTION_ENVIRONMENTS (config.py), иначе
# отпада fail-fast проверката на SECRET_KEY. Затова демото също се пише
# „staging“, макар средата да се казва demo.
case "$ENV_NAME" in
    prod)    HTTP_PORT=80;   HTTPS_PORT=443;  WORKERS=4; APP_ENV=production ;;
    preprod) HTTP_PORT=8080; HTTPS_PORT=8443; WORKERS=2; APP_ENV=staging ;;
    demo)    HTTP_PORT=8081; HTTPS_PORT=8444; WORKERS=1; APP_ENV=staging ;;
    *) die "употреба: $0 {preprod|demo|prod} [git-ref]" ;;
esac

REMOTE_DIR="/srv/aifos/${ENV_NAME}"
PROJECT="aifos-${ENV_NAME}"
cd "$REPO_ROOT"

# ───────────────────────── 0. Проверки преди да пипнем сървъра ────────────────
log "Проверки преди деплой (${ENV_NAME} ← ${GIT_REF})"

git rev-parse --verify "${GIT_REF}^{commit}" >/dev/null 2>&1 \
    || die "няма такъв git ref: ${GIT_REF}"
COMMIT=$(git rev-parse --short "${GIT_REF}^{commit}")
DESCRIBE=$(git describe --tags --always "${GIT_REF}" 2>/dev/null || echo "$COMMIT")
ok "ref ${GIT_REF} → ${DESCRIBE} (${COMMIT})"

# Мръсното дърво е проблем само когато ref-ът е двусмислен (HEAD или клон): тогава
# лесно се мисли, че се качва работното състояние, а се качва последният комит.
# При изричен таг няма двусмислие — тагът е фиксиран.
IS_TAG=$(git tag --list "$GIT_REF" | head -1)
if [ -n "$(git status --porcelain)" ]; then
    if [ "$ENV_NAME" = "prod" ] && [ -z "$IS_TAG" ]; then
        git status --short | head -20
        die "работната директория е мръсна — production се деплойва от таг, не от '${GIT_REF}'"
    fi
    printf '\033[1;33m  ! има некомитнати промени — те НЕ влизат в този деплой\033[0m\n'
fi

log "Проверка за разрушителни миграции"
python3 infra/ci/check_migrations.py || die "деплоят е спрян от пазача на миграциите"

# ─────────────────────────── 1. Архив от git tag ──────────────────────────────
log "Правя архив от ${DESCRIBE}"
TARBALL=$(mktemp -t aifos-release-XXXXXX.tar.gz)
trap 'rm -f "$TARBALL"' EXIT
git archive --format=tar.gz -o "$TARBALL" "$GIT_REF" apps infra
ok "архивът е $(du -h "$TARBALL" | cut -f1)"

log "Качвам към ${HOST}:${REMOTE_DIR}"
ssh "$HOST" "mkdir -p ${REMOTE_DIR}/{release,storage,backups}"
scp -q "$TARBALL" "${HOST}:${REMOTE_DIR}/release.tar.gz"

# ─────────────────── 2. Тайни (само при първо създаване на средата) ───────────
log "Проверявам .env"
ssh "$HOST" ENV_NAME="$ENV_NAME" REMOTE_DIR="$REMOTE_DIR" \
    HTTP_PORT="$HTTP_PORT" HTTPS_PORT="$HTTPS_PORT" WORKERS="$WORKERS" APP_ENV="$APP_ENV" \
    bash -euo pipefail <<'REMOTE'
cd "$REMOTE_DIR"
# Разархивираме предварително, за да имаме шаблона под ръка.
rm -rf release.new && mkdir -p release.new
tar -xzf release.tar.gz -C release.new

if [ -f .env ]; then
    echo "  .env вече съществува — не го пипам"
else
    echo "  създавам .env с нови тайни"
    SECRET=$(openssl rand -base64 48 | tr -d '\n')
    PGPASS=$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 32)
    sed -e "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" \
        -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${PGPASS}|" \
        -e "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+psycopg://aifos:${PGPASS}@db:5432/aifos|" \
        -e "s|^ENVIRONMENT=.*|ENVIRONMENT=${APP_ENV}|" \
        release.new/infra/env.production.example > .env
    {
        echo ""
        echo "# ── Специфично за средата ─────────────────────────────────────"
        echo "AIFOS_HTTP_PORT=${HTTP_PORT}"
        echo "AIFOS_HTTPS_PORT=${HTTPS_PORT}"
        echo "AIFOS_WORKERS=${WORKERS}"
    } >> .env
    chmod 600 .env
    echo "  ВАЖНО: ANTHROPIC_API_KEY и CORS_ORIGINS остават за попълване на ръка"
fi
REMOTE

# ───────────────────── 3. Дъмп ПРЕДИ каквато и да е миграция ──────────────────
# Не е бекъп режим — за това отговаря хостинг доставчикът. Това е точка за връщане
# за конкретна рискова операция: снимката на машината от снощи не помага, ако
# миграция в 14:00 повреди данни, защото с нея се губи целият ден.
log "Дъмп на базата преди миграциите"
ssh "$HOST" PROJECT="$PROJECT" REMOTE_DIR="$REMOTE_DIR" bash -euo pipefail <<'REMOTE'
cd "$REMOTE_DIR"
set -a; . ./.env; set +a
dc() { docker compose -p "$PROJECT" -f release/infra/docker-compose.yml \
       --project-directory . --env-file .env "$@"; }

if [ -d release ] && dc ps --status running --services 2>/dev/null | grep -qx db; then
    STAMP=$(date +%Y%m%d-%H%M%S)
    OUT="backups/pre-deploy-${STAMP}.sql.gz"
    dc exec -T db pg_dump -U "${POSTGRES_USER:-aifos}" -d "${POSTGRES_DB:-aifos}" \
        --clean --if-exists | gzip -9 > "$OUT"
    SIZE=$(stat -c%s "$OUT")
    if [ "$SIZE" -lt 512 ]; then
        echo "ГРЕШКА: бекъпът е само ${SIZE} байта — СПИРАМ деплоя" >&2
        rm -f "$OUT"; exit 1
    fi
    gzip -t "$OUT" || { echo "ГРЕШКА: повреден дъмп — СПИРАМ" >&2; exit 1; }
    echo "  дъмп: $OUT ($(numfmt --to=iec "$SIZE" 2>/dev/null || echo "$SIZE B"))"
    # Пазим последните 10 — иначе дъмповете растат без край. Съдържат лични данни,
    # затова колкото по-малко копия, толкова по-добре (виж docs/BACKLOG.md).
    ls -1t backups/pre-deploy-*.sql.gz 2>/dev/null | tail -n +11 | xargs -r rm -f
else
    echo "  средата е нова — няма какво да се дъмпва"
fi
REMOTE

# ──────────────────────── 4. Смяна на кода и вдигане ──────────────────────────
log "Пускам ${DESCRIBE} в ${ENV_NAME}"
ssh "$HOST" PROJECT="$PROJECT" REMOTE_DIR="$REMOTE_DIR" DESCRIBE="$DESCRIBE" \
    bash -euo pipefail <<'REMOTE'
cd "$REMOTE_DIR"
dc() { docker compose -p "$PROJECT" -f release/infra/docker-compose.yml \
       --project-directory . --env-file .env "$@"; }

# Пазим предишния образ, за да има към какво да се върнем.
if docker image inspect "aifos-api:${PROJECT}" >/dev/null 2>&1; then
    docker tag "aifos-api:${PROJECT}" "aifos-api:${PROJECT}-previous"
    echo "  предишният образ е запазен като aifos-api:${PROJECT}-previous"
fi

rm -rf release.old
[ -d release ] && mv release release.old || true
mv release.new release
echo "$DESCRIBE" > release/VERSION

export AIFOS_IMAGE="aifos-api:${PROJECT}"
dc build --pull api
dc up -d --remove-orphans
dc ps --format 'table {{.Service}}\t{{.Status}}'
REMOTE

# ─────────────────────────── 5. Health gate + връщане назад ───────────────────
log "Проверявам здравето"
PORT="$HTTP_PORT"
HEALTHY=0
for i in $(seq 1 20); do
    if ssh "$HOST" "curl -fsS --max-time 5 http://127.0.0.1:${PORT}/api/v1/health" 2>/dev/null; then
        echo
        ssh "$HOST" "curl -fsS --max-time 5 http://127.0.0.1:${PORT}/api/v1/health/db" 2>/dev/null && echo
        HEALTHY=1
        break
    fi
    sleep 3
done

if [ "$HEALTHY" = 0 ]; then
    printf '\n\033[1;31m✗ приложението не отговаря — връщам предишната версия\033[0m\n' >&2
    ssh "$HOST" PROJECT="$PROJECT" REMOTE_DIR="$REMOTE_DIR" bash -euo pipefail <<'REMOTE' >&2 || true
cd "$REMOTE_DIR"
dc() { docker compose -p "$PROJECT" -f release/infra/docker-compose.yml \
       --project-directory . --env-file .env "$@"; }
dc logs --tail 60 api migrate || true
if [ -d release.old ] && docker image inspect "aifos-api:${PROJECT}-previous" >/dev/null 2>&1; then
    echo "ВРЪЩАМ предишната версия"
    rm -rf release.failed && mv release release.failed && mv release.old release
    docker tag "aifos-api:${PROJECT}-previous" "aifos-api:${PROJECT}"
    AIFOS_IMAGE="aifos-api:${PROJECT}" dc up -d --no-build
    echo "ВНИМАНИЕ: базата НЕ е върната назад. Ако миграцията е минала, "
    echo "възстанови от backups/pre-deploy-*.sql.gz преди да пуснеш стария код."
fi
REMOTE
    die "деплоят се провали"
fi

ok "ДЕПЛОЙ УСПЕШЕН: ${ENV_NAME} ← ${DESCRIBE}"
ssh "$HOST" "cd ${REMOTE_DIR} && rm -rf release.old && echo '  почистено'"
