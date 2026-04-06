#!/bin/bash
# setup.sh — configuración inicial del proyecto
# Genera el archivo .env con los valores que elijas.
# Uso: bash setup.sh

set -e
set -a  # auto-exportar todas las variables para que Python las vea via os.environ

# ── Utilidades ─────────────────────────────────────────────────────────────────
gen_secret() {
    python3 -c "import secrets; print(secrets.token_urlsafe($1))"
}

gen_hex() {
    python3 -c "import secrets; print(secrets.token_hex($1))"
}

# Lee un valor del .env existente (si existe)
get_env() {
    local val
    val=$(grep "^${1}=" .env 2>/dev/null | head -1 | cut -d'=' -f2-)
    val=$(echo "$val" | sed "s/^'//;s/'$//")
    echo "$val"
}

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   Setup: Django Skeleton"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ -f .env ]; then
    echo "  .env existente detectado — los valores actuales se usarán como default."
    echo ""
fi

# ── Entorno ───────────────────────────────────────────────────────────────────
_ENV_DEFAULT=$(get_env DEBUG)
[ "${_ENV_DEFAULT}" = "True" ] && _ENV_DEFAULT=dev || _ENV_DEFAULT=prod
read -p "¿Entorno? (dev/prod) [${_ENV_DEFAULT}]: " ENV_TYPE
ENV_TYPE=${ENV_TYPE:-${_ENV_DEFAULT}}
echo ""

# ── Nombre del proyecto ───────────────────────────────────────────────────────
DIR_NAME=$(basename "$(pwd)")
_DEFAULT=$(get_env PROJECT_NAME)
read -p "Nombre del proyecto [${_DEFAULT:-${DIR_NAME}}]: " PROJECT_NAME
PROJECT_NAME=${PROJECT_NAME:-${_DEFAULT:-${DIR_NAME}}}
PROJECT_NAME=$(echo "${PROJECT_NAME}" | tr ' ' '-' | tr '[:upper:]' '[:lower:]')
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# ── MODO DEV ──────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
if [ "${ENV_TYPE}" = "dev" ]; then
    DEBUG=True
    DOMAIN=localhost

    # Puertos
    _DEFAULT=$(get_env APP_PORT)
    read -p "Puerto base de la app Django [${_DEFAULT:-8000}]: " APP_PORT
    APP_PORT=${APP_PORT:-${_DEFAULT:-8000}}
    N8N_PORT=$((APP_PORT + 1))
    N8N_MCP_PORT=$((APP_PORT + 2))
    echo ""

    # PostgreSQL — siempre contenedor en dev
    POSTGRES_MODE=container
    POSTGRES_HOST=localhost
    POSTGRES_DB="${PROJECT_NAME}_db"
    POSTGRES_USER="${PROJECT_NAME}_user"
    _PG_PASS=$(get_env POSTGRES_PASSWORD)
    POSTGRES_PASSWORD=${_PG_PASS:-$(gen_secret 24)}
    POSTGRES_PORT=5432
    POSTGRES_HOST_PORT=5432

    # n8n
    _N8N_CURRENT=$(get_env N8N_DOMAIN)
    [ -n "${_N8N_CURRENT}" ] && _N8N_DEFAULT="s" || _N8N_DEFAULT="N"
    read -p "¿Habilitar n8n? (s/N) [${_N8N_DEFAULT}]: " ENABLE_N8N
    ENABLE_N8N=${ENABLE_N8N:-${_N8N_DEFAULT}}
    echo ""

    N8N_DOMAIN=""
    N8N_ENCRYPTION_KEY=""
    N8N_MCP_ENABLED=""
    N8N_MCP_AUTH_TOKEN=""

    if [ "${ENABLE_N8N}" = "s" ] || [ "${ENABLE_N8N}" = "S" ]; then
        N8N_DOMAIN=localhost
        _N8N_KEY=$(get_env N8N_ENCRYPTION_KEY)
        N8N_ENCRYPTION_KEY=${_N8N_KEY:-$(gen_secret 32)}

        _MCP_CURRENT=$(get_env N8N_MCP_ENABLED)
        [ "${_MCP_CURRENT}" = "true" ] && _MCP_DEFAULT="s" || _MCP_DEFAULT="N"
        read -p "  ¿Habilitar n8n-MCP? (s/N) [${_MCP_DEFAULT}]: " ENABLE_MCP
        ENABLE_MCP=${ENABLE_MCP:-${_MCP_DEFAULT}}
        echo ""

        if [ "${ENABLE_MCP}" = "s" ] || [ "${ENABLE_MCP}" = "S" ]; then
            N8N_MCP_ENABLED=true
            _MCP_TOKEN=$(get_env N8N_MCP_AUTH_TOKEN)
            N8N_MCP_AUTH_TOKEN=${_MCP_TOKEN:-$(gen_secret 32)}
        fi
    fi

    # Secretos
    _SK=$(get_env SECRET_KEY)
    SECRET_KEY=${_SK:-$(gen_secret 50)}
    ADMIN_URL=admin/
    ALLOWED_HOSTS="localhost,127.0.0.1"
    CSRF_TRUSTED_ORIGINS="http://localhost:${APP_PORT}"
    EMAIL_HOST=""

