import os
from decouple import config, Csv

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(PROJECT_DIR)

_SECRET_KEY_DEFAULT = 'django-insecure-default-only-for-dev-run-make-setup'
SECRET_KEY = config('SECRET_KEY', default=_SECRET_KEY_DEFAULT)

DEBUG = config('DEBUG', default=False, cast=bool)

# Validar solo cuando existe .env (entorno configurado) pero SECRET_KEY no fue definido.
# Sin .env = instalación inicial, el default es aceptable.
if SECRET_KEY == _SECRET_KEY_DEFAULT and os.path.exists(os.path.join(BASE_DIR, '.env')):
    raise ValueError("SECRET_KEY no está en .env. Ejecuta 'make setup' para generarlo.")

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='', cast=Csv())

ADMIN_URL = config('ADMIN_URL', default='admin/')

# Application definition

INSTALLED_APPS = [
    # 'daphne' primero: requisito de Django Channels para que `runserver` sirva ASGI/WS.
    'daphne',
    'channels',

    'accounts',
    'tickets',
    'attachments',
    'notifications',
    'axes',

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'csp.middleware.CSPMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'axes.middleware.AxesMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]

INSTALLED_APPS += ['tailwind', 'theme']
TAILWIND_APP_NAME = 'theme'

if DEBUG:
    INSTALLED_APPS += ['django_browser_reload']
    MIDDLEWARE += [
        'django_browser_reload.middleware.BrowserReloadMiddleware',
        'accounts.middleware.DevImpersonationMiddleware',
    ]
    INTERNAL_IPS = ['127.0.0.1', '::1']
    import sys
    if sys.platform == 'win32':
        NPM_BIN_PATH = r'C:\Program Files\nodejs\npm.cmd'

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'accounts.backends.EmailBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# ── Login / sesión ────────────────────────────────────────────────────────────
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'tickets:board'
LOGOUT_REDIRECT_URL = 'accounts:login'

# Sesión persistente ("seguir logueado"); el form de login la acorta si no marcan "Recordarme".
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = config('SESSION_COOKIE_AGE', default=60 * 60 * 24 * 30, cast=int)  # 30 días

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'accounts.context_processors.nav_flags',
                'notifications.context_processors.notifications',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'
ASGI_APPLICATION = 'core.asgi.application'

