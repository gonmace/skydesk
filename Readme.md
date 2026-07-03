# Django Skeleton

Skeleton para desplegar Django en un VPS con nginx como reverse proxy. Incluye soporte opcional para n8n (automatización) y n8n-MCP (integración con Claude Code / clientes MCP).

## Stack

| Componente | Tecnología |
|---|---|
| Framework | Django 5.2+ |
| Servidor WSGI | Gunicorn (3 workers) |
| Base de datos | PostgreSQL 17 (contenedor o host) |
| Cache / Sesiones | Redis 7 |
| CSS | Tailwind CSS v4.2 + DaisyUI v5.5 |
| Archivos estáticos | Whitenoise (`CompressedManifestStaticFilesStorage`) + nginx (`gzip_static`) |
| Seguridad | django-axes (cache backend), django-csp, HSTS |
| Hot reload (dev) | django-browser-reload |
| Automatización (opcional) | n8n |
| MCP Server (opcional) | n8n-MCP |
| Reverse proxy | Nginx (host) + Let's Encrypt |

---

## Quick Start (VPS)

```bash
# 1. Clonar el proyecto
git clone <repo> miproyecto && cd miproyecto

# 2. Configurar — genera .env de forma interactiva
make setup

# 3. Configurar nginx (SOLO la primera vez — no volver a ejecutar tras certbot)
make nginx

# 4. Obtener certificado SSL
sudo certbot --nginx -d tudominio.com
# Si n8n está habilitado, agregar también: -d n8n.tudominio.com

# 5. Desplegar
make deploy
```

Para deploys posteriores solo se necesita `make deploy` — hace `git pull` + verifica puertos + rebuild automáticamente. **Nunca volver a ejecutar `make nginx`** después de que certbot configuró el SSL.

---

## Desarrollo local

### Opción A — Mínimo (solo SQLite, sin contenedores)

Ideal para trabajar en templates, vistas y lógica de negocio sin necesitar base de datos completa.

```bash
make install           # instala dependencias Python + Tailwind
make setup             # genera .env (elige SQLite / sin n8n)
make dev               # migrate + tailwind watcher + runserver
```

> En este modo axes usa el backend de base de datos en lugar de Redis — no hay crash si Redis no está disponible.

### Opción B — Completo (PostgreSQL + Redis en Docker)

```bash
make install           # instala dependencias Python + Tailwind
make setup             # genera .env con PostgreSQL
make dev-up            # levanta Redis + PostgreSQL (+ n8n/MCP si están en .env)
make dev-check         # verifica que todo esté corriendo
make dev               # migrate + tailwind watcher + runserver
```

En ambos casos Django corre nativo en el host (no en Docker). Redis en Docker es accesible en `localhost:6379`.

### Hot reload

`make dev` lanza Tailwind en background y Django con `django-browser-reload`:

- **Python y templates**: Django recarga automáticamente → el browser se refresca solo
- **CSS**: Tailwind recompila el CSS → refrescar el browser manualmente

### Dos terminales (alternativa a `make dev`)

```bash
# Terminal 1 — watcher CSS
python manage.py tailwind start

# Terminal 2 — servidor Django
python manage.py runserver
```

### Probar con datos y roles distintos

```bash
python manage.py seed_demo   # usuarios (los 4 roles) + tickets de demo
```

Ver [TESTING-ROLES.md](TESTING-ROLES.md) para credenciales, cómo tener varios roles logueados
en paralelo y el impersonador dev (solo superuser + `DEBUG=True`) para navegar como un
usuario real sin cerrar tu sesión.

### Comportamiento automático según `.env`

| Variable | Ausente | Presente |
|---|---|---|
| `POSTGRES_DB` | SQLite | PostgreSQL |
| `N8N_DOMAIN` | n8n deshabilitado | n8n en contenedor |
| `REDIS_URL` | `localhost:6379` | valor configurado |

---

## PostgreSQL: contenedor vs host

Controla el comportamiento con `POSTGRES_MODE` en `.env`:

### Contenedor Docker (default)
```env
POSTGRES_MODE=container
POSTGRES_HOST=postgres
```
PostgreSQL corre en Docker, incluido en `docker-compose.yml` con el profile `postgres`.

### PostgreSQL del servidor host
```env
POSTGRES_MODE=host
POSTGRES_HOST=host.docker.internal
```
Los contenedores se conectan al PostgreSQL instalado en el VPS via `host.docker.internal`. El contenedor postgres **no se inicia**.

**Requisitos para modo host:**
1. `listen_addresses` en `postgresql.conf` debe incluir la IP del bridge Docker (o `*`)
2. `pg_hba.conf` debe aceptar conexiones desde la red Docker (`172.17.0.0/16`):
   ```
   host  all  all  172.17.0.0/16  md5
   ```
3. Crear manualmente las bases de datos del proyecto y `n8n`

---

## Servicios opcionales

Los servicios opcionales se activan via Docker Compose profiles. `deploy.sh` los gestiona automáticamente según el `.env`.

### n8n

