#!/bin/bash
# Importa workflows (y credenciales si existen) al n8n de producción.
# Uso: make n8n-import
# Requiere: el contenedor n8n levantado (docker compose --profile n8n up -d).
#           Para importar credenciales encriptadas, N8N_ENCRYPTION_KEY debe ser
#           igual a la del entorno de origen.

set -e

WORKFLOWS_DIR="./n8n/workflows"
CREDENTIALS_DIR="./n8n/credentials"

if [ ! -d "$WORKFLOWS_DIR" ] || [ -z "$(ls -A "$WORKFLOWS_DIR" 2>/dev/null)" ]; then
    echo "Error: no hay workflows en $WORKFLOWS_DIR"
    echo "  Ejecuta 'make n8n-export' en el entorno origen y haz push."
    exit 1
fi

echo "▶ Copiando workflows al contenedor..."
docker compose exec n8n mkdir -p /home/node/.n8n/imports/workflows/
docker compose cp "$WORKFLOWS_DIR/." n8n:/home/node/.n8n/imports/workflows/

echo "▶ Importando workflows..."
docker compose exec n8n \
    n8n import:workflow --separate --input=/home/node/.n8n/imports/workflows/

if [ -d "$CREDENTIALS_DIR" ] && [ -n "$(ls -A "$CREDENTIALS_DIR" 2>/dev/null)" ]; then
    echo "▶ Copiando credenciales al contenedor..."
    docker compose exec n8n mkdir -p /home/node/.n8n/imports/credentials/
    docker compose cp "$CREDENTIALS_DIR/." n8n:/home/node/.n8n/imports/credentials/

    echo "▶ Importando credenciales..."
    docker compose exec n8n \
        n8n import:credentials --separate --input=/home/node/.n8n/imports/credentials/
else
    echo "  Sin credenciales para importar (cargar la credencial OpenAI en la UI)."
fi

echo ""
echo "✓ Importación completada."
echo "  Reinicia n8n para activar los workflows: docker compose restart n8n"
