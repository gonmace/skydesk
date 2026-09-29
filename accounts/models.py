import os

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models


class Role(models.TextChoices):
    COORDINADOR = 'COORDINADOR', 'Coordinador'
    EXPERTO = 'EXPERTO', 'Experto'
    EJECUTOR = 'EJECUTOR', 'Ejecutor'
    SEGUIMIENTO = 'SEGUIMIENTO', 'Seguimiento'
    # Espía solo-lectura: ve TODO (incluida la columna Entrada) pero no participa —
    # no es asignable, no escribe, no recibe notificaciones y no figura ante los
    # demás roles (se omite de la leyenda «?» del tablero; solo el superuser lo ve
    # en Cuentas/Roles).
    ADMINISTRADOR = 'ADMINISTRADOR', 'Administrador'


# Letra RACI por rol (A=Accountable, R=Responsible, C=Consulted, I=Informed).
# ADMINISTRADOR no tiene letra a propósito: es un observador fuera de la matriz RACI.
RACI_LETTER = {
    'COORDINADOR': 'A',
    'EJECUTOR': 'R',
    'EXPERTO': 'C',
    'SEGUIMIENTO': 'I',
}


def _validate_logo_size(value):
    max_bytes = 2 * 1024 * 1024
    if value.size > max_bytes:
        raise ValidationError('El logo no puede superar los 2 MB.')


def _validate_favicon_ext(value):
    ext = os.path.splitext(value.name)[1].lower()
    # SVG a propósito excluido: es XML ejecutable si alguien lo abre directo.
    if ext not in ('.png', '.ico'):
        raise ValidationError('El favicon debe ser PNG o ICO.')


def _logo_light_path(instance, filename):
    return f'branding/{instance.slug}/logo-light{os.path.splitext(filename)[1].lower()}'


def _logo_dark_path(instance, filename):
    return f'branding/{instance.slug}/logo-dark{os.path.splitext(filename)[1].lower()}'


def _favicon_path(instance, filename):
    return f'branding/{instance.slug}/favicon{os.path.splitext(filename)[1].lower()}'


# Solo para que la migración histórica 0018_brandingconfig siga importando (referencia
# estas funciones por nombre). BrandingConfig ya no existe: la marca vive en Company.
def _branding_light_path(instance, filename):  # pragma: no cover — legado
    return f'branding/logo-light{os.path.splitext(filename)[1].lower()}'


def _branding_dark_path(instance, filename):  # pragma: no cover — legado
    return f'branding/logo-dark{os.path.splitext(filename)[1].lower()}'


slug_validator = RegexValidator(
    r'^[a-z][a-z0-9-]{1,30}$',
    'Solo minúsculas, números y guiones (2 a 31 caracteres), empezando con una letra.',
)
ticket_prefix_validator = RegexValidator(r'^[A-Z]{2,6}$', 'Entre 2 y 6 letras mayúsculas, ej. EMBOL.')
hex_color_validator = RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Color hexadecimal de 6 dígitos, ej. #E4002B.')

# Primer segmento de ruta que NUNCA puede ser slug de empresa: son rutas propias del
# servidor (ver accounts.tenancy.CompanyMiddleware) o del urlconf raíz sin prefijo.
RESERVED_SLUGS = frozenset({
    'static', 'media', 'ws', 'empresas', 'admin', 'robots.txt', 'sitemap.xml', '__reload__',
})

COMPANY_CACHE_KEY = 'company:slug:{}'