Habilitar en `.env`:
```env
N8N_DOMAIN=n8n.tudominio.com
N8N_ENCRYPTION_KEY=clave-generada-por-setup
```

- Subdominio propio con imagen custom (Python 3.12 integrado para Code nodes)
- Comparte PostgreSQL con base de datos separada (`n8n`)
- Workflows en `n8n/workflows/` se importan automáticamente al arrancar
- Exportar workflows del dev: `make n8n-export`
- **`N8N_ENCRYPTION_KEY` debe mantenerse constante** — cambiarla invalida credenciales guardadas

### n8n-MCP

Requiere n8n habilitado. Habilitar en `.env`:
```env
N8N_MCP_ENABLED=true
N8N_API_KEY=<generar en n8n: Settings > API>
N8N_MCP_AUTH_TOKEN=token-generado-por-setup
```

Expone un servidor MCP sobre HTTP en `https://n8n.tudominio.com/mcp`. Permite integrar n8n con Claude Code u otros clientes MCP.

---

## Puertos

Los servicios usan puertos consecutivos desde `APP_PORT`. Para cambiarlos, ajusta solo `APP_PORT` en `.env` (los demás se calculan en `setup.sh`).

| Servicio | Puerto default | Variable |
|---|---|---|
| Django | 8000 | `APP_PORT` |
| n8n | 8001 | `N8N_PORT` |
| n8n-MCP | 8002 | `N8N_MCP_PORT` |
| Redis | interno | — |
| PostgreSQL | 5432 | `POSTGRES_HOST_PORT` (solo dev) |

En producción todos los puertos bindean a `127.0.0.1` — solo accesibles via nginx. Redis no expone puerto al exterior en ningún entorno.

---

## Actualizar n8n

n8n no tiene actualización desde la UI web. El proceso es:

```bash
make n8n-update   # rebuild imagen custom + restart contenedor
```

Esto reconstruye la imagen con la última versión de n8n, reinicia el contenedor y preserva todos los datos en `./volumes/n8n`. Para controlar la versión exacta, edita la imagen base en `docker/n8n.Dockerfile`.

---

## Tailwind + DaisyUI

Las versiones se gestionan en `theme/static_src/package.json` (devDependencies):

- **Tailwind CSS**: `^4.2.2`
- **DaisyUI**: `^5.5.19`

En **desarrollo**: `make install` → `npm install` instala los paquetes.

En **producción**: el Dockerfile usa `npm ci && npm run build` en una stage Node aislada. El CSS compilado y minificado se copia a la imagen Python final. **Los módulos npm no están en la imagen de producción.**

Para actualizar versiones: edita `package.json`, corre `npm update` en `theme/static_src/` y regenera `package-lock.json`.

---

## Archivos estáticos

Whitenoise + nginx trabajando en conjunto:

1. `collectstatic` genera archivos con hashes en el nombre (`styles.abc123.css`) y versiones `.gz` pre-comprimidas
2. nginx intercepta `/static/` y sirve directamente desde `staticfiles/` con `gzip_static on` — usa los `.gz` sin comprimir on-the-fly
3. Cache `immutable` con 365 días es seguro porque los filenames cambian en cada deploy

---

## Redis

Redis es siempre activo y optimiza tres aspectos clave:

| Aspecto | Sin Redis | Con Redis |
|---|---|---|
| Cache | `LocMemCache` por worker (no compartido) | Cache compartido entre los 3 workers Gunicorn |
| Sesiones | Escrituras a PostgreSQL en cada request | Cache en memoria, sin tocar la DB |
| django-axes | Escrituras a DB en cada intento fallido | Operaciones en cache, más rápido bajo ataques |

---

## Variables de entorno

| Variable | Requerida | Descripción |
|---|---|---|
| `PROJECT_NAME` | Sí | Nombre usado en contenedores y nginx |
| `DOMAIN` | Sí | Dominio principal de Django |
| `SECRET_KEY` | Sí | Clave secreta de Django |
| `DEBUG` | No | `False` en prod (default) |
| `ALLOWED_HOSTS` | Sí | Dominios permitidos (CSV) |
| `CSRF_TRUSTED_ORIGINS` | Sí | Orígenes confiables CSRF (CSV) |
| `ADMIN_URL` | No | URL del admin (default: `admin/`) |
| `APP_PORT` | No | Puerto Django (default: `8000`) |
| `POSTGRES_MODE` | No | `container` o `host` (default: `container`) |
| `POSTGRES_DB` | Sí | Nombre de la base de datos |
| `POSTGRES_USER` | Sí | Usuario PostgreSQL |
| `POSTGRES_PASSWORD` | Sí | Contraseña PostgreSQL |
| `POSTGRES_HOST` | No | Host PostgreSQL (default: `postgres`) |
| `POSTGRES_PORT` | No | Puerto PostgreSQL (default: `5432`) |
| `REDIS_URL` | No | URL de Redis (default: `redis://redis:6379/0`) |
| `N8N_DOMAIN` | No | Subdominio de n8n (activa el servicio) |
| `N8N_PORT` | No | Puerto externo n8n (default: `8001`) |
| `N8N_ENCRYPTION_KEY` | Si n8n | Clave de cifrado de n8n (**no cambiar**) |
| `N8N_MCP_ENABLED` | No | `true` para habilitar n8n-MCP |
| `N8N_MCP_PORT` | No | Puerto externo MCP (default: `8002`) |
| `N8N_API_KEY` | Si MCP | API key de n8n para el servidor MCP |
| `N8N_MCP_AUTH_TOKEN` | Si MCP | Token de autenticación del MCP |
| `N8N_URL` | No | URL de n8n para llamadas desde Django |
| `EMAIL_HOST` | No | SMTP host (activa email backend) |