# Database: SQLite por defecto en dev, PostgreSQL si se define POSTGRES_DB
if config('POSTGRES_DB', default=''):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('POSTGRES_DB'),
            'USER': config('POSTGRES_USER'),
            'PASSWORD': config('POSTGRES_PASSWORD'),
            'HOST': config('POSTGRES_HOST', default='postgres'),
            'PORT': config('POSTGRES_PORT', default='5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es'
TIME_ZONE = 'America/La_Paz'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
WHITENOISE_MANIFEST_STRICT = not DEBUG  # True en prod: rechaza archivos sin entrada en manifest

STORAGES = {
    'staticfiles': {
        # CompressedManifestStaticFilesStorage: hashes en filenames (cache-busting seguro)
        # + archivos .gz pre-generados que nginx sirve con gzip_static on
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Email: consola en dev, SMTP en prod si se configura EMAIL_HOST
if config('EMAIL_HOST', default=''):
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = config('EMAIL_HOST')
    EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
    EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
    EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
    EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
    DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='noreply@example.com')
    # Sin timeout, un SMTP caído/lento cuelga el request indefinidamente — con 3 workers
    # de gunicorn, 3 comentarios simultáneos congelaban la app entera.
    EMAIL_TIMEOUT = config('EMAIL_TIMEOUT', default=10, cast=int)
else:
    if not DEBUG and os.path.exists(os.path.join(BASE_DIR, '.env')):
        # En producción sin EMAIL_HOST, las activaciones de cuenta y resets de password
        # "se enviarían" a los logs del contenedor — nadie los recibiría. Mismo criterio
        # de fail-fast que SECRET_KEY (solo si hay .env: sin .env es instalación inicial).
        raise ValueError('EMAIL_HOST no está en .env y DEBUG=False. Configurá el SMTP para producción.')
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='SkyDesk Tickets <noreply@example.com>')

# ── Adjuntos (almacenamiento intercambiable) ─────────────────────────────────
# Hoy TODOS los adjuntos van a Nextcloud; la abstracción permite migrar a S3/CDN a futuro.
ATTACHMENT_DEFAULT_BACKEND = config('ATTACHMENT_DEFAULT_BACKEND', default='nextcloud')
ATTACHMENT_MAX_SIZE = config('ATTACHMENT_MAX_SIZE', default=20 * 1024 * 1024, cast=int)  # 20 MB
ATTACHMENT_ALLOWED_TYPES = (
    'image/', 'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'text/plain', 'text/csv',
)
ATTACHMENT_BACKENDS = {
    'nextcloud': {
        'BACKEND': 'attachments.backends.nextcloud.NextcloudBackend',
        'OPTIONS': {
            # URL base WebDAV, ej. https://nube.dominio/remote.php/dav/files/<usuario>
            'base_url': config('NEXTCLOUD_URL', default=''),
            'user': config('NEXTCLOUD_USER', default=''),
            'token': config('NEXTCLOUD_TOKEN', default=''),  # app-password de Nextcloud
            'root': config('NEXTCLOUD_ROOT', default='SkyDesk-Tickets'),
        },
    },
    # Disco local bajo media/ — usado por `manage.py seed_demo` para adjuntos de prueba
    # sin depender de Nextcloud. No es el backend por defecto (ATTACHMENT_DEFAULT_BACKEND).
    'local': {
        'BACKEND': 'attachments.backends.local.LocalDiskBackend',
        'OPTIONS': {},
    },
}

# ── Seguridad ──────────────────────────────────────────────────────────────────
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# SkyDesk se embebe como iframe dentro de Nextcloud (NEXTCLOUD_EMBED_ORIGIN) además de
# servirse en su propio dominio — no hay X_FRAME_OPTIONS ni XFrameOptionsMiddleware, el
# framing lo gobierna exclusivamente la CSP (frame-ancestors, más abajo), que es más
# granular. SameSite=None es requisito para que sessionid/csrftoken viajen dentro del
# iframe cross-site; solo en producción porque exige Secure (HTTPS).
SESSION_COOKIE_SAMESITE = 'None' if not DEBUG else 'Lax'
CSRF_COOKIE_SAMESITE = 'None' if not DEBUG else 'Lax'

# URL de la página de Nextcloud (External Sites) a la que se vuelve tras el login SSO
# iniciado desde dentro del iframe — ver accounts.views.nextcloud_login/_callback.
NEXTCLOUD_RETURN_URL = config('NEXTCLOUD_RETURN_URL', default='')

# ── Redis (cache, sesiones) ───────────────────────────────────────────────────
# En dev sin .env, se conecta a localhost:6379 (Docker Desktop expone el puerto al host).
# En producción, .env siempre define REDIS_URL=redis://redis:6379/0 (nombre del servicio Docker).
REDIS_URL = config('REDIS_URL', default='redis://localhost:6379/0')

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': REDIS_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
    }
}

# cached_db: la DB es la fuente de verdad y Redis solo acelera lecturas. Con el
# backend 'cache' puro, una caída de Redis daba 500 en TODA la app (cada request
# toca la sesión) y cada deploy/restart de Redis deslogueaba a todos los usuarios.
SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'
SESSION_CACHE_ALIAS = 'default'

# ── Channels (tiempo real, WebSockets) ─────────────────────────────────────────
# Reusa el mismo Redis de cache/sesiones (prefijos de clave propios, sin colisión).
# En tests se pisa por InMemoryChannelLayer (ver tickets/tests_realtime.py).
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            # redis-py 8.0 puso socket_timeout=5s por defecto, igual al BZPOPMIN
            # bloqueante (brpop_timeout=5) de channels_redis -> el read del socket
            # expiraba en cada conexión inactiva y tiraba el WebSocket. Se le da
            # margen al socket para que nunca compita con el timeout del bloqueo.
            'hosts': [{'address': REDIS_URL, 'socket_timeout': 30}],
        },
    }
}

