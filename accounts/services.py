"""Operaciones de alto nivel sobre empresas (tenants)."""
from django.db import transaction

from .models import Company, NextcloudOAuthConfig, RolePermission
from .permissions import CAPABILITY_KEYS, DEFAULT_ROLE_CAPS


def copy_role_matrix(company, template=None):
    """Siembra la matriz rol × capacidad de `company`: copia la de `template` (otra
    empresa, con los ajustes que el superuser ya le hizo) o, sin plantilla, los defaults
    de código. Idempotente: no pisa filas que ya existan."""
    if template is not None:
        rows = template.role_permissions.values_list('role', 'capability', 'enabled')
    else:
        rows = [
            (role, cap, cap in caps)
            for role, caps in DEFAULT_ROLE_CAPS.items()
            for cap in CAPABILITY_KEYS
        ]
    RolePermission.objects.bulk_create(
        [RolePermission(company=company, role=r, capability=c, enabled=e) for r, c, e in rows],
        ignore_conflicts=True,
    )


def ensure_company_configs(company):
    """Filas de configuración (vacías) que cada empresa debe tener."""
    from attachments.models import NextcloudConfig  # evita ciclo accounts ↔ attachments
    NextcloudOAuthConfig.objects.get_or_create(company=company)
    NextcloudConfig.objects.get_or_create(company=company)


class MembershipError(ValueError):
    """Alta/baja de membresía adicional rechazada; el mensaje es apto para mostrar."""


def add_extra_membership(user, company):
    """Suma a `user` (cuenta operativa existente) como miembro ADICIONAL de `company`:
    podrá entrar a /<slug>/ con su mismo rol. Idempotente. Solo lo hace el superuser
    (/empresas/). Ver accounts.tenancy.is_member."""
    profile = getattr(user, 'profile', None)
    if user.is_superuser:
        raise MembershipError('Un superuser ya entra a todas las empresas.')
    if profile is None or profile.company_id is None:
        raise MembershipError('La cuenta no tiene empresa principal; invitala primero desde Cuentas.')
    if profile.company_id == company.pk:
        raise MembershipError(f'«{company.name}» ya es la empresa principal de esta cuenta.')
    profile.extra_companies.add(company)
    user.__dict__.pop('_company_ids', None)


def remove_extra_membership(user, company):
    """Quita la membresía adicional. Se bloquea si el usuario tiene tickets asignados en
    esa empresa (quedarían Assignments cruzando empresas — mismo criterio que
    ProfileAdmin al mover la principal)."""
    from tickets.models import Assignment  # evita ciclo accounts ↔ tickets
    profile = getattr(user, 'profile', None)
    if profile is None:
        return
    if Assignment.objects.filter(user=user, ticket__company=company).exists():
        raise MembershipError(
            f'{user.email} tiene tickets asignados en «{company.name}»; reasignalos antes de quitarle el acceso.'
        )
    profile.extra_companies.remove(company)
    user.__dict__.pop('_company_ids', None)


@transaction.atomic
def create_company(*, template=None, **fields):
    """Crea una empresa lista para usar: validada, con matriz de roles y configs."""
    company = Company(**fields)
    company.full_clean()
    company.save()
    copy_role_matrix(company, template)
    ensure_company_configs(company)
    return company