---

## Comandos

| Comando | Descripción |
|---|---|
| `make setup` | Wizard interactivo — genera `.env` |
| `make install` | Instala dependencias Python y Tailwind |
| `make dev-up` | Levanta servicios de desarrollo (Docker) |
| `make dev-down` | Detiene servicios de desarrollo |
| `make dev-logs` | Logs de servicios de desarrollo |
| `make dev-check` | Verifica estado del entorno de desarrollo |
| `make dev` | migrate + tailwind start + runserver |
| `make migrate` | Ejecuta migraciones |
| `make migrations` | Crea migraciones |
| `make superuser` | Crea superusuario |
| `make shell` | Django shell |
| `make collect` | collectstatic |
| `make db-shell` | Abre psql (PostgreSQL) o indica sqlite3 |
| `make db-reset` | Elimina SQLite y vuelve a migrar |
| `make n8n-export` | Exporta workflows de n8n dev a `n8n/workflows/` |
| `make n8n-update` | Actualiza n8n en producción (rebuild + restart) |
| `make check-ports` | Verifica disponibilidad de puertos |
| `make nginx` | Instala config nginx (**solo primera vez**) |
| `make deploy` | Despliega en VPS (git pull + verifica puertos + rebuild) |
| `make logs` | Logs de Django en producción |
| `make down` | Detiene contenedores de producción |

---

## Estructura

```
├── core/                    # Configuración Django (settings, urls, wsgi)
├── home/                    # App principal (index, sitemaps)
├── templates/               # Templates globales (base, 404, 500, robots.txt)
├── theme/                   # App Tailwind (static_src/ con npm build)
├── static/                  # Assets estáticos (img, css)
├── staticfiles/             # collectstatic output (generado)
├── media/                   # Uploads de usuarios (generado)
├── n8n/workflows/           # Workflows n8n versionados en git
├── volumes/                 # Datos persistentes de contenedores (gitignored)
│   └── n8n/                 # Datos de n8n (workflows, credenciales)
├── db/                      # Datos PostgreSQL en producción (gitignored)
├── docker/
│   ├── n8n.Dockerfile       # n8n con Python 3.12 (para Code nodes)
│   ├── n8n-export.sh        # Script de exportación de workflows
│   └── init-db.sql          # Crea la base de datos n8n al iniciar postgres
├── Dockerfile               # Multi-stage: Node (CSS build) → Python (prod)
├── docker-compose.yml       # Producción: postgres* + redis + django + n8n* + mcp*
├── docker-compose.dev.yml   # Desarrollo: postgres* + redis + n8n* + mcp*
├── entrypoint.sh            # Espera PG + Redis, collectstatic, migrate, gunicorn
├── nginx.conf               # Template nginx Django
├── nginx-n8n.conf           # Template nginx n8n (con marcador {{MCP_BLOCK}})
├── nginx-n8n-mcp.conf       # Location block para n8n-MCP (SSE)
├── nginx-deploy.sh          # Genera e instala config nginx (solo primera vez)
├── deploy.sh                # Script de despliegue VPS
├── setup.sh                 # Wizard de configuración inicial
├── check-ports.sh           # Verifica disponibilidad de puertos
├── Makefile
├── .env.example             # Plantilla de variables de entorno
└── requirements.txt         # Dependencias Python de producción
```

`*` servicio opcional (Docker Compose profile)

---

## Notas de seguridad

- **Admin URL aleatorio** — generado por `setup.sh`, desindexado via `robots.txt`
- **Brute-force protection** — django-axes bloquea tras 5 intentos fallidos, 1h cooldown, usando Redis (no DB) como backend en producción
- **CSP headers** — política estricta vía django-csp, relajada en DEBUG para browser-reload
- **HSTS** — habilitado en producción (1 año, incluye subdominios)
- **Static files** — hashes en filenames + cache `immutable` 365 días, seguros porque cambian en cada deploy

---

## Checklist de personalización

- [ ] Cambiar favicon: reemplazar `static/img/favicon.svg`
- [ ] Cambiar imagen OG: reemplazar `static/img/og-default.jpg`
- [ ] Actualizar email de admin en `core/settings.py` → `ADMINS`
- [ ] Ajustar zona horaria y locale → `TIME_ZONE`, `LANGUAGE_CODE` en `settings.py`
- [ ] Personalizar tema DaisyUI en `theme/static_src/src/styles.css`
- [ ] Al agregar nuevas apps: `INSTALLED_APPS` + `@source "../../../<app>"` en `styles.css`