# ── django-axes (protección brute force) ──────────────────────────────────────
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # hora
AXES_LOCKOUT_PARAMETERS = ['ip_address', 'username']
# Detrás de nginx, REMOTE_ADDR es siempre 127.0.0.1 — sin esto el lockout por IP no
# distingue clientes (ver core/client_ip.py).
AXES_CLIENT_IP_CALLABLE = 'core.client_ip.client_ip'

if DEBUG:
    # En desarrollo se usa el handler de base de datos para no depender de Redis.
    # Permite correr 'python manage.py runserver' sin contenedores activos.
    AXES_HANDLER = 'axes.handlers.database.AxesDatabaseHandler'
else:
    # En producción Redis siempre está disponible — más rápido bajo ataques.
    AXES_HANDLER = 'axes.handlers.cache.AxesCacheHandler'
    AXES_CACHE = 'default'

# ── Content Security Policy (django-csp 4.x) ─────────────────────────────────
# API nueva: un único dict CONTENT_SECURITY_POLICY. Sin inline JS/CSS (todo externo).
from csp.constants import SELF  # noqa: E402

if DEBUG:
    _WS_SOURCES = ['ws://localhost:*', 'ws://127.0.0.1:*']
else:
    # wss:// del/de los host(s) real(es) — sin esto el handshake del WebSocket (tiempo
    # real, ver tickets/consumers.py) queda bloqueado por CSP en producción.
    _WS_SOURCES = [f'wss://{h}' for h in ALLOWED_HOSTS if h and h not in ('localhost', '127.0.0.1')]

# frame-ancestors reemplaza a X_FRAME_OPTIONS (eliminado más arriba): permite embeber
# SkyDesk como iframe dentro de Nextcloud (NEXTCLOUD_EMBED_ORIGIN, ej. sky.redlinegs.com)
# sin abrir el framing a cualquier origen. Sin la variable en .env, solo 'self'.
_NC_EMBED_ORIGIN = config('NEXTCLOUD_EMBED_ORIGIN', default='')
_FRAME_ANCESTORS = [SELF] + ([_NC_EMBED_ORIGIN] if _NC_EMBED_ORIGIN else [])

CONTENT_SECURITY_POLICY = {
    'DIRECTIVES': {
        'default-src': [SELF],
        'script-src': [SELF],
        'style-src': [SELF],
        'img-src': [SELF, 'data:', 'blob:'],
        'font-src': [SELF],
        'connect-src': [SELF] + _WS_SOURCES,
        'frame-ancestors': _FRAME_ANCESTORS,
        'form-action': [SELF],
    },
}

# ── Integración n8n (opcional) ───────────────────────────────────────────────
N8N_URL = config('N8N_URL', default='')
N8N_API_KEY = config('N8N_API_KEY', default='')
N8N_WEBHOOK_URL = config('N8N_WEBHOOK_URL', default='')

# ── Admins y logging ──────────────────────────────────────────────────────────
# ADMIN_EMAIL en .env — sin él no se manda mail de errores (antes iba hardcodeado a
# admin@example.com, o sea a nadie). El handler de consola garantiza que los errores
# de producción queden SIEMPRE en `docker logs`, haya o no email configurado.
_admin_email = config('ADMIN_EMAIL', default='')
ADMINS = [('Admin', _admin_email)] if _admin_email else []
MANAGERS = ADMINS

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'require_debug_false': {'()': 'django.utils.log.RequireDebugFalse'}
    },
    'handlers': {
        'mail_admins': {
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler',
        },
        'console': {
            'level': 'ERROR',
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django.request': {
            'handlers': ['mail_admins', 'console'],
            'level': 'ERROR',
            'propagate': True,
        },
    },
}
