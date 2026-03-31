#!/bin/bash
# deploy.sh — despliega el proyecto en el VPS
# Uso: bash deploy.sh

set -e

# ── Cargar variables del .env ──────────────────────────────────────────────────
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

if [ "${DEBUG:-False}" = "True" ]; then
    echo "Error: DEBUG=True en .env — no se puede desplegar en modo debug"
    exit 1
fi
# N8N_DOMAIN=${N8N_DOMAIN:-}

echo "━━━ Desplegando: ${PROJECT_NAME} (${DOMAIN}) ━━━"

# ── 1. Actualizar código ───────────────────────────────────────────────────────
echo "▶ Actualizando código..."
git pull origin main

# ── 2. Permisos del volumen n8n (deshabilitado) ───────────────────────────────
# if [ -n "${N8N_DOMAIN}" ]; then
#     echo "▶ Ajustando permisos de n8n..."
#     mkdir -p volumes/n8n
#     sudo chown -R 1000:1000 volumes/n8n
# fi

# ── 3. Reconstruir y reiniciar contenedores ────────────────────────────────────
# NOTA: nginx NO se toca en cada deploy. Ejecutar `make nginx` solo manualmente
#       cuando cambie nginx.conf (primera instalación o cambio de config).
echo "▶ Reconstruyendo contenedores Docker..."
docker compose down
docker compose up -d --build

# n8n (deshabilitado)
# if [ -n "${N8N_DOMAIN}" ]; then
#     echo "  n8n habilitado (${N8N_DOMAIN})"
#     docker compose --profile n8n up -d --build
# fi

echo ""
echo "✓ Despliegue completado → http://${DOMAIN}"
