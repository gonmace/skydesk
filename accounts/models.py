from django.conf import settings
from django.db import models


class Role(models.TextChoices):
    COORDINADOR = 'COORDINADOR', 'Coordinador'
    EXPERTO = 'EXPERTO', 'Experto'
    EJECUTOR = 'EJECUTOR', 'Ejecutor'
    SEGUIMIENTO = 'SEGUIMIENTO', 'Seguimiento'


# Letra RACI por rol (A=Accountable, R=Responsible, C=Consulted, I=Informed).
RACI_LETTER = {
    'COORDINADOR': 'A',
    'EJECUTOR': 'R',
    'EXPERTO': 'C',
    'SEGUIMIENTO': 'I',
}


class AllowedDomain(models.Model):
    """Dominio de correo habilitado para solicitar acceso (ej. 'empresa.com')."""
    domain = models.CharField('Dominio', max_length=255, unique=True)
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

    def save(self, *args, **kwargs):
        self.domain = self.domain.strip().lower().lstrip('@')
        super().save(*args, **kwargs)

    def __str__(self):
        return self.domain


class AllowedEmail(models.Model):
    """Correo puntual habilitado (excepción a un dominio no listado)."""
    email = models.EmailField('Correo', unique=True)
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

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email


class Profile(models.Model):
    """Datos extra del usuario — principalmente su rol en el sistema."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile',
    )
    role = models.CharField('Rol', max_length=20, choices=Role.choices, default=Role.EJECUTOR)
    created = models.DateTimeField(auto_now_add=True)

    @property
    def raci_letter(self):
        return RACI_LETTER.get(self.role, '')

    def __str__(self):
        return f'{self.user} ({self.get_role_display()})'


class NextcloudOAuthConfig(models.Model):
    """Config de login "Iniciar sesión con Nextcloud" (fila única, pk=1), editable por el
    superuser. Separada de `attachments.NextcloudConfig` a propósito: esa guarda un
    app-password de una cuenta de servicio para WebDAV (storage de adjuntos); esta guarda
    credenciales OAuth2 (client_id/secret) para autenticar usuarios finales — son
    credenciales de naturaleza y dueño distintos, aunque apunten al mismo servidor.

    Por default asume la app OAuth2 nativa de Nextcloud (Settings → Security → OAuth2:
    solo authorize+token, sin discovery/userinfo OIDC) y resuelve el email vía la API OCS.
    Si el Nextcloud tiene la app OIDC completa, `userinfo_url` (y opcionalmente las otras
    dos) se pueden sobreescribir sin tocar código.
    """
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
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def resolved_authorize_url(self):
        return self.authorize_url or f'{self.base_url.rstrip("/")}/index.php/apps/oauth2/authorize'

    def resolved_token_url(self):
        return self.token_url or f'{self.base_url.rstrip("/")}/index.php/apps/oauth2/api/v1/token'

    def resolved_userinfo_url(self):
        return self.userinfo_url or f'{self.base_url.rstrip("/")}/ocs/v2.php/cloud/user?format=json'


class RolePermission(models.Model):
    """Matriz rol × capacidad, editable por el superuser en el tablero de toggles."""
    role = models.CharField(max_length=20, choices=Role.choices)
    capability = models.CharField(max_length=50)
    enabled = models.BooleanField(default=False)

    class Meta:
        unique_together = ('role', 'capability')
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
