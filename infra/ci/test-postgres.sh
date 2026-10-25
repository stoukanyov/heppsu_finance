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
# Хранилището се монтира и тестовете се пускат ОТТАМ, а не от /app в образа:
# образът носи само apps/api, а `tests/` чете и файлове от корена на хранилището
# (`parents[3]`). Без монтирането събирането гърмеше с `IndexError: 3` и
# прекъсваше ЦЕЛИЯ пробег — портата не пускаше нито един тест, а изглеждаше, че
# е минала.
#
# `tests/test_infra_*.py` се изключват нарочно и видимо: те вдигат истинско git
# хранилище и пускат `deploy.sh`, а в образа няма `git` (той е за приложението,
# не за CI). Тези тестове се пускат в GitHub Actions (.github/workflows/api.yml,
# ubuntu-latest), където git го има. Изключването е по шаблон, не по списък с
# имена — нов infra тест да не остава извън която и да е от двете порти.
REPO_ROOT_HOST="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
docker run --rm --network "$NET_NAME" \
    -e TEST_DATABASE_URL="postgresql+psycopg://test:test@${PG_NAME}:5432/aifos_test" \
    -e AI_PROVIDER=stub \
    -e ENVIRONMENT=test \
    -e SECRET_KEY=ci-test-secret-key-not-used-anywhere \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -v "${REPO_ROOT_HOST}:/repo:ro" \
    -w /repo/apps/api \
    "$IMAGE" \
    python -m pytest -q -p no:warnings --tb=short -p no:cacheprovider \
        --ignore-glob='tests/test_infra_*.py'

log "ТЕСТОВЕТЕ МИНАХА СРЕЩУ POSTGRESQL"
