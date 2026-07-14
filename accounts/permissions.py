"""Capacidades del sistema y helpers de autorización por rol.

Las capacidades NO se hardcodean en las vistas: el superuser las gestiona en el
tablero de toggles (`RolePermission`). Aquí se define el catálogo de capacidades,
los valores por defecto que siembra la data migration, y los helpers que las consultan.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied

from .models import Role, RolePermission, UserPermission

# (clave, etiqueta legible) — el tablero de toggles muestra todas estas filas.
CAPABILITIES = [
    ('tickets.view_all', 'Ver todos los tickets'),
    ('tickets.create', 'Crear tickets'),
    ('tickets.edit_any', 'Editar cualquier ticket'),
    ('tickets.assign', 'Asignar tickets'),
    ('tickets.close', 'Cerrar tickets'),
    ('tickets.move', 'Mover tickets (drag & drop)'),
    ('chat.view_all', 'Ver el chat de cualquier tarea'),
    ('chat.write', 'Escribir en el chat de seguimiento'),
    ('dashboard.view', 'Ver el dashboard de métricas'),
    ('projects.manage', 'Gestionar proyectos'),
    # 'roles.assign' se eliminó del catálogo: nunca la consultó ningún código (las vistas
    # de roles/usuarios son superuser-only vía _superuser_required) — el toggle en
    # /acceso/roles/ prometía algo sin efecto. Las filas viejas en DB se ignoran.
    ('tickets.unarchive', 'Desarchivar tickets'),
    ('tickets.view_waiting', 'Ver la columna Suspendido/Cancelado del tablero'),
    ('tickets.view_backlog', 'Ver la columna Entrada del tablero'),
    ('tickets.board_by_ticket', 'Ver el tablero por ticket completo (no por subticket propio)'),
    # Abre la página Cuentas (invitar, activar/desactivar, roles, dominios). Quien la
    # tiene sin ser superuser NO ve superusers ni nada del rol Administrador (ni las
    # páginas Roles/Nextcloud/Correo, que siguen siendo superuser-only).
    ('accounts.manage', 'Gestionar cuentas (invitar, activar, roles)'),
]

CAPABILITY_KEYS = [key for key, _ in CAPABILITIES]

# Defaults sembrados por la migración (todos editables luego por el superuser).
# `tickets.view_all` = alcance ("ve todos los tickets"); `tickets.board_by_ticket` = modo de
# tablero (cards por ticket completo, no por subticket propio) — son cosas distintas: Experto
# usa el tablero por ticket pero solo ve los suyos (no tiene view_all); Ejecutor no tiene
# ninguna de las dos (tablero por subticket, alcance propio).
DEFAULT_ROLE_CAPS = {
    Role.COORDINADOR: set(CAPABILITY_KEYS),
    Role.EXPERTO: {'chat.write', 'dashboard.view', 'tickets.board_by_ticket'},
    Role.EJECUTOR: {'tickets.move', 'chat.write'},
    Role.SEGUIMIENTO: {
        'tickets.view_all', 'chat.view_all', 'dashboard.view',
        'tickets.view_waiting', 'tickets.board_by_ticket',
    },
    # Mismos privilegios que Coordinador (ver migración 0017): la única diferencia con
    # Coordinador es que Administrador nunca aparece como asignable/participante en
    # tickets ni listado en /acceso/admin/ — eso lo garantizan filtros explícitos por
    # Role.ADMINISTRADOR en tickets/forms.py y accounts/views.py, no las capacidades.
    Role.ADMINISTRADOR: set(CAPABILITY_KEYS),
}

# Roles que además del default de su rol pueden tener overrides individuales por
# usuario (UserPermission) — se editan desde la ficha de cada cuenta (user_edit). El
# resto de los roles siempre usa el default de RolePermission, sin excepciones.
INDIVIDUAL_OVERRIDE_ROLES = {Role.COORDINADOR, Role.SEGUIMIENTO}


def get_user_role(user):
    """Rol del usuario (Ejecutor si no tiene Profile aún)."""
    if not user or not user.is_authenticated:
        return None
    profile = getattr(user, 'profile', None)
    return profile.role if profile else Role.EJECUTOR


def _load_capability_set(user):
    """Todas las capacidades habilitadas para `user` en 2 queries (overrides + matriz de
    rol), resolviendo el mismo criterio que antes hacía has_capability por-llamada
    (override individual gana sobre el default del rol)."""
    role = get_user_role(user)
    if role is None:
        return frozenset()
    overrides = dict(UserPermission.objects.filter(user=user).values_list('capability', 'enabled'))
    role_caps = set(RolePermission.objects.filter(role=role, enabled=True).values_list('capability', flat=True))
    enabled = set()
    for key in CAPABILITY_KEYS:
        if key in overrides:
            if overrides[key]:
                enabled.add(key)
        elif key in role_caps:
            enabled.add(key)
    return frozenset(enabled)


def has_capability(user, capability):
    """True si el usuario tiene la capacidad. El superuser saltea todos los checks.

    Si el usuario tiene un override individual (UserPermission) para esta capacidad,
    gana sobre el default de su rol — solo existen overrides para los roles en
    INDIVIDUAL_OVERRIDE_ROLES (ver user_edit), pero acá no hace falta repetir ese
    chequeo: si no hay fila, simplemente no hay override que aplicar.

    El resultado se memoiza en el propio objeto `user` (2 queries la primera vez que se
    llama en el request, cero las siguientes) — se llama 10+ veces por request (nav,
    tablero, detalle de ticket) y `request.user` es la misma instancia durante todo el
    request, así que el cache no sobrevive entre requests."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if '_capability_set' not in user.__dict__:
        user.__dict__['_capability_set'] = _load_capability_set(user)
    return capability in user.__dict__['_capability_set']


def users_with_capability(capability):
    """Usuarios activos que tienen la capacidad habilitada — para notificar a "quien
    puede aprobar", etc. Replica la lógica de has_capability (override individual gana
    sobre el default del rol) como queryset. Excluye a los superusers puros a propósito:
    su bypass es administrativo, no significa que quieran recibir cada notificación
    operativa (si un superuser además coordina, su Profile.role ya lo incluye)."""
    from django.contrib.auth import get_user_model
    from django.db.models import Q

    User = get_user_model()
    roles = RolePermission.objects.filter(
        capability=capability, enabled=True).values_list('role', flat=True)
    override_on = UserPermission.objects.filter(
        capability=capability, enabled=True).values_list('user_id', flat=True)
    override_off = UserPermission.objects.filter(
        capability=capability, enabled=False).values_list('user_id', flat=True)
    return User.objects.filter(is_active=True).filter(
        Q(pk__in=override_on) | (Q(profile__role__in=roles) & ~Q(pk__in=override_off))
    ).distinct()


def roles_with_capability(capability):
    """Roles (valores de `Role`) que tienen esta capacidad habilitada por defecto —
    política general del rol vía `RolePermission`, sin mirar overrides individuales de
    `UserPermission` (esos son la excepción puntual de una cuenta, no la regla del rol).
    Para leyendas/ayuda que describen "qué ve cada rol" en general, no lo que ve un
    usuario particular ahora mismo (eso es `has_capability`)."""
    return set(RolePermission.objects.filter(
        capability=capability, enabled=True).values_list('role', flat=True))


def require_capability(capability):
    """Decorador para vistas: 403 si el usuario no tiene la capacidad."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not has_capability(request.user, capability):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator
