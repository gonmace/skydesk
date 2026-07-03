# Probar por rol en desarrollo

SkyDesk tiene 4 roles (`accounts/models.py:Role`): **Coordinador**, **Experto**, **Ejecutor**,
**Seguimiento**. Qué puede hacer cada uno está centralizado en `accounts/permissions.py`
(`CAPABILITIES` + `DEFAULT_ROLE_CAPS`), editable en caliente por el superuser en
`/acceso/roles/`. Esta guía cubre cómo probar esos permisos en desarrollo.

## Setup rápido

```bash
make dev              # migrate + tailwind watch + runserver
python manage.py seed_demo   # (en otra terminal) crea usuarios + tickets de demo
```

`seed_demo` crea 12 cuentas cubriendo los 4 roles, todas con password **`Demo1234!`**:

| Email | Rol |
|---|---|
| `coordinador@empresa.com` / `coordinador2@empresa.com` | Coordinador |
| `experto@empresa.com` / `experto2@empresa.com` / `experto3@empresa.com` | Experto |
| `ejecutor@empresa.com` … `ejecutor5@empresa.com` | Ejecutor |
| `seguimiento@empresa.com` / `seguimiento2@empresa.com` | Seguimiento |

Más 17 tickets cubriendo toda combinación relevante de estado/asignación/adjuntos. Entrá en
`/acceso/login/` con cualquiera de esas cuentas.

**Gotchas:**
- Re-correr `seed_demo` **no** resetea la password de una cuenta que ya existía (solo la fija
  al crearla). Si una cuenta quedó con otra contraseña, cambiala desde `/acceso/admin/`
  (superuser) o borrala y volvé a correr el comando.
- django-axes bloquea IP+usuario después de 5 intentos fallidos por 1 hora
  (`AXES_FAILURE_LIMIT` en `core/settings.py`). Si te trabás: `python manage.py axes_reset`.
- **Un superuser nunca sirve para probar restricciones de rol** — `has_capability()` hace
  `if user.is_superuser: return True` antes de mirar el rol. Para probar lo que ve/puede hacer
  un rol, usá una cuenta de `seed_demo` (o el impersonador dev, ver más abajo).

## Sesiones paralelas (varios roles a la vez)

Para ver, por ejemplo, el tablero de un Ejecutor y el de un Coordinador lado a lado sin que
compartan cookies de sesión:

- **Perfiles de Chrome/Edge**: creá un perfil por rol (ícono de cuenta → Agregar perfil). Cada
  perfil tiene su propio storage de cookies — quedan todos logueados a la vez, cómodo para
  sesiones largas de prueba.
- **Ventanas de incógnito**: más rápido para chequeos puntuales, pero *todas* las ventanas de
  incógnito de una misma instancia del navegador comparten sesión entre sí — para 2+ roles
  simultáneos necesitás perfiles, o incógnito en un navegador + normal en otro.
- **Navegadores distintos** (Firefox + Chrome, o dos Firefox con `-P`): la opción más simple
  cuando ya los tenés instalados.

Con 2-3 sesiones así podés reproducir flujos cruzados de verdad: Coordinador asigna → Ejecutor
mueve su subticket → Coordinador aprueba, todo viendo el resultado en tiempo real en cada
ventana (recargando).

## Impersonador dev (chequeos rápidos sin abrir otra sesión)

Solo visible en `DEBUG=True` y solo para superuser: un botón "Impersonar" en el header (arriba
a la derecha) lista los usuarios reales (con su rol) y deja elegir uno para navegar la app
*siendo* esa persona, sin cerrar tu sesión de superuser. Aparece una franja amarilla
recordando a quién estás impersonando, con un botón "Salir" para volver a tu vista real.

Qué hace por debajo (`accounts/middleware.py:DevImpersonationMiddleware`): mientras esté
activo, reemplaza `request.user` por el usuario elegido — no es un rol simulado, es
literalmente ese usuario. Por eso ves **sus datos reales**: sus tickets asignados, sus
subtickets, sus notificaciones, sus "fantasma" de compañeros, y `has_capability()`/
`get_user_role()` responden con su Profile real (incluida la restricción de superuser, si
llegaras a impersonar a otro superuser). No existe fuera de `DEBUG=True`: en producción la
vista devuelve 404 sin importar quién la llame.

