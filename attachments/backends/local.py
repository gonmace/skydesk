"""Backend de almacenamiento en disco local — para demos/dev sin Nextcloud.

A diferencia de `memory.MemoryBackend` (se pierde al reiniciar el proceso), este backend
persiste los archivos en disco, así que sobreviven entre `manage.py seed_demo` y `runserver`
(procesos distintos). No pensado para producción (sin dedupe atómico entre workers).

Deliberadamente FUERA de MEDIA_ROOT: nginx sirve MEDIA_ROOT/media/ sin autenticación
(ver nginx.conf), y `attachment_serve` es la única vía que debe entregar estos archivos
tras chequear permisos — si vivieran bajo MEDIA_ROOT, cualquiera con la key adivinable
(son legibles, ej. "SKY-12/foto.jpg") podría descargarlos directo por /media/.
"""
import os

from django.conf import settings

from .base import StorageBackend


class LocalDiskBackend(StorageBackend):

    def __init__(self, *, root='demo_attachments', name='local'):
        self.name = name
        self.base_path = os.path.join(settings.BASE_DIR, 'private_attachments', root)

    def _path(self, key):
        path = os.path.normpath(os.path.join(self.base_path, key))
        if not (path + os.sep).startswith(os.path.normpath(self.base_path) + os.sep):
            raise ValueError(f'Ruta inválida: {key}')
        return path

    def save(self, key, fileobj, content_type):
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if hasattr(fileobj, 'read'):
            data = fileobj.read()
        elif isinstance(fileobj, (bytes, bytearray)):
            data = bytes(fileobj)
        else:
            data = b''.join(fileobj)
        with open(path, 'wb') as f:
            f.write(data)
        return key

    def open(self, key):
        path = self._path(key)
        if not os.path.isfile(path):
            raise FileNotFoundError(key)
        with open(path, 'rb') as f:
            data = f.read()
        return iter([data]), None

    def delete(self, key):
        try:
            os.remove(self._path(key))
        except FileNotFoundError:
            pass

    def exists(self, key):
        return os.path.isfile(self._path(key))