class Company(models.Model):
    """Empresa cliente (tenant). Todo dato operativo cuelga de una empresa y las
    empresas no se ven entre sí. Se identifica en la URL por el prefijo `/<slug>/`
    (ver accounts.tenancy). Solo el superuser (global, sin empresa) las crea."""
    name = models.CharField('Nombre', max_length=120)
    slug = models.SlugField(
        'Identificador en la URL', max_length=31, unique=True, validators=[slug_validator],
        help_text='Prefijo de todas las rutas de la empresa, ej. "embol" → /embol/. '
                  'Cambiarlo invalida los links ya enviados por correo.',
    )
    is_active = models.BooleanField(
        'Activa', default=True,
        help_text='Desactivada: nadie de la empresa puede entrar (sus datos se conservan).',
    )
    ticket_prefix = models.CharField(
        'Prefijo de tickets', max_length=6, unique=True, validators=[ticket_prefix_validator],
        help_text='Ej. EMBOL → EMBOL-0001. Cambiarlo no renumera: el correlativo sigue.',
    )
    ticket_seq = models.PositiveIntegerField('Último correlativo', default=0)

    # ── Marca ──
    brand_name = models.CharField(
        'Nombre de marca', max_length=60, default='Kanban',
        help_text='Título de la pestaña, pantalla de login y firma de los correos.',
    )
    logo_light = models.ImageField(
        'Logo (tema claro)', upload_to=_logo_light_path, blank=True,
        validators=[_validate_logo_size],
        help_text='PNG/JPG/WEBP, máx. 2 MB. Vacío = logo por defecto.',
    )
    logo_dark = models.ImageField(
        'Logo (tema oscuro)', upload_to=_logo_dark_path, blank=True,
        validators=[_validate_logo_size], help_text='Vacío = se usa el logo del tema claro.',
    )
    favicon = models.FileField(
        'Favicon', upload_to=_favicon_path, blank=True,
        validators=[_validate_logo_size, _validate_favicon_ext],
        help_text='PNG o ICO. Vacío = favicon por defecto.',
    )
    primary_color = models.CharField(
        'Color primario (claro)', max_length=7, blank=True, validators=[hex_color_validator],
        help_text='Botones, links y acentos de marca. Vacío = el del tema por defecto.',
    )
    primary_color_dark = models.CharField(
        'Color primario (oscuro)', max_length=7, blank=True, validators=[hex_color_validator],
        help_text='Vacío = se usa el color primario claro también en modo oscuro.',
    )
    accent_color = models.CharField(
        'Color de acento (claro)', max_length=7, blank=True, validators=[hex_color_validator],
    )
    accent_color_dark = models.CharField(
        'Color de acento (oscuro)', max_length=7, blank=True, validators=[hex_color_validator],
    )

    # ── Correo ──
    email_from_name = models.CharField(
        'Nombre del remitente', max_length=100, blank=True,
        help_text='Ej. "Embol Tickets". Vacío = el remitente del servidor.',
    )
    email_from = models.EmailField(
        'Correo del remitente', blank=True,
        help_text='Debe estar autorizado en el SMTP del servidor. Vacío = el del servidor.',
    )

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Empresa'
        verbose_name_plural = 'Empresas'

    def __str__(self):
        return self.name

    @classmethod
    def from_db(cls, db, field_names, values):
        obj = super().from_db(db, field_names, values)
        obj._loaded_slug = obj.__dict__.get('slug')
        return obj

    def clean(self):
        super().clean()
        slug = (self.slug or '').strip().lower()
        if slug in RESERVED_SLUGS or slug.isdigit():
            raise ValidationError({'slug': f'"{slug}" está reservado por el sistema.'})
        # Un slug que coincide con una ruta del urlconf raíz (acceso/, proyectos/, nuevo/…)
        # la taparía para todas las empresas.
        from django.urls import is_valid_path
        if slug and is_valid_path(f'/{slug}/'):
            raise ValidationError({'slug': f'"{slug}" coincide con una ruta de la aplicación.'})

    def save(self, *args, **kwargs):
        self.slug = (self.slug or '').strip().lower()
        self.ticket_prefix = (self.ticket_prefix or '').strip().upper()
        super().save(*args, **kwargs)
        update_fields = kwargs.get('update_fields')
        # El correlativo se incrementa en cada ticket nuevo: no vale la pena tirar el cache
        # por eso (nadie lee ticket_seq del objeto cacheado — ver Ticket._next_code).
        if update_fields is None or set(update_fields) != {'ticket_seq'}:
            self.invalidate_cache()

    def delete(self, *args, **kwargs):
        self.invalidate_cache()
        return super().delete(*args, **kwargs)

    def invalidate_cache(self):
        keys = {COMPANY_CACHE_KEY.format(self.slug)}
        old = getattr(self, '_loaded_slug', None)
        if old:
            keys.add(COMPANY_CACHE_KEY.format(old))
        try:
            cache.delete_many(list(keys))
        except Exception:  # Redis caído: el TTL corto (5 min) termina de limpiar
            pass
        self._loaded_slug = self.slug

    @property
    def has_custom_colors(self):
        return bool(self.primary_color or self.accent_color)

    def theme_version(self):
        """Cache-bust para logos/CSS por empresa: cambia en cada guardado."""
        return int(self.updated.timestamp()) if self.updated else 0


