# Integración con Nextcloud

SkyDesk se integra con Nextcloud (`sky.redlinegs.com`) de tres formas independientes:

1. **Storage de adjuntos (WebDAV)** — los archivos adjuntos de los tickets se guardan en Nextcloud.
2. **Login SSO (OAuth2)** — "Iniciar sesión con Nextcloud", sin escribir contraseña en SkyDesk.
3. **Embebido como iframe** — SkyDesk corre dentro de Nextcloud (app *External Sites*) además de en su propio dominio (`skydesk.redlinegs.com`).

Cada una se configura por separado. Las dos primeras tienen su propia tarjeta en `/acceso/nextcloud/` (solo superuser).

---

## 1. Storage de adjuntos (WebDAV)

Modelo: `attachments.NextcloudConfig` (una sola fila, editable en la UI). Si `enabled=True`, pisa a las variables de entorno.

| Campo | Valor | De dónde sale |
|---|---|---|
| URL base (WebDAV) | `https://sky.redlinegs.com/remote.php/dav/files/<usuario>` | Fija, solo cambiás `<usuario>` |
| Usuario | el username de la cuenta Nextcloud "dueña" de los adjuntos | Recomendado: una cuenta dedicada (ej. `skydesk-bot`), no una personal |
| App-password | token generado por Nextcloud | Ver pasos abajo |
| Carpeta raíz | `SkyDesk-Tickets` (default) | Nextcloud la crea sola |

**Generar el App-password**: logueado con la cuenta dedicada en Nextcloud → **Settings → Security** → sección *"Devices & sessions"* → *"Create new app password"* → copiar usuario + contraseña generada (no se vuelve a mostrar).

**Dónde cargarlo**: `https://skydesk.redlinegs.com/acceso/nextcloud/`, tarjeta de storage WebDAV. Tiene botón **"Probar conexión"** que confirma si la carpeta raíz existe o hay error de credenciales.

**Alternativa por `.env`** (sin marcar `enabled` en la UI): `NEXTCLOUD_URL`, `NEXTCLOUD_USER`, `NEXTCLOUD_TOKEN`, `NEXTCLOUD_ROOT`.

---

## 2. Login SSO (OAuth2)

Modelo: `accounts.NextcloudOAuthConfig` (una sola fila, editable en la UI). Flujo authorization-code server-side (`accounts/views.py`: `nextcloud_login` / `nextcloud_callback`), gateado por la misma allow-list del onboarding normal (`accounts.access.is_email_allowed`).

### Crear el cliente OAuth2 en Nextcloud

`Settings → Administration → Security → OAuth 2.0 clients` → agregar cliente nuevo con:
- **Redirection URI**: `https://skydesk.redlinegs.com/acceso/nextcloud/callback/`
  (ojo: el prefijo es `/acceso/`, la app `accounts` está montada ahí — `core/urls.py`)

Nextcloud entrega un **Client ID** y **Client secret**.

### Cargar la config en SkyDesk

`https://skydesk.redlinegs.com/acceso/nextcloud/`, tarjeta de login OAuth2:
- **URL base de Nextcloud**: `https://sky.redlinegs.com` (el dominio de Nextcloud, **no** el de SkyDesk)
- **Client ID** / **Client secret**: los generados arriba
- Dejar vacíos los overrides de authorize/token/userinfo (usa los defaults de la app OAuth2 nativa de Nextcloud)
- Marcar **Activo**

### Allow-list

El email que devuelve Nextcloud tiene que estar habilitado en `https://skydesk.redlinegs.com/acceso/admin/` (como **correo puntual** o por **dominio**), igual que el onboarding manual. Si no, el login falla con *"Tu cuenta de Nextcloud no está habilitada para acceder a SkyDesk."*

---

## 3. Embebido como iframe (External Sites)

### Variables de entorno (`.env` de la VPS)

```bash
NEXTCLOUD_EMBED_ORIGIN=https://sky.redlinegs.com
NEXTCLOUD_RETURN_URL=https://sky.redlinegs.com/apps/external/<id-del-external-site>
```

