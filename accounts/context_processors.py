"""Inyecta flags de navegación (rol/capacidades) y la marca de la empresa actual."""
from django.contrib.auth import get_user_model
from django.urls import reverse

from .models import RACI_LETTER, Role
from .permissions import get_user_role, has_capability
from .tenancy import company_path, members_q, user_companies

DEFAULT_BRAND_NAME = 'SkyDesk'


def company_branding(request):
    """Marca de la empresa del request (`request.company`, lo cuelga CompanyMiddleware).
    Corre también para anónimos: la pantalla de login de /<slug>/acceso/login/ ya muestra
    el nombre, logo y colores del cliente. Sin empresa (login genérico, panel del
    superuser, 500) cae a la marca por defecto del producto."""
    company = getattr(request, 'company', None)
    if company is None:
        return {
            'current_company': None,
            'brand_name': DEFAULT_BRAND_NAME,
            'brand_logo_light_url': None,
            'brand_logo_dark_url': None,
            'brand_favicon_url': None,
            'theme_css_url': None,
        }
    v = company.theme_version()

    def logo(variant, has_file):
        # Servido por accounts.views.branding_logo (nginx no expone /media/). Cache-bust
        # con `updated` para que un reemplazo se vea sin esperar el TTL del navegador.
        return f"{reverse('accounts:branding_logo', args=[variant])}?v={v}" if has_file else None

    return {
        'current_company': company,
        'brand_name': company.brand_name or DEFAULT_BRAND_NAME,
        'brand_logo_light_url': logo('light', company.logo_light),
        'brand_logo_dark_url': logo('dark', company.logo_dark or company.logo_light),
        'brand_favicon_url': logo('favicon', company.favicon),
        'theme_css_url': (
            f"{reverse('accounts:company_theme_css')}?v={v}" if company.has_custom_colors else None
        ),
    }


def nav_flags(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    role = get_user_role(user)
    company = getattr(request, 'company', None)
    # request.real_user lo cuelga DevImpersonationMiddleware cuando el superuser real
    # está impersonando a `user`. Si no existe, `user` ES el real.
    real_user = getattr(request, 'real_user', user)
    impersonate_available = real_user.is_superuser
    candidates = None
    if impersonate_available:
        candidates = get_user_model().objects.filter(is_active=True).exclude(pk=real_user.pk)
        if company is not None:
            candidates = candidates.filter(members_q(company)).distinct()
        candidates = candidates.select_related('profile').order_by('email')
    # Selector "Cambiar de empresa": solo para quien opera en más de una (principal +
    # adicionales). La URL define la empresa activa, así que cada opción es un link al
    # tablero de esa empresa con SU prefijo (company_path, no {% url %}).
    nav_companies = None
    if not user.is_superuser:
        companies = user_companies(user)
        if len(companies) > 1:
            nav_companies = [
                {'company': c, 'url': company_path(c, 'tickets:board'),
                 'active': company is not None and c.pk == company.pk}
                for c in companies
            ]
    return {
        'nav_companies': nav_companies,
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
        # Impersonar usuario real — ver accounts/middleware.py y accounts/views.dev_impersonate.
        'dev_impersonate_available': impersonate_available,
        'dev_impersonate_active': user if real_user is not user else None,
        'dev_impersonate_candidates': candidates,
    }
