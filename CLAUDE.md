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
python manage.py load_proyectos --company <slug> [--file proyectos_bd.xlsx] [--dry-run]  # importa/sincroniza Project de UNA empresa desde Excel (hoja "Base de datos ")
python manage.py seed_demo [--company demo] [--clear]   # datos de demo en la empresa "demo" (se crea sola)
python manage.py migrate_attachments --company <slug> --from nextcloud --to local

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

## Multi-empresa (tenants)

Varias empresas en un mismo servidor, datos totalmente aislados. Modelo `accounts.Company`
(slug, prefijo de tickets + correlativo propio, marca: nombre/logos/favicon/colores/remitente).

- **URL por empresa:** todo vive bajo `/<slug>/` (`/embol/`, `/embol/acceso/login/`).
  `accounts.tenancy.CompanyMiddleware` (último de `MIDDLEWARE`) recorta el prefijo de
  `request.path_info` y lo agrega al *script prefix* de Django → `reverse()`/`{% url %}`
  salen prefijados sin tocar url patterns. `request.company` es la empresa del request.
  Sin prefijo solo hay: login genérico (superuser), `/empresas/` (panel superuser), admin.
- **Superuser = global** (`Profile.company` nulo): crea empresas en `/empresas/` y entra a
  cualquiera. Todo usuario operativo tiene UNA empresa principal (`Profile.company`, a donde
  cae sin prefijo) y, esporádicamente, adicionales (`Profile.extra_companies`, las da el
  superuser en `/empresas/<slug>/editar/`) donde opera con el MISMO rol (la matriz
  `RolePermission` de la empresa activa decide qué puede hacer). Un email = una cuenta
  (índice único `LOWER(email)`). No miembro de B en `/b/...` → 403. Pertenencia SIEMPRE vía
  `accounts.tenancy.is_member(user, company)` / `members_q(company)` (+ `.distinct()`),
  nunca comparando `profile.company` a mano. Selector "Cambiar de empresa" en el menú de
  usuario (`nav_companies`).
- **Con FK `company`:** Profile, Project, Label, Ticket, Attachment (desnormalizado para
  el borrado de blobs), AllowedDomain/AllowedEmail/BlockedEmail (bloqueo puntual que gana
  al dominio permitido), RolePermission (matriz por empresa),
  NextcloudConfig + NextcloudOAuthConfig (uno por empresa: cada cliente su Nextcloud).
  `EmailConfig` (SMTP) sigue global; el remitente es por empresa (`Company.email_from*`).
- **Reglas al escribir código:** filtrar SIEMPRE por `request.company` (helper
  `_get_ticket(request, pk)` en tickets/views.py); forms reciben `company=`;
  `users_with_capability(company, cap)` / `roles_with_capability(company, cap)`;
  `is_email_allowed(company, email)`; `get_backend(name, company=)`;
  `broadcast_board(company_id, ticket_id)` (grupo WS `board_<company_id>`).
  Nunca `reverse()` dentro de un thread (sin prefijo): usar `accounts.tenancy.company_url`.
- **Login/reset por empresa:** el de `/<slug>/` solo acepta miembros (o superuser); el
  genérico sin prefijo acepta a todos y redirige a la principal.
- **Migraciones que siembran capacidades** deben iterar `Company.objects.all()`.
- **Nextcloud OAuth:** el redirect URI lleva el prefijo → cada empresa registra
  `https://<host>/<slug>/acceso/nextcloud/callback/` en su app OAuth2.
- **Colores por empresa:** la CSP no permite `<style>` inline → `accounts:company_theme_css`
  sirve `--color-primary/--color-accent` (+ `-content` por luminancia) bajo `html[data-theme]`.
- **Tests:** `core.testing.TenantTestCase`/`TenantClient` prefijan `/embol` (la empresa
  inicial que crea la data migration `accounts/0021`); `make_user(email, role, company=)`.