class AllowedDomain(models.Model):
    """Dominio de correo habilitado para solicitar acceso (ej. 'empresa.com')."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='allowed_domains')
    domain = models.CharField('Dominio', max_length=255)
    is_active = models.BooleanField('Activo', default=True)
    default_role = models.CharField(
        'Rol por defecto', max_length=20, choices=Role.choices, blank=True,
        help_text='Rol asignado a los usuarios de este dominio (Ejecutor si se deja vacío).',
    )
    note = models.CharField('Nota', max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['domain']
        verbose_name = 'Dominio permitido'
        verbose_name_plural = 'Dominios permitidos'
        constraints = [
            models.UniqueConstraint(fields=['company', 'domain'], name='accounts_alloweddomain_company_domain_uniq'),
        ]

    def save(self, *args, **kwargs):
        self.domain = self.domain.strip().lower().lstrip('@')
        super().save(*args, **kwargs)

    def __str__(self):
        return self.domain


class AllowedEmail(models.Model):
    """Correo puntual habilitado (excepción a un dominio no listado)."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='allowed_emails')
    email = models.EmailField('Correo')
    is_active = models.BooleanField('Activo', default=True)
    default_role = models.CharField(
        'Rol por defecto', max_length=20, choices=Role.choices, blank=True,
    )
    note = models.CharField('Nota', max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['email']
        verbose_name = 'Correo permitido'
        verbose_name_plural = 'Correos permitidos'
        constraints = [
            models.UniqueConstraint(fields=['company', 'email'], name='accounts_allowedemail_company_email_uniq'),
        ]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email


class BlockedEmail(models.Model):
    """Correo puntual NEGADO en la empresa aunque su dominio esté permitido: no puede
    solicitar acceso, ni entrar por SSO Nextcloud, ni ser invitado. Gana sobre
    AllowedDomain y AllowedEmail (ver access.is_email_allowed). No toca cuentas ya
    activas: para eso está «desactivar» en Cuentas registradas."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='blocked_emails')
    email = models.EmailField('Correo')
    note = models.CharField('Nota', max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['email']
        verbose_name = 'Correo bloqueado'
        verbose_name_plural = 'Correos bloqueados'
        constraints = [
            models.UniqueConstraint(fields=['company', 'email'], name='accounts_blockedemail_company_email_uniq'),
        ]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email


class Profile(models.Model):
    """Datos extra del usuario — su empresa y su rol en el sistema."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile',
    )
    # Null solo para el superuser global (administra todas las empresas). Cualquier
    # usuario operativo tiene UNA empresa principal (a donde cae al entrar sin prefijo)
    # y, esporádicamente, empresas adicionales donde también opera con el MISMO rol.
    # Para saber si puede entrar a /<slug>/ usar accounts.tenancy.is_member / members_q,
    # nunca comparar `company` a mano.
    company = models.ForeignKey(
        Company, null=True, blank=True, on_delete=models.CASCADE, related_name='profiles',
        verbose_name='Empresa principal',
    )
    extra_companies = models.ManyToManyField(
        Company, blank=True, related_name='extra_member_profiles',
        verbose_name='Empresas adicionales',
        help_text='Empresas donde el usuario también opera, además de su principal. Mismo rol.',
    )
    role = models.CharField('Rol', max_length=20, choices=Role.choices, default=Role.EJECUTOR)
    created = models.DateTimeField(auto_now_add=True)
    nextcloud_uid = models.CharField(
        'UID de Nextcloud', max_length=255, blank=True,
        help_text='Se completa solo al loguearse vía Nextcloud OAuth2 — usado para '
                   'detectar que la sesión embebida quedó de otro usuario de Nextcloud.',
    )

    @property
    def raci_letter(self):
        return RACI_LETTER.get(self.role, '')

    def __str__(self):
        return f'{self.user} ({self.get_role_display()})'


