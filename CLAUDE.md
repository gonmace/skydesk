# CLAUDE.md

## Comandos clave

```bash
# Setup y dev
make setup          # genera .env interactivo (primera vez)
make install        # pip install requirements-dev + tailwind install
make dev-up         # levanta Redis + PostgreSQL + n8n/MCP según .env
make dev            # migrate + tailwind watch + runserver (hot reload completo)
make dev-check      # verifica estado del entorno

# Django
make migrate / migrations / superuser / shell / collect
python manage.py load_proyectos [--file proyectos_bd.xlsx] [--dry-run]  # importa/sincroniza Project desde Excel (hoja "Base de datos ")

# Producción
make nginx          # configura nginx (SOLO la primera vez — certbot modifica este archivo)
make deploy         # git pull + verifica puertos + rebuild
make n8n-update     # actualiza n8n (rebuild imagen + restart, preserva volumen)
make n8n-export     # exporta workflows dev a n8n/workflows/
```

On Windows: `NPM_BIN_PATH = r'C:\Program Files\nodejs\npm.cmd'` en `settings.py` dentro del bloque `if DEBUG:`.

## Arquitectura

`core/settings.py` único — comportamiento por variables de entorno:
- Sin `POSTGRES_DB` → SQLite | con `POSTGRES_DB` → PostgreSQL
- `POSTGRES_MODE=host` → contenedores usan `host.docker.internal`
- Sin `EMAIL_HOST` → consola | con `EMAIL_HOST` → SMTP
- `DEBUG=True` → axes DB handler, browser-reload, tailwind activo
- `DEBUG=False` → axes cache handler, HSTS, CSP estricto

**Docker Compose profiles** (gestionados automáticamente por `deploy.sh`):
| Profile | Servicio | Condición |
|---------|----------|-----------|
| `postgres` | PostgreSQL | `POSTGRES_MODE=container` |
| `n8n` | n8n | `N8N_DOMAIN` definido |
| `n8n-mcp` | n8n-MCP | `N8N_MCP_ENABLED=true` + n8n activo |
| — | Redis + Django | Siempre activos |

**Puertos:** `APP_PORT` (8000), `N8N_PORT` (8001), `N8N_MCP_PORT` (8002). Todos bindean a `127.0.0.1` en producción. Redis no expone puerto al exterior.

**Static files:** Whitenoise `CompressedManifestStaticFilesStorage` → hashes en filenames + `.gz` pre-comprimidos. nginx sirve `/static/` con `gzip_static on`. Cache `immutable` 365d es seguro por los hashes.

**Hot reload dev:** `make dev` corre `tailwind start &` + `runserver --watch-dir static/css/dist`. Cambios CSS → Tailwind recompila → Django detecta → browser-reload recarga.

**Tailwind/DaisyUI:** v4.2 / v5.5. Deps en `devDependencies` de `package.json`. En producción el Dockerfile compila CSS en stage Node y copia solo el CSS al stage Python (sin node_modules en prod).

**n8n:** subdominio propio, imagen custom con Python 3.12, comparte PostgreSQL (DB `n8n`). `N8N_ENCRYPTION_KEY` no cambiar nunca. Actualizar con `make n8n-update`.

**nginx:** `make nginx` solo una vez — certbot lo modifica para SSL y `deploy.sh` nunca lo toca.

**Al agregar apps Django:** añadir a `INSTALLED_APPS` + `@source "../../../<app>"` en `theme/static_src/src/styles.css`.