# ══════════════════════════════════════════════════════════════════════════════
# ── MODO PROD ─────────────────────────────────────────════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
else
    DEBUG=False

    # Dominio
    _DEFAULT=$(get_env DOMAIN)
    while true; do
        read -p "Dominio para Django (ej: miapp.com) [${_DEFAULT}]: " DOMAIN
        DOMAIN=${DOMAIN:-${_DEFAULT}}
        [ -n "${DOMAIN}" ] && break
        echo "  El dominio no puede estar vacío."
    done
    echo ""

    # PostgreSQL
    _PG_MODE=$(get_env POSTGRES_MODE)
    echo "PostgreSQL:"
    echo "  1) Contenedor Docker — recomendado"
    echo "  2) Host del servidor — PostgreSQL ya instalado en el VPS"
    echo ""
    [ "${_PG_MODE}" = "host" ] && _PG_OPT=2 || _PG_OPT=1
    read -p "Opción [${_PG_OPT}]: " PG_CHOICE
    PG_CHOICE=${PG_CHOICE:-${_PG_OPT}}
    echo ""

    if [ "${PG_CHOICE}" = "2" ]; then
        POSTGRES_MODE=host
        POSTGRES_HOST=host.docker.internal
        _DEFAULT=$(get_env POSTGRES_DB)
        read -p "  Base de datos [${_DEFAULT:-${PROJECT_NAME}_db}]: " POSTGRES_DB
        POSTGRES_DB=${POSTGRES_DB:-${_DEFAULT:-${PROJECT_NAME}_db}}
        _DEFAULT=$(get_env POSTGRES_USER)
        read -p "  Usuario [${_DEFAULT:-${PROJECT_NAME}_user}]: " POSTGRES_USER
        POSTGRES_USER=${POSTGRES_USER:-${_DEFAULT:-${PROJECT_NAME}_user}}
        read -sp "  Contraseña (Enter para mantener actual): " POSTGRES_PASSWORD_NEW; echo
        _PG_PASS=$(get_env POSTGRES_PASSWORD)
        POSTGRES_PASSWORD=${POSTGRES_PASSWORD_NEW:-${_PG_PASS}}
        _DEFAULT=$(get_env POSTGRES_PORT)
        read -p "  Puerto [${_DEFAULT:-5432}]: " POSTGRES_PORT
        POSTGRES_PORT=${POSTGRES_PORT:-${_DEFAULT:-5432}}
        POSTGRES_HOST_PORT=${POSTGRES_PORT}
        echo ""
        echo "  NOTA: Asegúrate de que PostgreSQL esté configurado para aceptar"
        echo "  conexiones desde la red Docker (172.17.0.0/16) en pg_hba.conf."
        echo ""
    else
        POSTGRES_MODE=container
        POSTGRES_HOST=postgres
        _DEFAULT=$(get_env POSTGRES_DB)
        POSTGRES_DB=${_DEFAULT:-${PROJECT_NAME}_db}
        _DEFAULT=$(get_env POSTGRES_USER)
        POSTGRES_USER=${_DEFAULT:-${PROJECT_NAME}_user}
        _PG_PASS=$(get_env POSTGRES_PASSWORD)
        POSTGRES_PASSWORD=${_PG_PASS:-$(gen_secret 24)}
        POSTGRES_PORT=5432
        POSTGRES_HOST_PORT=5432
    fi

    # Puertos
    _DEFAULT=$(get_env APP_PORT)
    read -p "Puerto base de la app Django [${_DEFAULT:-8000}]: " APP_PORT
    APP_PORT=${APP_PORT:-${_DEFAULT:-8000}}
    N8N_PORT=$((APP_PORT + 1))
    N8N_MCP_PORT=$((APP_PORT + 2))
    echo ""

    # n8n
    _N8N_CURRENT=$(get_env N8N_DOMAIN)
    [ -n "${_N8N_CURRENT}" ] && _N8N_DEFAULT="s" || _N8N_DEFAULT="N"
    read -p "¿Habilitar n8n? (s/N) [${_N8N_DEFAULT}]: " ENABLE_N8N
    ENABLE_N8N=${ENABLE_N8N:-${_N8N_DEFAULT}}
    echo ""

    N8N_DOMAIN=""
    N8N_ENCRYPTION_KEY=""
    N8N_MCP_ENABLED=""
    N8N_API_KEY=""
    N8N_MCP_AUTH_TOKEN=""

    if [ "${ENABLE_N8N}" = "s" ] || [ "${ENABLE_N8N}" = "S" ]; then
        while true; do
            read -p "  Dominio para n8n [${_N8N_CURRENT:-n8n.${DOMAIN}}]: " N8N_DOMAIN
            N8N_DOMAIN=${N8N_DOMAIN:-${_N8N_CURRENT:-n8n.${DOMAIN}}}
            [ -n "${N8N_DOMAIN}" ] && break
            echo "  El dominio de n8n no puede estar vacío."
        done
        _N8N_KEY=$(get_env N8N_ENCRYPTION_KEY)
        N8N_ENCRYPTION_KEY=${_N8N_KEY:-$(gen_secret 32)}
        [ -z "${_N8N_KEY}" ] && echo "  N8N_ENCRYPTION_KEY generada automáticamente."
        echo ""

        _MCP_CURRENT=$(get_env N8N_MCP_ENABLED)
        [ "${_MCP_CURRENT}" = "true" ] && _MCP_DEFAULT="s" || _MCP_DEFAULT="N"
        read -p "  ¿Habilitar n8n-MCP? (s/N) [${_MCP_DEFAULT}]: " ENABLE_MCP
        ENABLE_MCP=${ENABLE_MCP:-${_MCP_DEFAULT}}
        echo ""

        if [ "${ENABLE_MCP}" = "s" ] || [ "${ENABLE_MCP}" = "S" ]; then
            N8N_MCP_ENABLED=true
            _MCP_TOKEN=$(get_env N8N_MCP_AUTH_TOKEN)
            N8N_MCP_AUTH_TOKEN=${_MCP_TOKEN:-$(gen_secret 32)}
            [ -z "${_MCP_TOKEN}" ] && echo "  N8N_MCP_AUTH_TOKEN generada automáticamente."
            echo "  Recuerda completar N8N_API_KEY en .env después de configurar n8n."
            echo ""
        fi
    fi

    # Admin URL
    _DEFAULT=$(get_env ADMIN_URL)
    RANDOM_ADMIN="$(gen_hex 6)/"
    read -p "URL del panel admin [${_DEFAULT:-${RANDOM_ADMIN}}]: " ADMIN_URL
    ADMIN_URL=${ADMIN_URL:-${_DEFAULT:-${RANDOM_ADMIN}}}
    echo ""

    # Email SMTP
    _EMAIL_CURRENT=$(get_env EMAIL_HOST)
    [ -n "${_EMAIL_CURRENT}" ] && _EMAIL_DEFAULT="s" || _EMAIL_DEFAULT="N"
    read -p "¿Configurar email SMTP? (s/N) [${_EMAIL_DEFAULT}]: " ENABLE_EMAIL
    ENABLE_EMAIL=${ENABLE_EMAIL:-${_EMAIL_DEFAULT}}
    echo ""

    EMAIL_HOST=""
    EMAIL_PORT=587
    EMAIL_USE_TLS=True
    EMAIL_HOST_USER=""
    EMAIL_HOST_PASSWORD=""
    DEFAULT_FROM_EMAIL="noreply@${DOMAIN}"

    if [ "${ENABLE_EMAIL}" = "s" ] || [ "${ENABLE_EMAIL}" = "S" ]; then
        _DEFAULT=$(get_env EMAIL_HOST)
        read -p "  SMTP Host [${_DEFAULT:-smtp.gmail.com}]: " EMAIL_HOST
        EMAIL_HOST=${EMAIL_HOST:-${_DEFAULT:-smtp.gmail.com}}
        _DEFAULT=$(get_env EMAIL_PORT)
        read -p "  Puerto [${_DEFAULT:-587}]: " EMAIL_PORT
        EMAIL_PORT=${EMAIL_PORT:-${_DEFAULT:-587}}
        _DEFAULT=$(get_env EMAIL_HOST_USER)
        read -p "  Usuario [${_DEFAULT}]: " EMAIL_HOST_USER
        EMAIL_HOST_USER=${EMAIL_HOST_USER:-${_DEFAULT}}
        read -sp "  Contraseña (Enter para mantener actual): " EMAIL_HOST_PASSWORD_NEW; echo
        _EMAIL_PASS=$(get_env EMAIL_HOST_PASSWORD)
        EMAIL_HOST_PASSWORD=${EMAIL_HOST_PASSWORD_NEW:-${_EMAIL_PASS}}
        _DEFAULT=$(get_env DEFAULT_FROM_EMAIL)
        read -p "  From email [${_DEFAULT:-noreply@${DOMAIN}}]: " DEFAULT_FROM_EMAIL
        DEFAULT_FROM_EMAIL=${DEFAULT_FROM_EMAIL:-${_DEFAULT:-noreply@${DOMAIN}}}
        echo ""
    fi

    # Secretos
    _SK=$(get_env SECRET_KEY)
    SECRET_KEY=${_SK:-$(gen_secret 50)}
    ALLOWED_HOSTS="${DOMAIN}"
    CSRF_TRUSTED_ORIGINS="https://${DOMAIN}"