class NextcloudOAuthConfig(models.Model):
    """Config de login "Iniciar sesión con Nextcloud" (una fila por empresa), editable por
    el superuser. Separada de `attachments.NextcloudConfig` a propósito: esa guarda un
    app-password de una cuenta de servicio para WebDAV (storage de adjuntos); esta guarda
    credenciales OAuth2 (client_id/secret) para autenticar usuarios finales — son
    credenciales de naturaleza y dueño distintos, aunque apunten al mismo servidor.

    Por default asume la app OAuth2 nativa de Nextcloud (Settings → Security → OAuth2:
    solo authorize+token, sin discovery/userinfo OIDC) y resuelve el email vía la API OCS.
    Si el Nextcloud tiene la app OIDC completa, `userinfo_url` (y opcionalmente las otras
    dos) se pueden sobreescribir sin tocar código.
    """
    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name='nextcloud_oauth')
    enabled = models.BooleanField('Activo', default=False)
    base_url = models.CharField(
        'URL base de Nextcloud', max_length=500, blank=True,
        help_text='Ej. https://nube.dominio (sin /remote.php/...).',
    )
    client_id = models.CharField('Client ID', max_length=255, blank=True)
    client_secret = models.CharField('Client secret', max_length=500, blank=True)
    authorize_url = models.CharField(
        'URL de autorización (override)', max_length=500, blank=True,
        help_text='Vacío = {base_url}/index.php/apps/oauth2/authorize',
    )
    token_url = models.CharField(
        'URL de token (override)', max_length=500, blank=True,
        help_text='Vacío = {base_url}/index.php/apps/oauth2/api/v1/token',
    )
    userinfo_url = models.CharField(
        'URL de userinfo (override)', max_length=500, blank=True,
        help_text='Vacío = {base_url}/ocs/v2.php/cloud/user (API OCS)',
    )
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuración de login Nextcloud'
        verbose_name_plural = 'Configuración de login Nextcloud'

    def __str__(self):
        return f'Login Nextcloud ({"activo" if self.enabled else "inactivo"})'

    @classmethod
    def for_company(cls, company):
        obj, _ = cls.objects.get_or_create(company=company)
        return obj

    def resolved_authorize_url(self):
        return self.authorize_url or f'{self.base_url.rstrip("/")}/index.php/apps/oauth2/authorize'

    def resolved_token_url(self):
        return self.token_url or f'{self.base_url.rstrip("/")}/index.php/apps/oauth2/api/v1/token'

    def resolved_userinfo_url(self):
        return self.userinfo_url or f'{self.base_url.rstrip("/")}/ocs/v2.php/cloud/user?format=json'


class EmailConfig(models.Model):
    """Config de correo saliente (fila única, pk=1), editable por el superuser.

    Dos cosas distintas conviven acá a propósito (una sola pestaña "Correo"):
    - SMTP: si `enabled` y hay `host`, pisa la configuración del .env (mismo patrón
      que `attachments.NextcloudConfig` con el storage). Con `enabled=False` se sigue
      usando el backend del settings.
    - Toggles por evento: qué sucesos del ticket mandan email además de la
      notificación in-app. `notify_comment` arranca apagado: un chat activo genera
      un correo por mensaje a cada participante (decisión 2026-07).
    """
    enabled = models.BooleanField(
        'Usar esta configuración SMTP', default=False,
        help_text='Apagado: se usa la configuración de correo del servidor (.env).',
    )
    host = models.CharField('Servidor SMTP', max_length=255, blank=True)
    port = models.PositiveIntegerField('Puerto', default=587)
    use_tls = models.BooleanField('Usar TLS', default=True)
    username = models.CharField('Usuario', max_length=255, blank=True)
    password = models.CharField('Contraseña', max_length=500, blank=True)
    from_email = models.CharField(
        'Remitente', max_length=255, blank=True,
        help_text='Ej. Kanban Tickets <noreply@dominio>. Vacío = el del servidor.',
    )
    notify_assignment = models.BooleanField(
        'Enviar correo al asignar un ticket', default=True)
    notify_comment = models.BooleanField(
        'Enviar correo por cada mensaje de seguimiento', default=False,
        help_text='Los participantes siempre reciben la notificación in-app (campanita).',
    )
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuración de correo'
        verbose_name_plural = 'Configuración de correo'

    def __str__(self):
        return f'Correo ({"SMTP propio" if self.enabled else "settings"})'

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class RolePermission(models.Model):
    """Matriz rol × capacidad POR EMPRESA, editable por el superuser en el tablero de
    toggles. Al crear una empresa se copia la matriz de otra (o los defaults de código)
    — ver accounts.services.create_company."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='role_permissions')
    role = models.CharField(max_length=20, choices=Role.choices)
    capability = models.CharField(max_length=50)
    enabled = models.BooleanField(default=False)

    class Meta:
        unique_together = ('company', 'role', 'capability')
        ordering = ['role', 'capability']
        verbose_name = 'Permiso de rol'
        verbose_name_plural = 'Permisos de roles'

    def __str__(self):
        return f'{self.role}:{self.capability}={self.enabled}'


class UserPermission(models.Model):
    """Override puntual de una capacidad para UN usuario — pisa el default de
    RolePermission cuando existe una fila para (user, capability). Solo se edita desde
    la ficha del usuario (accounts:user_edit), y solo para roles habilitados para
    configuración individual (ver accounts.permissions.INDIVIDUAL_OVERRIDE_ROLES)."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='permission_overrides',
    )
    capability = models.CharField(max_length=50)
    enabled = models.BooleanField(default=False)

    class Meta:
        unique_together = ('user', 'capability')
        ordering = ['user_id', 'capability']
        verbose_name = 'Permiso de usuario'
        verbose_name_plural = 'Permisos de usuario'

    def __str__(self):
        return f'{self.user_id}:{self.capability}={self.enabled}'
