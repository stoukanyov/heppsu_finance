#!/usr/bin/env bash
#
# Нощен бекъп на базата и качените документи за една среда.
#
# ПУСКА СЕ НА САМИЯ СЪРВЪР, от cron на потребителя `deploy`:
#   0 3 * * * /srv/aifos/bin/backup.sh prod >> /srv/aifos/prod/backups/backup.log 2>&1
#
# Живее в `/srv/aifos/bin/`, а НЕ в `release/`, нарочно: `release/` се сменя при
# всеки деплой и се пълни от git таг. Ако бекъпът зависеше от него, всяко издание
# отпреди този файл щеше да изключва нощния бекъп мълчаливо — точно това се случи
# между 26 и 28 юли 2026, когато скриптът остана само в `/srv/aifos/_legacy/`.
# Затова: източникът е този файл в репото, инсталира се с
#   scp infra/backup.sh heppsu-deploy:/srv/aifos/bin/backup.sh
# и при промяна тук се копира наново на ръка.
#
# Пази 14 дневни + 8 седмични копия на базата. Счетоводните данни имат 10-годишен
# срок на съхранение по ЗСч — тези копия са ОПЕРАЦИОННИ и не заместват архив извън
# машината. Дневната снимка на цялата машина при Contabo е другият слой; тя връща
# машината към снощи, а тези дъмпове дават точка за връщане в рамките на деня.
#
set -euo pipefail

ENV_NAME="${1:-prod}"
# Коренът се подава отвън САМО за да може тестът да пусне скрипта наистина.
# Cron не подава нищо и пътят на машината е същият, какъвто беше.
ENV_DIR="${AIFOS_ENV_ROOT:-/srv/aifos}/${ENV_NAME}"
PROJECT="aifos-${ENV_NAME}"
BACKUP_DIR="${ENV_DIR}/backups"
KEEP_DAILY=14
KEEP_WEEKLY=8
STAMP=$(date +%Y%m%d-%H%M%S)
DOW=$(date +%u)          # 7 = неделя → седмично копие

[ -d "$ENV_DIR" ] || { echo "ГРЕШКА: няма среда $ENV_DIR" >&2; exit 1; }
cd "$ENV_DIR"

# `docker-compose.yml` иска AIFOS_IMAGE без стойност по подразбиране (`:?`), за да
# не тръгне стек с чужд образ. Тук само четем и правим pg_dump, нищо не се вдига,
# но без променливата дори `compose ps` гърми — и проверката „върви ли базата“
# връща лъжливо „не“. Затова я задаваме със същата стойност, която ползва deploy.sh.
export AIFOS_IMAGE="${AIFOS_IMAGE:-aifos-api:${PROJECT}}"

dc() {
    docker compose -p "$PROJECT" -f release/infra/docker-compose.yml \
        --project-directory . --env-file .env "$@"
}

set -a; . ./.env; set +a
mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly" "$BACKUP_DIR/documents"

# ─────────────────────────────── База ────────────────────────────────────────
# Ако базата не върви, това е провал, а не „няма какво да се пази“: мълчаливото
# пропускане е начинът, по който бекъпите спират, без някой да разбере.
if ! dc ps --status running --services 2>/dev/null | grep -qx db; then
    echo "[$(date '+%F %T')] ГРЕШКА: базата на ${ENV_NAME} не върви — няма бекъп" >&2
    exit 1
fi

DB_FILE="$BACKUP_DIR/daily/${ENV_NAME}-${STAMP}.sql.gz"
echo "[$(date '+%F %T')] бекъп на ${ENV_NAME} → $DB_FILE"
dc exec -T db pg_dump -U "${POSTGRES_USER:-aifos}" -d "${POSTGRES_DB:-aifos}" \
    --clean --if-exists | gzip -9 > "$DB_FILE"

