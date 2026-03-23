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

echo "━━━ Desplegando: ${PROJECT_NAME} (${DOMAIN}) ━━━"

# ── 1. Actualizar código ───────────────────────────────────────────────────────
echo "▶ Actualizando código..."
git pull origin main

# ── 2. Reconstruir y reiniciar contenedores ────────────────────────────────────
echo "▶ Reconstruyendo contenedores Docker..."
docker compose down
docker compose up -d --build

echo ""
echo "✓ Despliegue completado → http://${DOMAIN}"