- **`NEXTCLOUD_EMBED_ORIGIN`**: se agrega a la CSP (`frame-ancestors`) para que el navegador permita que Nextcloud embeba a SkyDesk. Sin esto, el iframe muestra *"skydesk.redlinegs.com rechazó la conexión"* (bloqueo de framing, no un problema de red).
- **`NEXTCLOUD_RETURN_URL`**: página de Nextcloud (External Sites) a la que se vuelve al terminar el login SSO iniciado *desde dentro* del iframe (el click rompe el frame con `target="_top"`, y sin esta variable el tab termina logueado en el board standalone de SkyDesk en vez de volver a Nextcloud). Para conseguir la URL: abrí la app *External Sites* en Nextcloud y copiá la URL completa de la barra de direcciones.

Después de cambiar el `.env`, reiniciar Django: `docker compose up -d --build django` (o `make deploy`).

### Configurar el sitio en Nextcloud

App *External Sites* → agregar sitio nuevo apuntando a `https://skydesk.redlinegs.com`.

Para que SkyDesk detecte cuándo cambia el usuario logueado en Nextcloud (ver sección siguiente), la URL del sitio debe incluir el placeholder `{uid}`:
```
https://skydesk.redlinegs.com/?nc_uid={uid}
```
Verificar que Nextcloud realmente lo reemplace (DevTools → Network → ver qué URL pide el iframe realmente).

### Detección de cambio de usuario (`NextcloudUidMismatchMiddleware`)

La sesión de SkyDesk es independiente de la de Nextcloud (cookies de dominios distintos). Si alguien cierra sesión en Nextcloud y entra con otra cuenta, sin este chequeo el iframe seguiría mostrando la sesión anterior de SkyDesk.

- En cada login OAuth2, `nextcloud_callback` guarda el UID de Nextcloud en `Profile.nextcloud_uid`.
- `accounts.middleware.NextcloudUidMismatchMiddleware` compara ese valor contra el parámetro `?nc_uid=` de cada request; si no coincide, cierra la sesión de SkyDesk (vuelve a mostrar el login con el botón SSO).
- Requiere que la URL del External Site incluya `{uid}` (paso anterior).

### UI dentro del iframe

Un script (`static/js/nextcloud-embed-login.js` en el login, `static/js/embed-hide-usermenu.js` en el resto de la app) detecta `window.self !== window.top` y ajusta la interfaz:
- **Login**: oculta el formulario local (email/contraseña), deja solo el botón SSO con `target="_top"` (necesario porque los navegadores bloquean que un iframe navegue `window.top` sin un click real del usuario).
- **Resto de la app**: oculta el logo y el dropdown de usuario (perfil, cerrar sesión — no aplica dentro de Nextcloud); deja visibles el avatar y el badge de rol.

Fuera del iframe (standalone en `skydesk.redlinegs.com`), nada de esto se oculta.

### Por qué no es 100% automático

No hay forma de loguear automáticamente sin al menos un click: los navegadores exigen un gesto de usuario real para que un iframe navegue el frame superior hacia otro dominio (protección anti-clickjacking desde 2019), y un chequeo silencioso vía iframe oculto no funciona porque Nextcloud se protege a sí mismo con `X-Frame-Options: SAMEORIGIN` (no se deja embeber ni oculto). El único camino hacia "cero clicks" sería pasar el usuario firmado (HMAC) vía el `{uid}` de External Sites — no implementado por ahora (mayor superficie de ataque a cambio de ahorrar un click).

---

## Checklist de troubleshooting

| Síntoma | Causa | Fix |
|---|---|---|
| `<dominio> rechazó la conexión` dentro del iframe | Falta `NEXTCLOUD_EMBED_ORIGIN` en `.env` | Agregarla y reiniciar Django |
| Click en "Iniciar sesión con Nextcloud" da 404 en el dominio de **SkyDesk** | `base_url` de `NextcloudOAuthConfig` mal cargado (apunta a SkyDesk en vez de a Nextcloud) | Corregir a `https://sky.redlinegs.com` en `/acceso/nextcloud/` |
| Tras dar "Grant access" en Nextcloud, termina logueado en el board standalone de SkyDesk (no vuelve a Nextcloud) | Falta `NEXTCLOUD_RETURN_URL` en `.env` | Agregarla (URL de la página de External Sites) y reiniciar Django |
| "Tu cuenta de Nextcloud no está habilitada para acceder a SkyDesk" | El email no está en la allow-list | Agregarlo en `/acceso/admin/` (correo puntual o dominio) |
| Cambiar de usuario en Nextcloud no cambia el usuario logueado en el SkyDesk embebido | Sesiones independientes; falta `{uid}` en la URL del External Site | Agregar `?nc_uid={uid}` a la URL del sitio en Nextcloud |
