#!/bin/bash
# nginx-deploy.sh — instala/actualiza la config de nginx
# Uso: bash nginx-deploy.sh
# Nota: solo ejecutar cuando se cambie nginx.conf o en el primer deploy.
#       NO se ejecuta en cada deploy para no sobreescribir la config de certbot.

set -e

if [ ! -f .env ]; then
    echo "Error: no se encontró el archivo .env"
    exit 1
fi
set -a
source .env
set +a

PROJECT_NAME=${PROJECT_NAME:?La variable PROJECT_NAME no está definida en .env}
APP_PORT=${APP_PORT:-8000}
DOMAIN=${DOMAIN:?La variable DOMAIN no está definida en .env}
N8N_HOST_PORT=${N8N_HOST_PORT:-5680}
PROJECT_DIR=$(pwd)

NGINX_TEMPLATE="${PROJECT_NAME}.conf"
NGINX_AVAILABLE="/etc/nginx/sites-available/${PROJECT_NAME}.conf"
NGINX_ENABLED="/etc/nginx/sites-enabled/${PROJECT_NAME}.conf"

echo "▶ Generando ${NGINX_TEMPLATE}..."
sed -e "s|{{DOMAIN}}|${DOMAIN}|g" \
    -e "s|{{APP_PORT}}|${APP_PORT}|g" \
    -e "s|{{N8N_HOST_PORT}}|${N8N_HOST_PORT}|g" \
    -e "s|{{PROJECT_DIR}}|${PROJECT_DIR}|g" \
    nginx.conf > "${NGINX_TEMPLATE}"

echo "▶ Instalando config en nginx..."
sudo cp "${NGINX_TEMPLATE}" "${NGINX_AVAILABLE}"

if [ ! -L "${NGINX_ENABLED}" ]; then
    sudo ln -s "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
    echo "  Symlink creado: ${NGINX_ENABLED}"
fi

sudo nginx -t
sudo systemctl reload nginx
echo "✓ nginx actualizado y recargado."