fi

# ── Escribir .env ──────────────────────────────────────────────────────────────
python3 - << 'PYEOF'
import os

def kv(key, value):
    if value and any(c in value for c in '$`"\\'):
        value = "'" + value.replace("'", "'\\''") + "'"
    return f"{key}={value}"

env_type = os.environ.get("ENV_TYPE", "prod")
n8n_domain = os.environ.get("N8N_DOMAIN", "")
is_dev = env_type == "dev"

lines = [
    "# Generado por setup.sh",
    "# Edita este archivo para ajustar la configuración.",
    "",
    "# ── Proyecto ──────────────────────────────────────────────────────────────",
    kv("PROJECT_NAME", os.environ.get("PROJECT_NAME", "")),
    "",
    "# ── Puertos ───────────────────────────────────────────────────────────────",
    kv("APP_PORT", os.environ.get("APP_PORT", "8000")),
    kv("N8N_PORT", os.environ.get("N8N_PORT", "8001")),
    kv("N8N_MCP_PORT", os.environ.get("N8N_MCP_PORT", "8002")),
    "",
    "# ── Django ────────────────────────────────────────────────────────────────",
    kv("SECRET_KEY", os.environ.get("SECRET_KEY", "")),
    kv("DEBUG", os.environ.get("DEBUG", "False")),
    kv("ALLOWED_HOSTS", os.environ.get("ALLOWED_HOSTS", "")),
    kv("CSRF_TRUSTED_ORIGINS", os.environ.get("CSRF_TRUSTED_ORIGINS", "")),
    kv("ADMIN_URL", os.environ.get("ADMIN_URL", "admin/")),
    "",
    "# ── PostgreSQL ────────────────────────────────────────────────────────────",
    kv("POSTGRES_MODE", os.environ.get("POSTGRES_MODE", "container")),
    kv("POSTGRES_DB", os.environ.get("POSTGRES_DB", "")),
    kv("POSTGRES_USER", os.environ.get("POSTGRES_USER", "")),
    kv("POSTGRES_PASSWORD", os.environ.get("POSTGRES_PASSWORD", "")),
    kv("POSTGRES_HOST", os.environ.get("POSTGRES_HOST", "localhost")),
    kv("POSTGRES_PORT", os.environ.get("POSTGRES_PORT", "5432")),
    kv("POSTGRES_HOST_PORT", os.environ.get("POSTGRES_HOST_PORT", "5432")),
    "",
    "# ── Redis ─────────────────────────────────────────────────────────────────",
    "REDIS_URL=redis://localhost:6379/0" if is_dev else "REDIS_URL=redis://redis:6379/0",
    "",
]

