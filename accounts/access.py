"""Allow-list POR EMPRESA: decide qué correos pueden solicitar acceso a una empresa y
con qué rol entran."""
from .models import AllowedDomain, AllowedEmail, BlockedEmail, Role


def _split_domain(email):
    email = (email or '').strip().lower()
    if '@' not in email:
        return email, ''
    return email, email.rsplit('@', 1)[1]


def is_email_blocked(company, email):
    """True si el correo está en la lista de bloqueados de `company` (gana sobre todo)."""
    email, _ = _split_domain(email)
    if company is None or not email:
        return False
    return BlockedEmail.objects.filter(company=company, email=email).exists()


def is_email_allowed(company, email):
    """True si el correo está habilitado en `company` por dominio o como excepción puntual,
    y NO está bloqueado puntualmente (un dominio permitido puede tener correos negados)."""
    email, domain = _split_domain(email)
    if company is None or not domain:
        return False
    if is_email_blocked(company, email):
        return False
    if AllowedEmail.objects.filter(company=company, email=email, is_active=True).exists():
        return True
    return AllowedDomain.objects.filter(company=company, domain=domain, is_active=True).exists()


def resolve_default_role(company, email):
    """Rol predefinido para el correo en `company` (excepción puntual gana sobre dominio);
    Ejecutor por defecto."""
    email, domain = _split_domain(email)
    if company is None:
        return Role.EJECUTOR
    allowed_email = AllowedEmail.objects.filter(company=company, email=email, is_active=True).first()
    if allowed_email and allowed_email.default_role:
        return allowed_email.default_role
    allowed_domain = AllowedDomain.objects.filter(company=company, domain=domain, is_active=True).first()
    if allowed_domain and allowed_domain.default_role:
        return allowed_domain.default_role
    return Role.EJECUTOR
