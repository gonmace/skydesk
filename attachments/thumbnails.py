"""Generación de thumbnails (imágenes con Pillow, PDF con PyMuPDF).

Los aciertos se persisten en disco (`private_attachments/thumbnails/`), indexados por
sha256: así se generan una sola vez para siempre y sobreviven a reinicios/flush de Redis
(a diferencia del cache-only-en-Redis anterior, que forzaba volver a descargar el blob
completo de Nextcloud y re-renderizarlo cada vez que expiraba el TTL). Redis se usa solo
como cache NEGATIVO (fallos/oversize) con TTL corto, para no reintentar en cada request un
archivo corrupto.
"""
import io
import os

from django.conf import settings
from django.core.cache import cache

from . import services

FAIL_CACHE_TTL = 60 * 10  # 10 min — solo para no reintentar fallos en cada request

# Tope para generar thumbnail: el blob completo se descarga del backend y se renderiza
# EN el request (síncrono) — con adjuntos de hasta 20 MB, una grilla de PDFs recién
# subidos podía consumir los 3 workers de gunicorn en descargas+renders simultáneos.
MAX_SOURCE_SIZE = 8 * 1024 * 1024  # 8 MB

THUMB_ROOT = os.path.join(settings.BASE_DIR, 'private_attachments', 'thumbnails')


def _thumb_path(sha256, size):
    # Shard por los primeros 2 hex para no amontonar todo en una sola carpeta.
    return os.path.join(THUMB_ROOT, sha256[:2], f'{sha256}_{size}.png')


def get_thumbnail(attachment, size=256):
    """PNG (bytes) del thumbnail del adjunto, o None si no aplica / falla."""
    if not attachment.has_thumbnail:
        return None
    if (attachment.size or 0) > MAX_SOURCE_SIZE:
        return None   # el template cae al ícono genérico, igual que sin thumbnail

    sha = attachment.sha256
    path = _thumb_path(sha, size) if sha else None

    if path and os.path.isfile(path):
        with open(path, 'rb') as f:
            return f.read()

    fail_key = f'attthumb:fail:{sha or attachment.pk}:{size}'
    if cache.get(fail_key):
        return None

    try:
        stream, _ = services.open_blob(attachment)
        data = b''.join(stream)
        png = _image_thumb(data, size) if attachment.is_image else _pdf_thumb(data, size)
    except Exception:
        png = None

    if not png:
        cache.set(fail_key, 1, FAIL_CACHE_TTL)
        return None

    if path:
        _write_atomic(path, png)
    return png


def _write_atomic(path, data):
    """Escribe vía archivo temporal + rename: evita que dos workers generando el mismo
    thumbnail en paralelo dejen un archivo truncado (rename es atómico en el mismo fs)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


def _image_thumb(data, size):
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im = im.convert('RGBA')
    im.thumbnail((size, size))
    out = io.BytesIO()
    im.save(out, 'PNG')
    return out.getvalue()


def _pdf_thumb(data, size):
    import fitz  # PyMuPDF
    doc = fitz.open(stream=data, filetype='pdf')
    try:
        page = doc.load_page(0)
        rect = page.rect
        zoom = size / max(rect.width, rect.height, 1)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        return pix.tobytes('png')
    finally:
        doc.close()