if not is_dev:
    lines.insert(4, kv("DOMAIN", os.environ.get("DOMAIN", "")))
    lines.insert(5, "")

email_host = os.environ.get("EMAIL_HOST", "")
if email_host:
    lines += [
        "# ── Email (SMTP) ──────────────────────────────────────────────────────────",
        kv("EMAIL_HOST", email_host),
        kv("EMAIL_PORT", os.environ.get("EMAIL_PORT", "587")),
        kv("EMAIL_USE_TLS", os.environ.get("EMAIL_USE_TLS", "True")),
        kv("EMAIL_HOST_USER", os.environ.get("EMAIL_HOST_USER", "")),
        kv("EMAIL_HOST_PASSWORD", os.environ.get("EMAIL_HOST_PASSWORD", "")),
        kv("DEFAULT_FROM_EMAIL", os.environ.get("DEFAULT_FROM_EMAIL", "")),
        "",
    ]

if n8n_domain and n8n_domain != "localhost":
    lines += [
        "# ── n8n ───────────────────────────────────────────────────────────────────",
        kv("N8N_DOMAIN", n8n_domain),
        kv("N8N_ENCRYPTION_KEY", os.environ.get("N8N_ENCRYPTION_KEY", "")),
        "",
        "# ── Integración Django ↔ n8n ──────────────────────────────────────────────",
        f"N8N_URL=https://{n8n_domain}",
        f"N8N_WEBHOOK_URL=https://{n8n_domain}/webhook/",
        "",
    ]
