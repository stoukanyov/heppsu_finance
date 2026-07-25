#!/usr/bin/env bash
#
# Пуска ЦЕЛИЯ тестов пакет срещу истински PostgreSQL — същата версия като в
# production.
#
# Това е проверката „кодът съвместим ли е с продукционната база“: SQLite прощава
# неща, които PostgreSQL не прощава (типове, ограничения, транзакционен DDL,
# сортиране). Тест, минал само на SQLite, НЕ доказва нищо за production.
#
# Пуска се на машина с Docker (сървъра или CI runner-а):
#   bash infra/ci/test-postgres.sh [път-до-образа]
#
set -euo pipefail

IMAGE="${1:-aifos-api:latest}"
PG_NAME="aifos-ci-pg-$$"
NET_NAME="aifos-ci-net-$$"
PG_IMAGE="postgres:17-alpine"

log() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }

cleanup() {
    docker rm -f "$PG_NAME" >/dev/null 2>&1 || true
    docker network rm "$NET_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

log "Вдигам PostgreSQL за тестовете"
docker network create "$NET_NAME" >/dev/null
docker run -d --name "$PG_NAME" --network "$NET_NAME" \
    -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=aifos_test \
    -e POSTGRES_INITDB_ARGS="--encoding=UTF8 --locale=C.UTF-8" \
    "$PG_IMAGE" >/dev/null

for i in $(seq 1 30); do
    if docker exec "$PG_NAME" pg_isready -U test -d aifos_test >/dev/null 2>&1; then
        echo "базата е готова (след ${i}s)"
        break
    fi
    [ "$i" = 30 ] && { echo "базата не тръгна" >&2; exit 1; }
    sleep 1
done

log "Пускам тестовете срещу PostgreSQL"
docker run --rm --network "$NET_NAME" \
    -e TEST_DATABASE_URL="postgresql+psycopg://test:test@${PG_NAME}:5432/aifos_test" \
    -e AI_PROVIDER=stub \
    -e ENVIRONMENT=test \
    -e SECRET_KEY=ci-test-secret-key-not-used-anywhere \
    -w /app \
    "$IMAGE" \
    python -m pytest -q -p no:warnings --tb=short

log "ТЕСТОВЕТЕ МИНАХА СРЕЩУ POSTGRESQL"
