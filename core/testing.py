"""Helpers de tests para el modo multi-empresa (ver accounts/tenancy.py).

Toda la app vive bajo `/<slug>/`. Para que los tests existentes sigan usando
`reverse('tickets:board')` (que devuelve `/`, sin prefijo — el middleware restaura el
script prefix al terminar cada request), `TenantClient` antepone `/embol` a cada path
de app antes de mandarlo. `embol` es la empresa inicial que crea la data migration
`accounts/0021_seed_default_company` en TODA base (también la de tests).
"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from accounts.models import Company, Profile, Role

DEFAULT_SLUG = 'embol'
# Rutas del servidor que nunca llevan prefijo de empresa (ver accounts.tenancy).
ROOT_PREFIXES = ('/admin/', '/empresas/', '/static/', '/media/', '/ws/', '/robots.txt', '/sitemap.xml')


def default_company():
    return Company.objects.get(slug=DEFAULT_SLUG)


def prefix_path(path, slug=DEFAULT_SLUG):
    """'/mis-tickets/' → '/embol/mis-tickets/'. Deja intactas las rutas ya prefijadas,
    las del servidor (admin, /empresas/, estáticos) y las URLs absolutas."""
    path = str(path)
    if not path.startswith('/') or path.startswith(f'/{slug}/') or path == f'/{slug}':
        return path
    if path.startswith(ROOT_PREFIXES):
        return path
    return f'/{slug}{path}'


p = prefix_path


def make_user(email, role=Role.EJECUTOR, company=None, password='x', is_active=True,
              extra_companies=(), **extra):
    """Usuario operativo con Profile (rol + empresa principal; `embol` por defecto) y,
    opcionalmente, empresas adicionales donde también opera (ver accounts.tenancy)."""
    User = get_user_model()
    u = User.objects.create_user(email, email, password, is_active=is_active, **extra)
    profile, _ = Profile.objects.update_or_create(
        user=u, defaults={'role': role, 'company': company or default_company()},
    )
    if extra_companies:
        profile.extra_companies.set(extra_companies)
    return u


class TenantClient(Client):
    """Client que navega dentro de la empresa `slug` (prefija los paths) y que, al
    hacer force_login de un usuario sin empresa, lo cuelga de la empresa por defecto —
    un usuario operativo sin empresa es un 403 en todo el sitio (por diseño)."""
    slug = DEFAULT_SLUG

    def generic(self, method, path, *args, **kwargs):
        return super().generic(method, prefix_path(path, self.slug), *args, **kwargs)

    def force_login(self, user, backend=None):
        if not user.is_superuser:
            profile, _ = Profile.objects.get_or_create(user=user)
            if profile.company_id is None:
                profile.company = Company.objects.get(slug=self.slug)
                profile.save(update_fields=['company'])
        super().force_login(user, backend)


class TenantTestCase(TestCase):
    client_class = TenantClient

    @property
    def company(self):
        return default_company()
