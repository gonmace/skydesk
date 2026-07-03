from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class Attachment(models.Model):
    """Adjunto (imagen/PDF) desacoplado del almacenamiento.

    El byte-stream vive en un backend (Nextcloud hoy; S3/CDN mañana). El modelo solo
    guarda metadatos + (storage_backend, storage_key), lo que permite migrar el
    archivo a otro backend sin perder la referencia.
    """
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    filename = models.CharField('Nombre', max_length=255)
    mime_type = models.CharField('Tipo MIME', max_length=100)
    size = models.PositiveBigIntegerField('Tamaño (bytes)', default=0)
    sha256 = models.CharField('Hash', max_length=64, blank=True, default='', db_index=True)

    storage_backend = models.CharField('Backend', max_length=50)
    storage_key = models.CharField('Clave/ruta', max_length=1000)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created']
        indexes = [models.Index(fields=['content_type', 'object_id'])]

    def __str__(self):
        return self.filename

    @property
    def is_image(self):
        return self.mime_type.startswith('image/')

    @property
    def is_pdf(self):
        return self.mime_type == 'application/pdf'

    @property
    def has_thumbnail(self):
        return self.is_image or self.is_pdf

    @property
    def ext(self):
        return self.filename.rsplit('.', 1)[-1].lower() if '.' in self.filename else ''


class NextcloudConfig(models.Model):
    """Config de Nextcloud editable por el superuser (fila única, pk=1).

    Si `enabled` está activo, estos valores pisan a los de `.env`/`settings.py` en
    `attachments.backends.get_backend()`. Si no hay fila o está deshabilitada, se usa
    la config de entorno (comportamiento actual). El token nunca se re-muestra en
    pantalla una vez guardado (campo write-only en el form).
    """
    enabled = models.BooleanField('Activo', default=False)
    base_url = models.CharField(
        'URL base (WebDAV)', max_length=500, blank=True,
        help_text='Ej. https://nube.dominio/remote.php/dav/files/<usuario>',
    )
    user = models.CharField('Usuario', max_length=255, blank=True)
    token = models.CharField('App-password', max_length=500, blank=True)
    root = models.CharField('Carpeta raíz', max_length=255, blank=True, default='SkyDesk-Tickets')
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuración de Nextcloud'
        verbose_name_plural = 'Configuración de Nextcloud'

    def __str__(self):
        return f'Nextcloud ({"activo" if self.enabled else "inactivo"})'

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
