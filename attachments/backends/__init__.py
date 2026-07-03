"""Factory de backends de almacenamiento, configurable por settings."""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string


def get_backend(name=None):
    """Devuelve una instancia del backend `name` (o el por defecto).

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
        options.update(_nextcloud_db_overrides())
    return cls(**options)


def _nextcloud_db_overrides():
    """Config de BD (superuser, `NextcloudConfig`) pisa a la de `.env` si está activa."""
    from .. import models  # import perezoso: evita ciclos en el arranque de la app
    try:
        cfg = models.NextcloudConfig.objects.filter(pk=1, enabled=True).first()
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
