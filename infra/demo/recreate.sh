#!/usr/bin/env bash
#
# Пресъздава демо средата от нулата.
#
#   bash infra/demo/recreate.sh
#
# Пуска се на сървъра, всяка нощ по cron:
#   0 4 * * * /srv/aifos/demo/release/infra/demo/recreate.sh >> /srv/aifos/demo/recreate.log 2>&1
#
# Защо от нулата, а не почистване: демото е публично и всеки може да въведе в него
# каквото си иска — включително реални данни на реално дружество. Пълното
# пресъздаване гарантира, че такова попадение живее най-много 24 часа.
#
set -euo pipefail

ENV_DIR=/srv/aifos/demo
PROJECT=aifos-demo
PORT=8081

log() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }

cd "$ENV_DIR"
dc() {
    docker compose -p "$PROJECT" -f release/infra/docker-compose.yml \
        --project-directory . --env-file .env "$@"
}

log "[$(date '+%F %T')] Свалям демо средата заедно с данните"
AIFOS_IMAGE="aifos-api:${PROJECT}" dc down -v --remove-orphans

log "Изчиствам качените документи"
rm -rf "${ENV_DIR:?}/storage"/* 2>/dev/null || true

log "Вдигам наново"
AIFOS_IMAGE="aifos-api:${PROJECT}" dc up -d --no-build

for i in $(seq 1 40); do
    if curl -fsS --max-time 5 "http://127.0.0.1:${PORT}/api/v1/health" >/dev/null 2>&1; then
        break
    fi
    [ "$i" = 40 ] && { echo "демо средата не тръгна" >&2; exit 1; }
    sleep 3
done

log "Пълня с измислени данни"
python3 release/infra/demo/seed_demo.py "http://127.0.0.1:${PORT}"

log "[$(date '+%F %T')] Демо средата е пресъздадена"
