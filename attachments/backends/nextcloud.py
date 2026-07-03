"""Backend de almacenamiento sobre Nextcloud vía WebDAV (basic-auth con app-password).

La `key` es una ruta legible bajo `root` (ej. ``SKY-12/foto.jpg``), de modo que los
archivos también se pueden navegar/abrir directamente desde la web/cliente de Nextcloud.
"""
from urllib.parse import quote

import requests

from .base import StorageBackend


class NextcloudError(Exception):
    pass


class NextcloudBackend(StorageBackend):
    name = 'nextcloud'

    def __init__(self, *, base_url, user, token, root='', name='nextcloud', timeout=30):
        if not base_url or not user or not token:
            raise NextcloudError(
                'Nextcloud no está configurado: definí NEXTCLOUD_URL, NEXTCLOUD_USER y NEXTCLOUD_TOKEN.'
            )
        self.name = name
        self.base_url = base_url.rstrip('/')
        self.user = user
        self.token = token
        self.root = root.strip('/')
        self.timeout = timeout

    # ── helpers ────────────────────────────────────────────────────────────
    @property
    def _auth(self):
        return (self.user, self.token)

    def _quote(self, path):
        return quote(path, safe='/')

    def _url(self, key):
        parts = [p for p in (self.root, key.strip('/')) if p]
        return f"{self.base_url}/{self._quote('/'.join(parts))}"

    def _ensure_parents(self, key):
        """Crea (MKCOL) cada colección padre de `key`, de forma idempotente."""
        segments = [p for p in (self.root, *key.strip('/').split('/')[:-1]) if p]
        path = ''
        for seg in segments:
            path = f'{path}/{seg}' if path else seg
            url = f"{self.base_url}/{self._quote(path)}"
            resp = requests.request('MKCOL', url, auth=self._auth, timeout=self.timeout)
            # 201 creado, 405 ya existe → ambos OK.
            if resp.status_code not in (201, 405, 301):
                raise NextcloudError(f'MKCOL {path} → {resp.status_code}')

    # ── API ────────────────────────────────────────────────────────────────
    def save(self, key, fileobj, content_type):
        self._ensure_parents(key)
        headers = {'Content-Type': content_type or 'application/octet-stream'}
        resp = requests.put(
            self._url(key), data=fileobj, headers=headers,
            auth=self._auth, timeout=self.timeout,
        )
        if resp.status_code not in (200, 201, 204):
            raise NextcloudError(f'PUT {key} → {resp.status_code}')
        return key

    def open(self, key):
        resp = requests.get(self._url(key), auth=self._auth, stream=True, timeout=self.timeout)
        if resp.status_code != 200:
            raise NextcloudError(f'GET {key} → {resp.status_code}')
        content_type = resp.headers.get('Content-Type', 'application/octet-stream')
        return resp.iter_content(chunk_size=8192), content_type

    def delete(self, key):
        resp = requests.delete(self._url(key), auth=self._auth, timeout=self.timeout)
        if resp.status_code not in (200, 204, 404):
            raise NextcloudError(f'DELETE {key} → {resp.status_code}')

    def exists(self, key):
        resp = requests.request('PROPFIND', self._url(key), auth=self._auth,
                                headers={'Depth': '0'}, timeout=self.timeout)
        return resp.status_code in (200, 207)