elif n8n_domain == "localhost":
    app_port = int(os.environ.get("APP_PORT", "8000"))
    n8n_port = app_port + 1
    lines += [
        "# ── n8n ───────────────────────────────────────────────────────────────────",
        kv("N8N_DOMAIN", n8n_domain),
        kv("N8N_ENCRYPTION_KEY", os.environ.get("N8N_ENCRYPTION_KEY", "")),
        "",
        "# ── Integración Django ↔ n8n ──────────────────────────────────────────────",
        f"N8N_URL=http://localhost:{n8n_port}",
        f"N8N_WEBHOOK_URL=http://localhost:{n8n_port}/webhook/",
        "",
    ]

if os.environ.get("N8N_MCP_ENABLED") == "true":
    lines += [
        "# ── n8n-MCP ───────────────────────────────────────────────────────────────",
        "N8N_MCP_ENABLED=true",
        kv("N8N_MCP_AUTH_TOKEN", os.environ.get("N8N_MCP_AUTH_TOKEN", "")),
        "# Completa N8N_API_KEY después del primer inicio de n8n: Settings > API",
        "N8N_API_KEY=",
        "",
    ]

with open(".env", "w") as f:
    f.write("\n".join(lines) + "\n")
PYEOF

# ── Resumen ───────────────────────────────────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   Configuración completada"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Proyecto:    ${PROJECT_NAME}"
echo "  Entorno:     ${ENV_TYPE}"
echo "  PostgreSQL:  ${POSTGRES_MODE} (${POSTGRES_HOST}:${POSTGRES_PORT})"

if [ "${ENV_TYPE}" = "dev" ]; then
    echo "  Django:      http://localhost:${APP_PORT}"
    echo "  Admin URL:   http://localhost:${APP_PORT}/${ADMIN_URL}"
    [ "${ENABLE_N8N}" = "s" ] || [ "${ENABLE_N8N}" = "S" ] && \
        echo "  n8n:         http://localhost:${N8N_PORT}"
    echo ""
    echo "Archivo .env generado correctamente."
    echo ""
    echo "━━━ Próximos pasos ━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  1. Levanta los servicios Docker:"
    echo "     make dev-up"
    echo ""
    echo "  2. Inicia Django:"
    echo "     make dev"
    echo ""
else
    echo "  Django:      https://${DOMAIN}  (puerto ${APP_PORT})"
    echo "  Admin URL:   https://${DOMAIN}/${ADMIN_URL}"
    [ -n "${N8N_DOMAIN}" ] && echo "  n8n:         https://${N8N_DOMAIN}  (puerto ${N8N_PORT})"
    [ "${N8N_MCP_ENABLED}" = "true" ] && echo "  n8n-MCP:     https://${N8N_DOMAIN}/mcp  (puerto ${N8N_MCP_PORT})"
    echo ""
    echo "Archivo .env generado correctamente."
    echo ""
    echo "━━━ Próximos pasos ━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  1. Configura nginx (solo la primera vez):"
    echo "     make nginx"
    echo ""
    echo "  2. Obtén certificado SSL con certbot:"
    CERTBOT_DOMAINS="-d ${DOMAIN}"
    [ -n "${N8N_DOMAIN}" ] && CERTBOT_DOMAINS="${CERTBOT_DOMAINS} -d ${N8N_DOMAIN}"
    echo "     sudo certbot --nginx ${CERTBOT_DOMAINS}"
    echo ""
    echo "  3. Despliega la aplicación:"
    echo "     make deploy"
    echo ""
    [ "${POSTGRES_MODE}" = "host" ] && echo "  NOTA: PostgreSQL en host — configura pg_hba.conf antes de hacer deploy."
    [ "${N8N_MCP_ENABLED}" = "true" ] && echo "  NOTA: Completa N8N_API_KEY en .env después del primer inicio de n8n."
fi
echo ""
