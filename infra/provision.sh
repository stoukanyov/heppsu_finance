#!/usr/bin/env bash
#
# Базово обезопасяване и подготовка на production сървъра (Ubuntu 24.04).
#
# Идемпотентен: може да се пуска повторно без вреда.
# Пуска се като root:  ssh heppsu 'bash -s' < infra/provision.sh
#
# Какво прави:
#   1. Часова зона Europe/Sofia — данъчните срокове се изчисляват от локалната дата.
#   2. Системни пакети + автоматични security обновявания.
#   3. Потребител `deploy` (без sudo) — приложението НЕ се върти като root.
#   4. SSH: само ключове, root вход само с ключ, ограничен списък потребители.
#   5. ufw: затворено всичко освен 22/80/443.
#   6. fail2ban за sshd.
#   7. Docker Engine + compose plugin от официалното хранилище.
#
set -euo pipefail

log() { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
DEPLOY_USER=deploy

# ─────────────────────────────── 1. Часова зона ───────────────────────────────
log "Часова зона"
timedatectl set-timezone Europe/Sofia
timedatectl set-ntp true
date

# ────────────────────────────── 2. Системни пакети ────────────────────────────
log "Системни пакети"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    ca-certificates curl gnupg git ufw fail2ban unattended-upgrades \
    htop jq rsync zip unzip logrotate

log "Автоматични security обновявания"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
systemctl enable --now unattended-upgrades >/dev/null 2>&1 || true

# ─────────────────────────── 3. Потребител за деплой ──────────────────────────
log "Потребител ${DEPLOY_USER}"
if ! id -u "$DEPLOY_USER" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "AI Finance OS deploy" "$DEPLOY_USER"
fi
# Паролата остава заключена — вход само с ключ.
passwd -l "$DEPLOY_USER" >/dev/null

install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
if [ -s /root/.ssh/authorized_keys ]; then
    install -m 600 -o "$DEPLOY_USER" -g "$DEPLOY_USER" \
        /root/.ssh/authorized_keys "/home/$DEPLOY_USER/.ssh/authorized_keys"
    echo "ключовете на root са копирани към $DEPLOY_USER"
else
    echo "ВНИМАНИЕ: /root/.ssh/authorized_keys е празен — не копирах ключове" >&2
fi

# ──────────────────────────────── 4. SSH ──────────────────────────────────────
# ВАЖНО: sshd взема ПЪРВАТА срещната стойност за даден ключ, а Include-ът е в
# началото на sshd_config. Затова файлът трябва да се чете преди 50-cloud-init.conf
# (който включва паролите) → префикс 00-.
log "SSH обезопасяване"
cat > /etc/ssh/sshd_config.d/00-aifos-hardening.conf <<EOF
# AI Finance OS — управлява се от infra/provision.sh. Не редактирай на ръка.
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PubkeyAuthentication yes
PermitRootLogin prohibit-password
AllowUsers root ${DEPLOY_USER}
MaxAuthTries 4
LoginGraceTime 30
X11Forwarding no
AllowAgentForwarding no
ClientAliveInterval 300
ClientAliveCountMax 2
EOF

# Първо валидираме — счупен конфиг + socket activation = недостъпен сървър.
if ! sshd -t; then
    echo "СЧУПЕН sshd конфиг — връщам назад" >&2
    rm -f /etc/ssh/sshd_config.d/00-aifos-hardening.conf
    exit 1
fi
systemctl restart ssh.socket ssh.service 2>/dev/null || systemctl restart ssh
echo "активна конфигурация:"
sshd -T | grep -E '^(passwordauthentication|permitrootlogin|pubkeyauthentication|allowusers|port)' | sort

# ─────────────────────────────── 5. Firewall ──────────────────────────────────
# Портът за SSH се отваря ПРЕДИ enable, иначе се самозаключваме.
log "ufw"
ufw --force reset >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 22/tcp  comment 'SSH'   >/dev/null
ufw allow 80/tcp  comment 'HTTP'  >/dev/null
ufw allow 443/tcp comment 'HTTPS' >/dev/null
ufw --force enable >/dev/null
ufw status verbose | head -12

# ─────────────────────────────── 6. fail2ban ──────────────────────────────────
log "fail2ban"
cat > /etc/fail2ban/jail.d/sshd.local <<'EOF'
[sshd]
enabled  = true
backend  = systemd
maxretry = 4
findtime = 10m
bantime  = 1h
EOF
systemctl enable --now fail2ban >/dev/null
sleep 2
fail2ban-client status sshd 2>/dev/null | head -6 || true

# ──────────────────────────────── 7. Docker ───────────────────────────────────
log "Docker"
if ! command -v docker >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    . /etc/os-release
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq \
        docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
# Логовете на контейнерите да не изядат диска.
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "5" },
  "live-restore": true
}
EOF
systemctl enable --now docker >/dev/null
systemctl restart docker
usermod -aG docker "$DEPLOY_USER"
docker --version
docker compose version

# ───────────────────────────── Директории на приложението ─────────────────────
log "Директории"
install -d -m 750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" /srv/aifos
install -d -m 750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" /srv/aifos/storage
install -d -m 750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" /srv/aifos/backups

log "ГОТОВО"
echo "Следваща стъпка: infra/docker-compose.prod.yml + .env"
