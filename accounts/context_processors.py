"""Inyecta flags de navegación según el rol/capacidades del usuario."""
from django.contrib.auth import get_user_model

from .models import RACI_LETTER, Role
from .permissions import get_user_role, has_capability


def nav_flags(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    role = get_user_role(user)
    # request.real_user lo cuelga DevImpersonationMiddleware cuando el superuser real
    # está impersonando a `user`. Si no existe, `user` ES el real.
    real_user = getattr(request, 'real_user', user)
    impersonate_available = real_user.is_superuser
    return {
        'nav_can_seguimiento': has_capability(user, 'chat.view_all'),
        'nav_can_dashboard': has_capability(user, 'dashboard.view'),
        'nav_can_create': has_capability(user, 'tickets.create'),
        'nav_can_labels': has_capability(user, 'tickets.edit_any'),
        'nav_can_projects': has_capability(user, 'projects.manage'),
        # Cuentas: superuser (has_capability lo bypasea) o coordinador con accounts.manage.
        'nav_can_accounts': has_capability(user, 'accounts.manage'),
        'nav_is_superuser': user.is_superuser,
        'nav_role': role or '',
        'nav_role_label': dict(Role.choices).get(role, ''),
        'nav_raci': RACI_LETTER.get(role, ''),
        # Impersonar usuario real (dev) — ver accounts/middleware.py y accounts/views.dev_impersonate.
        'dev_impersonate_available': impersonate_available,
        'dev_impersonate_active': user if real_user is not user else None,
        'dev_impersonate_candidates': (
            get_user_model().objects.filter(is_active=True).exclude(pk=real_user.pk)
            .select_related('profile').order_by('email')
            if impersonate_available else None
        ),
    }
