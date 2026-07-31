#!/usr/bin/env bash
#
# Репетиция на миграциите върху КОПИЕ на реалната production база.
#
#   bash infra/ci/rehearse-migrations.sh [образ] [дъмп]
#
# По подразбиране взима образа, който в момента е в pre-prod, и пресен дъмп на
# production. Тоест отговаря точно на въпроса:
#
#     „Ще минат ли промените от pre-prod върху реалните production данни,
#      без да счупят нещо и без да изтрият нещо?"
#
# Тестовете на празна база не могат да отговорят на този въпрос: миграция с
# `alter_column(nullable=False)` минава на празна таблица и гърми върху реални
# данни с NULL. Затова репетицията е задължителна преди production деплой.
#
# Прави се върху ЕДНОКРАТНО КОПИЕ. Production базата не се пипа изобщо.
#
set -euo pipefail

IMAGE="${1:-aifos-api:aifos-preprod}"
DUMP="${2:-}"
# Кой head трябва да е схемата СЛЕД репетицията. Изчислява се от кода, който се
# пуска (`infra/ci/alembic_head.py`), не от образа — иначе стар образ потвърждава
# сам себе си. Виж проверката в края.
EXPECT_HEAD="${3:-${EXPECT_HEAD:-}}"
PROD_DIR=/srv/aifos/prod
PG_NAME="aifos-rehearsal-pg-$$"
NET_NAME="aifos-rehearsal-net-$$"
WORK=$(mktemp -d)

log() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m  ✓ %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

cleanup() {
    docker rm -f "$PG_NAME" >/dev/null 2>&1 || true
    docker network rm "$NET_NAME" >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

docker image inspect "$IMAGE" >/dev/null 2>&1 || die "няма такъв образ: $IMAGE"

# ────────────────────────── 1. Копие на production данните ────────────────────
log "Взимам копие на production базата"
if [ -n "$DUMP" ]; then
    [ -f "$DUMP" ] || die "няма такъв дъмп: $DUMP"
    cp "$DUMP" "$WORK/prod.sql.gz"
    ok "ползвам подадения дъмп: $DUMP"
elif [ -d "$PROD_DIR/release" ]; then
    cd "$PROD_DIR"
    set -a; . ./.env; set +a
    # Без AIFOS_IMAGE compose отказва да прочете файла (`:?` в docker-compose.yml)
    # и репетицията пада още преди да е взела дъмпа. Тук нищо не се вдига —
    # само `exec` към работещата база. Същият капан изключи и дъмпа преди
    # миграциите в deploy.sh; виж „Поправено“ в infra/README.md.
    export AIFOS_IMAGE="${AIFOS_IMAGE:-aifos-api:aifos-prod}"
    docker compose -p aifos-prod -f release/infra/docker-compose.yml \
        --project-directory . --env-file .env \
        exec -T db pg_dump -U "${POSTGRES_USER:-aifos}" -d "${POSTGRES_DB:-aifos}" \
        | gzip -9 > "$WORK/prod.sql.gz"
    ok "пресен дъмп: $(du -h "$WORK/prod.sql.gz" | cut -f1)"
else
    die "production още не е разгърнат — няма върху какво да се репетира"
fi

BEFORE_SIZE=$(stat -c%s "$WORK/prod.sql.gz")
[ "$BEFORE_SIZE" -gt 256 ] || die "дъмпът е подозрително малък (${BEFORE_SIZE} байта)"

# ─────────────────────────── 2. Възстановяване в копие ────────────────────────
log "Възстановявам копието в еднократна база"
docker network create "$NET_NAME" >/dev/null
docker run -d --name "$PG_NAME" --network "$NET_NAME" \
    -e POSTGRES_USER=rehearsal -e POSTGRES_PASSWORD=rehearsal -e POSTGRES_DB=aifos \
    -e POSTGRES_INITDB_ARGS="--encoding=UTF8 --locale=C.UTF-8" \
    postgres:17-alpine >/dev/null

# `-h 127.0.0.1` е задължително, а не украса. Образът на postgres вдига ВРЕМЕНЕН
# сървър по време на initdb; той слуша само по unix сокета. `pg_isready` без хост
# минава точно по него и отговаря „готово“ секунди преди истинския сървър да е
# тръгнал — после временният се спира и възстановяването пада с „the database
# system is shutting down“. По TCP временният сървър не се вижда изобщо.
for i in $(seq 1 40); do
    docker exec "$PG_NAME" pg_isready -h 127.0.0.1 -U rehearsal -d aifos >/dev/null 2>&1 && break
    [ "$i" = 40 ] && die "копието на базата не тръгна"
    sleep 1
done

gunzip -c "$WORK/prod.sql.gz" | docker exec -i "$PG_NAME" psql -q -U rehearsal -d aifos >/dev/null
ok "данните са възстановени"

count_rows() {
    docker exec "$PG_NAME" psql -U rehearsal -d aifos -tAc "
        select coalesce(sum(n_live_tup), 0) from pg_stat_user_tables;" | tr -d ' '
}
docker exec "$PG_NAME" psql -U rehearsal -d aifos -qc "ANALYZE;" >/dev/null
ROWS_BEFORE=$(count_rows)
VER_BEFORE=$(docker exec "$PG_NAME" psql -U rehearsal -d aifos -tAc \
    "select version_num from alembic_version;" 2>/dev/null | tr -d ' ' || echo "няма")
echo "  преди миграциите: ${ROWS_BEFORE} реда, схема ${VER_BEFORE}"

# ──────────────────────────── 3. Самата репетиция ─────────────────────────────
log "Пускам миграциите от новия код върху копието"
if ! docker run --rm --network "$NET_NAME" \
        -e DATABASE_URL="postgresql+psycopg://rehearsal:rehearsal@${PG_NAME}:5432/aifos" \
        -e SECRET_KEY=rehearsal-secret-not-used-anywhere \
        -e ENVIRONMENT=test \
        -w /app "$IMAGE" alembic upgrade head; then
    die "МИГРАЦИИТЕ ПАДАТ ВЪРХУ РЕАЛНИТЕ ДАННИ — деплоят е спрян"
fi

docker exec "$PG_NAME" psql -U rehearsal -d aifos -qc "ANALYZE;" >/dev/null
ROWS_AFTER=$(count_rows)
VER_AFTER=$(docker exec "$PG_NAME" psql -U rehearsal -d aifos -tAc \
    "select version_num from alembic_version;" | tr -d ' ')
echo "  след миграциите:  ${ROWS_AFTER} реда, схема ${VER_AFTER}"

# ─────────── Пробван ли е ПРАВИЛНИЯТ код, или само някакъв код? ───────────────
#
# Зелена репетиция срещу стар образ е по-опасна от никаква репетиция, защото дава
# увереност за код, който не е бил пробван. А това не е хипотеза: след
# разделянето на машините `aifos-api:aifos-preprod` на Phobos е остатък отпреди
# преместването — pre-prod вече се строи на Deimos.
#
# Затова сравняваме с head-а на КОДА, който се пуска, а не с този на образа.
# Първият вариант на проверката беше „схемата помръдна ли“ — той е грешен в двете
# посоки: издание без нови миграции законно не мърда схемата и щеше да бъде
# спряно фалшиво, а точно в този случай стар образ щеше да мине зелено.
if [ -n "$EXPECT_HEAD" ]; then
    if [ "$VER_AFTER" != "$EXPECT_HEAD" ]; then
        die "схемата след репетицията е ${VER_AFTER}, а кодът очаква ${EXPECT_HEAD}.
   Образът ${IMAGE} не носи този код — почти сигурно е стар.
   Строй образа от ref-а, който пускаш, и подай него."
    fi
    ok "схемата съвпада с head-а на кода (${EXPECT_HEAD})"
else
    printf '\033[1;33m  ! без EXPECT_HEAD репетицията не доказва, че е пробван ПРАВИЛНИЯТ образ\033[0m\n'
    printf '\033[1;33m    подай го: bash %s <образ> "" $(python3 infra/ci/alembic_head.py)\033[0m\n' "$0"
    if [ "$VER_AFTER" = "$VER_BEFORE" ]; then
        printf '\033[1;33m  ! схемата не помръдна (%s) — ако това издание носи миграции, образът е стар\033[0m\n' "$VER_BEFORE"
    fi
fi

# ──────────────────────── 4. Изчезнали ли са данни? ───────────────────────────
log "Проверявам за загуба на данни"
if [ "$ROWS_AFTER" -lt "$ROWS_BEFORE" ]; then
    LOST=$((ROWS_BEFORE - ROWS_AFTER))
    die "ЗАГУБЕНИ ${LOST} реда при миграцията (${ROWS_BEFORE} → ${ROWS_AFTER}) — деплоят е спрян"
fi
ok "няма загуба на редове (${ROWS_BEFORE} → ${ROWS_AFTER})"

# Приложението трябва и да ТРЪГНЕ срещу мигрираната схема, не само да мигрира.
log "Проверявам, че приложението работи срещу мигрираната схема"
if ! docker run --rm --network "$NET_NAME" \
        -e DATABASE_URL="postgresql+psycopg://rehearsal:rehearsal@${PG_NAME}:5432/aifos" \
        -e SECRET_KEY=rehearsal-secret-not-used-anywhere \
        -e ENVIRONMENT=test -e AUTO_CREATE_TABLES=false -e AI_PROVIDER=stub \
        -w /app "$IMAGE" python -c "
from app.main import app          # вдига цялото приложение и всички рутери
from app.core.database import SessionLocal
from sqlalchemy import text
with SessionLocal() as db:
    for t in ('users','companies','journal_entries','invoices','documents'):
        db.execute(text(f'select count(*) from {t}'))
print('приложението стартира и чете всички основни таблици')
"; then
    die "приложението НЕ работи срещу мигрираната схема — деплоят е спрян"
fi

printf '\n\033[1;32m▸ РЕПЕТИЦИЯТА МИНА — миграциите са безопасни за production\033[0m\n'
