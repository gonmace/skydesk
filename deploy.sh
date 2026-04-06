#!/bin/bash
# deploy.sh — despliega el proyecto en el VPS
# Uso: bash deploy.sh

set -e

# ── Cargar variables del .env ──────────────────────────────────────────────────
if [ ! -f .env ]; then
    echo "Error: no se encontró el archivo .env. Ejecuta: bash setup.sh"
    exit 1
fi
set -a
source .env
set +a

PROJECT_NAME=${PROJECT_NAME:?La variable PROJECT_NAME no está definida en .env}
APP_PORT=${APP_PORT:-8000}
DOMAIN=${DOMAIN:?La variable DOMAIN no está definida en .env}
POSTGRES_MODE=${POSTGRES_MODE:-container}
N8N_DOMAIN=${N8N_DOMAIN:-}
N8N_MCP_ENABLED=${N8N_MCP_ENABLED:-}

echo "━━━ Desplegando: ${PROJECT_NAME} (${DOMAIN}) ━━━"
echo ""

# ── 1. Detener contenedores en ejecución ──────────────────────────────────────
echo "▶ Deteniendo contenedores..."
docker compose \
    --profile postgres \
    --profile n8n \
    --profile n8n-mcp \
    down --remove-orphans 2>/dev/null || true
docker network prune -f 2>/dev/null || true
echo ""

# ── 2. Verificar puertos disponibles ──────────────────────────────────────────
echo "▶ Verificando puertos..."
if ! bash check-ports.sh; then
    echo ""
    echo "Error: hay puertos ocupados. Resuelve los conflictos antes de continuar."
    exit 1
fi
echo ""

# ── 3. Actualizar código ───────────────────────────────────────────────────────
echo "▶ Actualizando código..."
git pull origin main

# ── 4. Construir lista de profiles ────────────────────────────────────────────
PROFILES=""

if [ "${POSTGRES_MODE}" = "container" ]; then
    PROFILES="${PROFILES} --profile postgres"
    echo "  PostgreSQL: contenedor Docker"
else
    echo "  PostgreSQL: servidor host (${POSTGRES_HOST:-host.docker.internal})"
    echo "  Asegúrate de que pg_hba.conf permita conexiones desde Docker (172.17.0.0/16)"
fi

if [ -n "${N8N_DOMAIN}" ]; then
    PROFILES="${PROFILES} --profile n8n"
    echo "  n8n: habilitado (${N8N_DOMAIN})"

    # Ajustar permisos del volumen n8n (corre como UID 1000 = node)
    mkdir -p volumes/n8n
    sudo chown -R 1000:1000 volumes/n8n

    if [ "${N8N_MCP_ENABLED}" = "true" ]; then
        PROFILES="${PROFILES} --profile n8n-mcp"
        echo "  n8n-MCP: habilitado (puerto ${N8N_MCP_PORT:-8002})"
    fi
else
    echo "  n8n: deshabilitado (N8N_DOMAIN no definido)"
fi

# ── 5. Reconstruir y reiniciar contenedores ────────────────────────────────────
echo ""
echo "▶ Reconstruyendo contenedores Docker..."
docker compose ${PROFILES} up -d --build

echo ""
echo "✓ Despliegue completado → https://${DOMAIN}"
[ -n "${N8N_DOMAIN}" ] && echo "✓ n8n disponible → https://${N8N_DOMAIN}"
