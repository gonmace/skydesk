"""Allow-list: decide qué correos pueden solicitar acceso y con qué rol entran."""
from .models import AllowedDomain, AllowedEmail, Role


def _split_domain(email):
    email = (email or '').strip().lower()
    if '@' not in email:
        return email, ''
    return email, email.rsplit('@', 1)[1]


def is_email_allowed(email):
    """True si el correo está habilitado por dominio o como excepción puntual."""
    email, domain = _split_domain(email)
    if not domain:
        return False
    if AllowedEmail.objects.filter(email=email, is_active=True).exists():
        return True
    return AllowedDomain.objects.filter(domain=domain, is_active=True).exists()


def resolve_default_role(email):
    """Rol predefinido para el correo (excepción puntual gana sobre dominio); Ejecutor por defecto."""
    email, domain = _split_domain(email)
    allowed_email = AllowedEmail.objects.filter(email=email, is_active=True).first()
    if allowed_email and allowed_email.default_role:
        return allowed_email.default_role
    allowed_domain = AllowedDomain.objects.filter(domain=domain, is_active=True).first()
    if allowed_domain and allowed_domain.default_role:
        return allowed_domain.default_role
    return Role.EJECUTOR
