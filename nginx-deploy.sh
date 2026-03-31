#!/bin/bash
# nginx-deploy.sh — instala/actualiza la config de nginx
# Uso: bash nginx-deploy.sh
#
# Flujo primera vez:
#   1. make nginx          → detecta que no hay cert → instala config HTTP
#   2. sudo certbot certonly --webroot -w /var/www/certbot -d $DOMAIN
#   3. make nginx          → detecta cert existente → instala config HTTPS

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
PROJECT_DIR=$(pwd)

NGINX_AVAILABLE="/etc/nginx/sites-available/${PROJECT_NAME}.conf"
NGINX_ENABLED="/etc/nginx/sites-enabled/${PROJECT_NAME}.conf"
CERT_PATH="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"

# Si la config ya está instalada con SSL activo, no sobreescribir salvo que
# se pase --force como argumento (ej: bash nginx-deploy.sh --force)
FORCE="${1:-}"
if [ -f "${NGINX_AVAILABLE}" ] && grep -q "ssl_certificate" "${NGINX_AVAILABLE}" 2>/dev/null; then
    if [ "${FORCE}" != "--force" ]; then
        echo "✓ nginx ya tiene SSL configurado — sin cambios."
        echo "  Usa 'bash nginx-deploy.sh --force' para sobreescribir."
        exit 0
    fi
    echo "▶ --force: sobreescribiendo config nginx existente con SSL..."
fi

# Elegir template según si ya existe el certificado SSL
if [ -f "${CERT_PATH}" ]; then
    TEMPLATE="nginx.conf"
    echo "▶ Certificado SSL detectado — usando config HTTPS..."
else
    TEMPLATE="nginx-http.conf"
    echo "▶ Sin certificado SSL — usando config HTTP temporal..."
    echo "  Después de ejecutar este script, obtén el cert con:"
    echo "  sudo mkdir -p /var/www/certbot"
    echo "  sudo certbot certonly --webroot -w /var/www/certbot -d ${DOMAIN}"
    echo "  Luego vuelve a ejecutar: make nginx"
    echo ""
fi

echo "▶ Generando ${PROJECT_NAME}.conf desde ${TEMPLATE}..."
sed -e "s|{{DOMAIN}}|${DOMAIN}|g" \
    -e "s|{{APP_PORT}}|${APP_PORT}|g" \
    -e "s|{{PROJECT_DIR}}|${PROJECT_DIR}|g" \
    "${TEMPLATE}" > "${PROJECT_NAME}.conf"

echo "▶ Instalando config en nginx..."
sudo cp "${PROJECT_NAME}.conf" "${NGINX_AVAILABLE}"

if [ ! -L "${NGINX_ENABLED}" ]; then
    sudo ln -s "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
    echo "  Symlink creado: ${NGINX_ENABLED}"
fi

sudo nginx -t
sudo systemctl reload nginx
echo "✓ nginx actualizado y recargado."
