"""Generación de thumbnails (imágenes con Pillow, PDF con PyMuPDF), cacheados en Redis."""
import io

from django.core.cache import cache

from . import services

CACHE_TTL = 60 * 60 * 24  # 1 día

# Tope para generar thumbnail: el blob completo se descarga del backend y se renderiza
# EN el request (síncrono) — con adjuntos de hasta 20 MB, una grilla de PDFs recién
# subidos podía consumir los 3 workers de gunicorn en descargas+renders simultáneos.
MAX_SOURCE_SIZE = 8 * 1024 * 1024  # 8 MB


def get_thumbnail(attachment, size=256):
    """PNG (bytes) del thumbnail del adjunto, o None si no aplica / falla."""
    if not attachment.has_thumbnail:
        return None
    if (attachment.size or 0) > MAX_SOURCE_SIZE:
        return None   # el template cae al ícono genérico, igual que sin thumbnail
    ckey = f'attthumb:{attachment.pk}:{size}'
    cached = cache.get(ckey)
    if cached is not None:
        return cached or None
    try:
        stream, _ = services.open_blob(attachment)
        data = b''.join(stream)
        png = _image_thumb(data, size) if attachment.is_image else _pdf_thumb(data, size)
    except Exception:
        png = None
    # Cachear también los fallos (b'') para no reintentar en cada request.
    cache.set(ckey, png or b'', CACHE_TTL)
    return png


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
