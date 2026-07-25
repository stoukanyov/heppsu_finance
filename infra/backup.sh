#!/usr/bin/env bash
#
# Нощен бекъп на базата и качените документи.
#
# Инсталира се като cron на сървъра (виж infra/README.md):
#   0 3 * * * /srv/aifos/infra/backup.sh >> /srv/aifos/backups/backup.log 2>&1
#
# Пази 14 дневни + 8 седмични копия. Счетоводните данни имат 10-годишен срок на
# съхранение по ЗСч — тези копия са операционни, НЕ заместват архивирането извън
# сървъра. Копие извън машината е задължително преди реална работа.
#
set -euo pipefail

BACKUP_DIR=/srv/aifos/backups
COMPOSE_FILE=/srv/aifos/infra/docker-compose.prod.yml
KEEP_DAILY=14
KEEP_WEEKLY=8
STAMP=$(date +%Y%m%d-%H%M%S)
DOW=$(date +%u)          # 7 = неделя → седмично копие

cd /srv/aifos
set -a; . ./.env; set +a

mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly" "$BACKUP_DIR/documents"

# ─────────────────────────────── База ────────────────────────────────────────
DB_FILE="$BACKUP_DIR/daily/aifos-${STAMP}.sql.gz"
echo "[$(date '+%F %T')] бекъп на базата → $DB_FILE"
docker compose -f "$COMPOSE_FILE" exec -T db \
    pg_dump -U "${POSTGRES_USER:-aifos}" -d "${POSTGRES_DB:-aifos}" --clean --if-exists \
    | gzip -9 > "$DB_FILE"

# Празен дъмп = провален бекъп. По-добре да гърми сега, отколкото при възстановяване.
SIZE=$(stat -c%s "$DB_FILE")
if [ "$SIZE" -lt 1024 ]; then
    echo "ГРЕШКА: дъмпът е само ${SIZE} байта — бекъпът се провали" >&2
    rm -f "$DB_FILE"
    exit 1
fi
gzip -t "$DB_FILE" || { echo "ГРЕШКА: повреден архив" >&2; rm -f "$DB_FILE"; exit 1; }
echo "  дъмпът е валиден (${SIZE} байта)"

# ──────────────────────────── Документи ──────────────────────────────────────
# Оригиналните сканирани документи са доказателствен материал — пазят се цели.
DOC_FILE="$BACKUP_DIR/documents/documents-${STAMP}.tar.gz"
if [ -d /srv/aifos/storage ]; then
    tar -czf "$DOC_FILE" -C /srv/aifos storage
    echo "  документи → $DOC_FILE ($(stat -c%s "$DOC_FILE") байта)"
fi

# ─────────────────────────── Седмично копие ──────────────────────────────────
if [ "$DOW" = "7" ]; then
    cp "$DB_FILE" "$BACKUP_DIR/weekly/"
    echo "  седмично копие запазено"
fi

# ──────────────────────────── Ротация ────────────────────────────────────────
ls -1t "$BACKUP_DIR/daily/"*.sql.gz 2>/dev/null | tail -n +$((KEEP_DAILY + 1)) | xargs -r rm -f
ls -1t "$BACKUP_DIR/weekly/"*.sql.gz 2>/dev/null | tail -n +$((KEEP_WEEKLY + 1)) | xargs -r rm -f
ls -1t "$BACKUP_DIR/documents/"*.tar.gz 2>/dev/null | tail -n +$((KEEP_DAILY + 1)) | xargs -r rm -f

echo "[$(date '+%F %T')] готово. Заето: $(du -sh "$BACKUP_DIR" | cut -f1)"
