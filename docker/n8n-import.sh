#!/bin/bash
# Importa workflows y credenciales al n8n de producción.
# Uso: make n8n-import
# Requiere: N8N_ENCRYPTION_KEY igual al entorno origen.

set -e

WORKFLOWS_DIR="./n8n/workflows"
CREDENTIALS_DIR="./n8n/credentials"

if [ ! -d "$WORKFLOWS_DIR" ]; then
    echo "Error: no se encontró $WORKFLOWS_DIR"
    echo "  Ejecuta primero 'make n8n-export' en el entorno origen y haz push."
    exit 1
fi

echo "▶ Copiando workflows al contenedor..."
docker compose exec -T n8n mkdir -p /home/node/.n8n/imports/workflows/
docker compose cp "$WORKFLOWS_DIR/." n8n:/home/node/.n8n/imports/workflows/

echo "▶ Importando workflows..."
docker compose exec -T n8n \
    n8n import:workflow --separate --input=/home/node/.n8n/imports/workflows/

if [ -d "$CREDENTIALS_DIR" ] && [ "$(ls -A "$CREDENTIALS_DIR" 2>/dev/null)" ]; then
    echo "▶ Copiando credenciales al contenedor..."
    docker compose exec -T n8n mkdir -p /home/node/.n8n/imports/credentials/
    docker compose cp "$CREDENTIALS_DIR/." n8n:/home/node/.n8n/imports/credentials/

    echo "▶ Importando credenciales..."
    docker compose exec -T n8n \
        n8n import:credentials --separate --input=/home/node/.n8n/imports/credentials/
else
    echo "  Sin credenciales para importar."
fi

echo ""
echo "✓ Importación completada."
echo "  Reinicia n8n para activar los workflows: docker compose restart n8n"
