#!/usr/bin/env bash
#
# Нощен бекъп на базата и качените документи за дадена среда.
#
#   bash infra/backup.sh prod
#
# Инсталира се като cron на сървъра:
#   0 3 * * * /srv/aifos/prod/release/infra/backup.sh prod >> /srv/aifos/prod/backups/backup.log 2>&1
#
# Пази 14 дневни + 8 седмични копия. Счетоводните данни имат 10-годишен срок на
# съхранение по ЗСч — тези копия са операционни и НЕ заместват архивирането
# извън сървъра. При загуба на машината изчезват заедно с нея.
#
set -euo pipefail

ENV_NAME="${1:-prod}"
case "$ENV_NAME" in
    prod|preprod) ;;
    *) echo "употреба: $0 {prod|preprod}" >&2; exit 2 ;;
esac

ENV_DIR="/srv/aifos/${ENV_NAME}"
PROJECT="aifos-${ENV_NAME}"
BACKUP_DIR="${ENV_DIR}/backups"
KEEP_DAILY=14
KEEP_WEEKLY=8
STAMP=$(date +%Y%m%d-%H%M%S)
DOW=$(date +%u)          # 7 = неделя → седмично копие

cd "$ENV_DIR"
set -a; . ./.env; set +a

dc() {
    docker compose -p "$PROJECT" -f release/infra/docker-compose.yml \
        --project-directory . --env-file .env "$@"
}

mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly" "$BACKUP_DIR/documents"

# ─────────────────────────────── База ────────────────────────────────────────
DB_FILE="$BACKUP_DIR/daily/${ENV_NAME}-${STAMP}.sql.gz"
echo "[$(date '+%F %T')] бекъп на ${ENV_NAME} → $DB_FILE"
dc exec -T db pg_dump -U "${POSTGRES_USER:-aifos}" -d "${POSTGRES_DB:-aifos}" \
    --clean --if-exists | gzip -9 > "$DB_FILE"

# Празен дъмп = провален бекъп. По-добре да гърми сега, отколкото при възстановяване.
SIZE=$(stat -c%s "$DB_FILE")
if [ "$SIZE" -lt 1024 ]; then
    echo "ГРЕШКА: дъмпът е само ${SIZE} байта — бекъпът се провали" >&2
    rm -f "$DB_FILE"
    exit 1
fi
gzip -t "$DB_FILE" || { echo "ГРЕШКА: повреден архив" >&2; rm -f "$DB_FILE"; exit 1; }
echo "  дъмпът е валиден ($(numfmt --to=iec "$SIZE" 2>/dev/null || echo "${SIZE}B"))"

# ──────────────────────────── Документи ──────────────────────────────────────
# Оригиналните сканирани документи са доказателствен материал — пазят се цели.
if [ -d "${ENV_DIR}/storage" ] && [ -n "$(ls -A "${ENV_DIR}/storage" 2>/dev/null)" ]; then
    DOC_FILE="$BACKUP_DIR/documents/documents-${STAMP}.tar.gz"
    tar -czf "$DOC_FILE" -C "$ENV_DIR" storage
    echo "  документи → $DOC_FILE ($(numfmt --to=iec "$(stat -c%s "$DOC_FILE")" 2>/dev/null))"
fi

# ─────────────────────────── Седмично копие ──────────────────────────────────
if [ "$DOW" = "7" ]; then
    cp "$DB_FILE" "$BACKUP_DIR/weekly/"
    echo "  седмично копие запазено"
fi

# ──────────────────────────── Ротация ────────────────────────────────────────
# Бекъпите съдържат лични данни — ротацията им е част от политиката за ретеншън
# (виж docs/BACKLOG.md), а не отделно техническо решение.
ls -1t "$BACKUP_DIR/daily/"*.sql.gz 2>/dev/null | tail -n +$((KEEP_DAILY + 1)) | xargs -r rm -f
ls -1t "$BACKUP_DIR/weekly/"*.sql.gz 2>/dev/null | tail -n +$((KEEP_WEEKLY + 1)) | xargs -r rm -f
ls -1t "$BACKUP_DIR/documents/"*.tar.gz 2>/dev/null | tail -n +$((KEEP_DAILY + 1)) | xargs -r rm -f
# Междинните бекъпи преди деплой не се трупат вечно.
ls -1t "$BACKUP_DIR/"pre-deploy-*.sql.gz 2>/dev/null | tail -n +11 | xargs -r rm -f

echo "[$(date '+%F %T')] готово. Заето: $(du -sh "$BACKUP_DIR" | cut -f1)"
