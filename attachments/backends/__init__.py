"""Factory de backends de almacenamiento, configurable por settings y por empresa."""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string


def get_backend(name=None, company=None):
    """Devuelve una instancia del backend `name` (o el por defecto) para `company`.

    Multi-empresa: cada cliente conecta su propio Nextcloud (`attachments.NextcloudConfig`
    por empresa pisa a la config de `.env`), y en el backend `local` cada empresa escribe
    bajo su propia subcarpeta (`<root>/<slug>`). Sin `company` se usa la config de entorno
    tal cual (tests, comandos globales).

    Configuración en settings::

        ATTACHMENT_DEFAULT_BACKEND = 'nextcloud'
        ATTACHMENT_BACKENDS = {
            'nextcloud': {
                'BACKEND': 'attachments.backends.nextcloud.NextcloudBackend',
                'OPTIONS': {...},
            },
        }
    """
    name = name or getattr(settings, 'ATTACHMENT_DEFAULT_BACKEND', 'nextcloud')
    backends = getattr(settings, 'ATTACHMENT_BACKENDS', {})
    try:
        cfg = backends[name]
    except KeyError:
        raise ImproperlyConfigured(f"Backend de adjuntos '{name}' no está en ATTACHMENT_BACKENDS.")
    cls = import_string(cfg['BACKEND'])
    options = dict(cfg.get('OPTIONS', {}))
    options.setdefault('name', name)
    if name == 'nextcloud':
        options.update(_nextcloud_db_overrides(company))
    elif name == 'local' and company is not None:
        options['root'] = f"{options.get('root', 'demo_attachments')}/{company.slug}"
    return cls(**options)


def _nextcloud_db_overrides(company):
    """Config de BD de la empresa (superuser, `NextcloudConfig`) pisa a la de `.env` si
    está activa."""
    if company is None:
        return {}
    from .. import models  # import perezoso: evita ciclos en el arranque de la app
    try:
        cfg = models.NextcloudConfig.objects.filter(company=company, enabled=True).first()
    except Exception:
        # Tabla no migrada todavía (ej. durante el propio makemigrations/migrate).
        return {}
    if not cfg:
        return {}
    overrides = {}
    if cfg.base_url:
        overrides['base_url'] = cfg.base_url
    if cfg.user:
        overrides['user'] = cfg.user
    if cfg.token:
        overrides['token'] = cfg.token
    if cfg.root:
        overrides['root'] = cfg.root
    return overrides
