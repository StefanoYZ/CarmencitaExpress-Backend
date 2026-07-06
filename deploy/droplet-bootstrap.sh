#!/usr/bin/env bash
# Bootstrap inicial de un Droplet Ubuntu limpio para Carmencita Express Cargo.
# Ejecutar UNA sola vez, como root o con sudo, en un Droplet nuevo (2GB RAM).
#
# Uso:
#   ssh root@TU_DROPLET_IP
#   curl -fsSL https://raw.githubusercontent.com/StefanoYZ/CarmencitaExpress-Backend/main/deploy/droplet-bootstrap.sh -o bootstrap.sh
#   bash bootstrap.sh
set -euo pipefail

APP_DIR="/opt/carmencita"
GIT_USER="StefanoYZ"

echo "==> 1/6 Actualizando el sistema"
apt-get update -y && apt-get upgrade -y

echo "==> 2/6 Creando swap de 4GB (build de backend+frontend en 2GB RAM se queda sin memoria sin esto)"
if [ ! -f /swapfile ]; then
  fallocate -l 4G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  # Prioriza RAM sobre swap para no penalizar el rendimiento en uso normal.
  echo 'vm.swappiness=10' >> /etc/sysctl.conf
  sysctl -p
fi

echo "==> 3/6 Instalando Docker Engine + Compose plugin"
if ! command -v docker &> /dev/null; then
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
fi

echo "==> 4/6 Configurando firewall (solo SSH, HTTP y HTTPS)"
apt-get install -y ufw
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "==> 5/6 Clonando backend y frontend como hermanos de deploy/"
# Repos publicos: clonamos por HTTPS (sin autenticacion, sin llave SSH).
# Lycet-Carmencita NO se clona: su imagen se compila en CI y se publica en
# ghcr.io; el Droplet solo hace "docker compose pull" (ver docker-compose.yml).
mkdir -p "$APP_DIR"
cd "$APP_DIR"
[ -d CarmencitaExpress-Backend ] || git clone "https://github.com/${GIT_USER}/CarmencitaExpress-Backend.git"
[ -d Front-Carmencita ]          || git clone "https://github.com/${GIT_USER}/Front-Carmencita.git"

mkdir -p "$APP_DIR/deploy"
cp -n CarmencitaExpress-Backend/deploy/docker-compose.yml "$APP_DIR/deploy/docker-compose.yml" || true
if [ ! -f "$APP_DIR/deploy/.env" ]; then
  cp CarmencitaExpress-Backend/deploy/.env.example "$APP_DIR/deploy/.env"
  echo "!!! Completa los valores reales en $APP_DIR/deploy/.env antes del primer arranque !!!"
fi

echo "==> 6/6 Autenticando Docker contra ghcr.io (para poder hacer pull de la imagen de Lycet)"
echo "El paquete ghcr.io/${GIT_USER,,}/lycet-carmencita es privado por defecto."
echo "Genera un Personal Access Token (classic) con el scope 'read:packages' en:"
echo "  https://github.com/settings/tokens"
echo "Luego ejecuta manualmente (una sola vez, el login queda cacheado):"
echo "  echo 'TU_TOKEN' | docker login ghcr.io -u ${GIT_USER} --password-stdin"
echo "(Alternativa mas simple: en GitHub, Packages > lycet-carmencita > Package settings,"
echo " cambia la visibilidad a 'Public'. Asi el Droplet no necesita login para el pull.)"

echo "==> Listo. Estructura final:"
find "$APP_DIR" -maxdepth 1

cat <<'EOF'

Siguientes pasos manuales:
  1. Edita /opt/carmencita/deploy/.env con las credenciales reales
     (o configura los GitHub Secrets para que el pipeline lo haga por ti).
  2. Verifica que el usuario SSH que usara GitHub Actions tenga permiso sobre
     Docker: usermod -aG docker <usuario_deploy> && newgrp docker
  3. Autentica Docker contra ghcr.io (ver paso 6 arriba) antes del primer
     "docker compose pull" de Lycet.
  4. Primer arranque manual:
       cd /opt/carmencita/deploy
       docker compose pull lycet_service
       docker compose up --build -d
  5. Configura los GitHub Secrets en los 3 repositorios:
     - Backend y Frontend: DROPLET_HOST, DROPLET_USER, DROPLET_SSH_KEY, ENV_FILE
     - Lycet: los mismos 4 (no necesita secret de registry: usa el GITHUB_TOKEN
       automatico del propio workflow para el push a ghcr.io)
EOF