# Празен дъмп = провален бекъп. По-добре да гърми сега, отколкото при възстановяване.
SIZE=$(stat -c%s "$DB_FILE")
if [ "$SIZE" -lt 1024 ]; then
    echo "  ГРЕШКА: дъмпът е само ${SIZE} байта — бекъпът се провали" >&2
    rm -f "$DB_FILE"
    exit 1
fi
gzip -t "$DB_FILE" || { echo "  ГРЕШКА: повреден архив" >&2; rm -f "$DB_FILE"; exit 1; }
echo "  дъмпът е валиден ($(numfmt --to=iec "$SIZE" 2>/dev/null || echo "${SIZE} B"))"

# ──────────────────────────── Документи ──────────────────────────────────────
# Оригиналните сканирани документи са доказателствен материал — пазят се цели.
if [ -d "${ENV_DIR}/storage" ] && [ -n "$(ls -A "${ENV_DIR}/storage" 2>/dev/null)" ]; then
    DOC_FILE="$BACKUP_DIR/documents/documents-${STAMP}.tar.gz"
    tar -czf "$DOC_FILE" -C "$ENV_DIR" storage
    echo "  документи → $DOC_FILE ($(numfmt --to=iec "$(stat -c%s "$DOC_FILE")" 2>/dev/null))"
else
    echo "  storage/ е празна — няма документи за пазене"
fi

# ─────────────────────────── Седмично копие ──────────────────────────────────
if [ "$DOW" = "7" ]; then
    cp "$DB_FILE" "$BACKUP_DIR/weekly/"
    echo "  седмично копие запазено"
fi

# ──────────────────────────── Ротация ────────────────────────────────────────
# С `find`, а не с `ls <шаблон>`. Несъвпаднал шаблон оставя `ls` да излезе с
# грешка; `set -o pipefail` я вдига до целия конвейер, а `set -e` убива скрипта.
#
# Точно това се случваше на Phobos всяка нощ: `documents/` е празна, докато
# `storage/` е празна, тъй че третият ред гърмеше и скриптът умираше — след като
# дъмпът е записан, но преди края. В целия `backup.log` нямаше НИТО ЕДНО „готово",
# а никой не забеляза, защото копието си беше на място и изходният код не се чете
# от никого. Открито на 22.08.2026, докато се добавяше клеймото за успех.
#
# `find` върху нищо излиза с 0 — празна директория вече е обикновен случай, а не
# край на света.
rotate() {
    local dir="$1" pattern="$2" keep="$3"
    find "$dir" -maxdepth 1 -type f -name "$pattern" -printf '%T@ %p\n' 2>/dev/null \
        | sort -rn | tail -n "+$((keep + 1))" | cut -d' ' -f2- | xargs -r rm -f
}

rotate "$BACKUP_DIR/daily"     '*.sql.gz'  "$KEEP_DAILY"
rotate "$BACKUP_DIR/weekly"    '*.sql.gz'  "$KEEP_WEEKLY"
rotate "$BACKUP_DIR/documents" '*.tar.gz'  "$KEEP_DAILY"

# ──────────────────────── Клеймо за успех ────────────────────────────────────
# Единственото, което провален бекъп не може да напише. Всичко останало лъже
# успокоително: файлове в директорията има и когато дъмпът е празен, ред в
# crontab има и когато скриптът гърми всяка нощ, а логът го чете само този,
# който вече е заподозрял нещо.
#
# Форматът е `date -u +%s` — същият файл и същото място, както при Groomelle,
# My Beagle и Control Center, за да може ЕДНА проверка да гледа всичките.
# Control Center мери възрастта му; над 26 часа значи пропусната нощ.
#
# Стои след ротацията нарочно: дотук всяка грешка е излизала с ненулев код
# заради `set -e`, тъй че този ред се достига само при бекъп, минал докрай.
date -u +%s > "${BACKUP_DIR}/LAST_SUCCESS"

echo "[$(date '+%F %T')] готово. Заето: $(du -sh "$BACKUP_DIR" | cut -f1)"
