#!/usr/bin/env bash
#
# Връщане към предишната версия, когато здравната проверка на деплоя откаже.
#
# Пуска се НА МАШИНАТА, но файлът живее тук и се подава по стдин:
#
#     ssh "$HOST" PROJECT=... REMOTE_DIR=... bash -s < infra/rollback.sh
#
# Така се тества локално (виж apps/api/tests/test_infra_rollback.py) — като
# текст в heredoc вътре в deploy.sh не се тестваше изобщо и точно затова и
# двете повреди по-долу оцеляха до 26.10.2026, когато свалиха production.
#
# 1. `dc logs` се викаше без AIFOS_IMAGE. `docker-compose.yml` иска
#    променливата със `:?` и compose отказва да прочете файла — дневникът на
#    отказа изчезваше точно когато е най-нужен:
#        error while interpolating services.api.image:
#        required variable AIFOS_IMAGE is missing a value
#
# 2. Вдигането беше `dc up -d --no-build`, тоест със зависимостите, тоест и
#    услугата `migrate`. Но базата вече е мигрирана НАПРЕД от провалилия се
#    деплой, а старият код не познава новата ревизия: `alembic upgrade head`
#    излиза с 255 и връщането назад се проваля точно когато трябва да работи.
#    Затова тук се вдигат само `api` и `nginx`, с `--no-deps`.
#
set -euo pipefail

: "${PROJECT:?липсва PROJECT}"
: "${REMOTE_DIR:?липсва REMOTE_DIR}"

cd "$REMOTE_DIR"

dc() {
    AIFOS_IMAGE="${AIFOS_IMAGE:-aifos-api:${PROJECT}}" \
    docker compose -p "$PROJECT" -f release/infra/docker-compose.yml \
        --project-directory . --env-file .env "$@"
}

dc logs --tail 60 api migrate || true

if [ ! -d release.old ] || ! docker image inspect "aifos-api:${PROJECT}-previous" >/dev/null 2>&1; then
    echo "НЯМА към какво да се върна: липсва release.old или aifos-api:${PROJECT}-previous"
    exit 0
fi

echo "ВРЪЩАМ предишната версия"
rm -rf release.failed && mv release release.failed && mv release.old release
docker tag "aifos-api:${PROJECT}-previous" "aifos-api:${PROJECT}"

AIFOS_IMAGE="aifos-api:${PROJECT}" dc up -d --no-build --no-deps api nginx

echo "ВНИМАНИЕ: базата НЕ е върната назад. Ако миграцията е минала, "
echo "възстанови от backups/pre-deploy-*.sql.gz преди да пуснеш стария код."
