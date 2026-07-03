"""Contrato de los backends de almacenamiento de adjuntos."""
from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """Almacén de blobs identificados por una `key` (ruta relativa legible).

    Implementaciones: Nextcloud (WebDAV) hoy; S3/CDN/otro servidor a futuro. La app
    `tickets` no conoce esta capa: pasa por `attachments.services`.
    """

    name = 'base'

    @abstractmethod
    def save(self, key, fileobj, content_type):
        """Guarda `fileobj` bajo `key`. Devuelve la key final realmente usada."""

    @abstractmethod
    def open(self, key):
        """Devuelve (iterador_de_bytes, content_type) para hacer streaming."""

    @abstractmethod
    def delete(self, key):
        """Elimina el blob. No debe fallar si ya no existe."""

    @abstractmethod
    def exists(self, key):
        """True si existe un blob en `key`."""