Con esto ya no hace falta abrir una sesión aparte para chequeos rápidos: impersoná
`ejecutor@empresa.com` (de `seed_demo`) desde tu propia ventana de superuser y vas a ver
exactamente su tablero, sus notificaciones y sus permisos.

**Cuándo igual conviene una sesión real aparte** (ver sección anterior): para probar flujos
donde varias personas interactúan a la vez (Coordinador aprueba mientras el Ejecutor mira su
notificación en vivo) — el impersonador es una sola sesión que salta de identidad, no sirve
para ver dos pantallas simultáneas.

## Matriz de capacidades → casos a probar

Derivada de `DEFAULT_ROLE_CAPS` en `accounts/permissions.py:31-38` (los valores reales pueden
diferir si el superuser los tocó en `/acceso/roles/` — esto es la línea de base sembrada por la
migración).

| Capacidad | Coordinador | Experto | Ejecutor | Seguimiento | Caso concreto a probar |
|---|:---:|:---:|:---:|:---:|---|
| `tickets.view_all` | ✅ | ✅ | ❌ | ✅ | Tablero: ¿ve todos los tickets o solo los propios/asignados? |
| `tickets.create` | ✅ | ❌ | ❌ | ❌ | Botón "+ Ticket" visible; `POST /nuevo/` da 403 si no. |
| `tickets.edit_any` | ✅† | ❌ | ❌ | ❌ | Editar un ticket ajeno; moderar comentarios de otros. |
| `tickets.assign` | ✅ | ❌ | ❌ | ❌ | Formulario de ticket: ¿aparecen los selectores de ejecutores/expertos? |
| `tickets.close` | ✅ | ❌ | ❌ | ❌ | Aprobar conclusión, Suspender/Reactivar — ambos exclusivos del Coordinador. |
| `tickets.move` | ❌* | ❌* | ✅ | ❌* | Drag & drop del propio subticket entre Por hacer/En progreso/Esperando. |
| `chat.view_all` | ❌ | ✅ | ❌ | ✅ | Página de Seguimiento (todas las conversaciones). |
| `chat.write` | ❌ | ✅ | ✅ | ❌ | Comentar en un ticket donde participa. |
| `dashboard.view` | ❌ | ✅ | ❌ | ✅ | `/dashboard/`: 200 vs 403. |
| `projects.manage` | ❌ | ❌ | ❌ | ❌ | Solo Coordinador vía `tickets.edit_any`… revisar `/proyectos/`. |
| `roles.assign` | ✅ | ❌ | ❌ | ❌ | Nadie más debería poder tocar `/acceso/roles/` (además, esa vista es superuser-only igual). |

\* El Coordinador/Experto/Seguimiento no tienen `tickets.move` porque su tablero muestra
tickets completos (agregados), no subtickets — no arrastran. Solo el Ejecutor arrastra su
propio subticket.

† `tickets.edit_any` (y por lo tanto quién puede editar un ticket, `_can_edit_ticket` en
`tickets/views.py`) es una capacidad del rol Coordinador **global al sistema**, no una
membresía por proyecto: no existe hoy un "coordinador del proyecto X" ligado a un `Project`
puntual — cualquier Coordinador edita tickets de cualquier proyecto.

**Casos adicionales fuera de la matriz de capacidades** (gates específicos, no genéricos):

- Ticket suspendido por el Coordinador: card atenuada (`is-locked`) y el Ejecutor no puede
  moverla (`assignment_move` responde 400) hasta que el Coordinador reactive.
- Concluir un subticket exige texto (descripción o link) — probar con el campo vacío.
- Archivar (Concluido/Suspendido) lo puede hacer cualquier editor; **desarchivar es solo
  superuser** — probar con una cuenta normal (debería dar 403) y con superuser (debería andar).
- Config de Nextcloud (`/acceso/nextcloud/`) es superuser-only.
- Tiempo por estado: mover un subticket Por hacer → En progreso → Esperando → En progreso y
  confirmar en el detalle que el tiempo en Esperando no se sumó a ningún contador.

## Automatizado (complemento, no reemplazo)

`tickets/tests.py`, `accounts/tests.py` y `attachments/tests.py` ya cubren buena parte de esta
matriz con el helper `make_user(email, role)` + `client.force_login(...)`. Correr
`python manage.py test` antes de dar por probado cualquier cambio de permisos — es más rápido
que repetir la matriz a mano, aunque no reemplaza un paseo visual real por la UI.
