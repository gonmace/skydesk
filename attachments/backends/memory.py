"""Backend de almacenamiento en memoria — para dev/tests sin Nextcloud (no persiste, sin red)."""
from .base import StorageBackend


class MemoryBackend(StorageBackend):
    _store = {}  # {name: {key: (bytes, content_type)}}

    def __init__(self, *, name='memory'):
        self.name = name
        MemoryBackend._store.setdefault(name, {})

    @property
    def _bucket(self):
        return MemoryBackend._store.setdefault(self.name, {})

    @classmethod
    def clear(cls):
        cls._store = {}

    def save(self, key, fileobj, content_type):
        if hasattr(fileobj, 'read'):
            data = fileobj.read()
        elif isinstance(fileobj, (bytes, bytearray)):
            data = bytes(fileobj)
        else:
            data = b''.join(fileobj)  # iterador de chunks (p.ej. migración)
        self._bucket[key] = (data, content_type)
        return key

    def open(self, key):
        if key not in self._bucket:
            raise FileNotFoundError(key)
        data, content_type = self._bucket[key]
        return iter([data]), content_type

    def delete(self, key):
        self._bucket.pop(key, None)

    def exists(self, key):
        return key in self._bucket
