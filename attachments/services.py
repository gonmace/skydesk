"""Capa de servicio de adjuntos: validación + persistencia, agnóstica del backend."""
import hashlib
import logging
import os
import re

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from .backends import get_backend
from .models import Attachment

logger = logging.getLogger(__name__)

# SVG es XML: si se sirve inline (navegación directa, no <img>) el navegador ejecuta
# cualquier <script> embebido con las cookies de sesión del origen — se rechaza sin
# excepción, sin importar qué liste ATTACHMENT_ALLOWED_TYPES (ver validate_upload).
_BLOCKED_EXACT = {'image/svg+xml'}

# Tipos que attachment_serve puede devolver como `inline` con seguridad (rasters sin
# contenido activo). Todo lo demás se descarga como adjunto (`Content-Disposition:
# attachment`) aunque esté en ATTACHMENT_ALLOWED_TYPES — ver tickets/views.py:attachment_serve.
SAFE_INLINE_TYPES = {
    'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/bmp', 'application/pdf',
}


class DuplicateAttachment(Exception):
    """El archivo (mismo sha256) ya está adjunto al mismo objeto."""
    def __init__(self, existing):
        self.existing = existing
        super().__init__('Ese adjunto ya estaba.')


def _hash_upload(uploaded_file):
    h = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        h.update(chunk)
    uploaded_file.seek(0)
    return h.hexdigest()

DEFAULT_MAX_SIZE = 20 * 1024 * 1024  # 20 MB
DEFAULT_ALLOWED = ('image/', 'application/pdf')

_SAFE = re.compile(r'[^A-Za-z0-9._() \-]+')


def _max_size():
    return getattr(settings, 'ATTACHMENT_MAX_SIZE', DEFAULT_MAX_SIZE)


def _allowed_prefixes():
    return tuple(getattr(settings, 'ATTACHMENT_ALLOWED_TYPES', DEFAULT_ALLOWED))


def validate_upload(uploaded_file):
    """Valida tipo (image/* o PDF), tamaño y —para imágenes— que los bytes reales sean
    una imagen decodificable (no solo que el cliente declare ese Content-Type: un
    archivo cualquiera renombrado con content_type='image/png' no pasa). Lanza
    ValidationError si no cumple."""
    mime = (uploaded_file.content_type or '').lower()
    if mime in _BLOCKED_EXACT:
        raise ValidationError('No se permiten archivos SVG.')
    if not mime.startswith(_allowed_prefixes()):
        raise ValidationError('Solo se permiten imágenes o archivos PDF.')
    if uploaded_file.size and uploaded_file.size > _max_size():
        mb = _max_size() // (1024 * 1024)
        raise ValidationError(f'El archivo supera el máximo de {mb} MB.')
    if mime.startswith('image/'):
        _verify_image(uploaded_file)


def _verify_image(uploaded_file):
    from PIL import Image, UnidentifiedImageError
    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError('El archivo no es una imagen válida.') from exc
    finally:
        uploaded_file.seek(0)


def _sanitize(filename):
    name = os.path.basename(filename or 'archivo')
    name = _SAFE.sub('_', name).strip() or 'archivo'
    # Evitar nombres que sean solo puntos ('.', '..') → escaparían un nivel de carpeta.
    if not name.strip('.'):
        name = 'archivo'
    return name[:255]


def _folder_for(content_object):
    """Carpeta legible para el objeto dueño (ej. 'SKY-12'), sin importar tickets."""
    if hasattr(content_object, 'key'):
        return str(content_object.key)
    ticket = getattr(content_object, 'ticket', None)
    if ticket is not None and hasattr(ticket, 'key'):
        return str(ticket.key)
    return f'{content_object._meta.model_name}-{content_object.pk}'


def _unique_key(backend, folder, filename):
    """Evita sobrescribir: si la key existe, agrega sufijo ' (2)', ' (3)'…"""
    base, ext = os.path.splitext(filename)
    candidate = f'{folder}/{filename}'
    i = 2
    while backend.exists(candidate):
        candidate = f'{folder}/{base} ({i}){ext}'
        i += 1
    return candidate


def store(uploaded_file, *, owner, content_object, backend_name=None):
    """Valida y sube el archivo al backend por defecto, creando el Attachment.

    Dedup: si un archivo con el mismo sha256 ya está adjunto al mismo objeto,
    no lo re-sube y lanza DuplicateAttachment(existing).
    """
    validate_upload(uploaded_file)
    digest = _hash_upload(uploaded_file)
    ct = ContentType.objects.get_for_model(content_object)
    existing = Attachment.objects.filter(
        content_type=ct, object_id=content_object.pk, sha256=digest,
    ).first()
    if existing:
        raise DuplicateAttachment(existing)

    backend = get_backend(backend_name)
    filename = _sanitize(uploaded_file.name)
    key = _unique_key(backend, _folder_for(content_object), filename)
    stored_key = backend.save(key, uploaded_file, uploaded_file.content_type)
    return Attachment.objects.create(
        content_object=content_object,
        filename=filename,
        mime_type=(uploaded_file.content_type or 'application/octet-stream')[:100],
        size=uploaded_file.size or 0,
        sha256=digest,
        storage_backend=backend.name,
        storage_key=stored_key,
        uploaded_by=owner,
    )


def open_blob(attachment):
    """Devuelve (iterador_de_bytes, content_type) para hacer streaming."""
    backend = get_backend(attachment.storage_backend)
    stream, content_type = backend.open(attachment.storage_key)
    return stream, content_type or attachment.mime_type


def delete_blob(attachment):
    """Borra el archivo del backend (no borra la fila — eso lo hace el signal post_delete
    de Attachment, ver attachments/signals.py).

    Los backends ya toleran "no existe" internamente (404 en NextcloudBackend.delete,
    FileNotFoundError en LocalDiskBackend.delete) sin lanzar. Cualquier otra excepción
    (backend caído, red, credenciales) se deja propagar a propósito: como esto corre en
    un receiver de post_delete dentro de la transacción de delete(), la excepción hace
    rollback de todo el borrado — mejor abortarlo que dejar el archivo huérfano en el
    storage con la fila ya borrada."""
    backend = get_backend(attachment.storage_backend)
    try:
        backend.delete(attachment.storage_key)
    except Exception:
        logger.exception(
            'No se pudo borrar el blob %s/%s', attachment.storage_backend, attachment.storage_key,
        )
        raise
