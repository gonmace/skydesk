"""Multi-empresa (tenants) por prefijo de ruta: `/<slug>/...`.

Diseño: una sola URLconf sin prefijos. `CompanyMiddleware` detecta el primer segmento
de `request.path_info`, lo resuelve a una `Company` (cache), lo RECORTA de `path_info`
(que es lo que usa el resolver de URLs) y agrega `/<slug>/` al *script prefix* de
Django, de modo que `reverse()`, `{% url %}`, `LOGIN_URL`, `redirect_to_login`, etc.
generan URLs prefijadas sin tocar ni una vista ni un template. `request.path` queda
intacto (lo usan `get_full_path()`/`build_absolute_uri()` y el tab activo del nav).

El prefijo de script vive en un `asgiref.Local` (contextvars): es por request tanto en
WSGI como en ASGI (daphne/uvicorn), y el handler ASGI lo resetea al inicio de cada
request. Igual se restaura en `finally` — el `Client` de tests no lo resetea entre
llamadas y sin eso todo `reverse()` posterior del test saldría prefijado.

Reglas de acceso:
- Superuser (global, `Profile.company` nulo): entra a cualquier empresa.
- Usuario que no es miembro de Y (principal ni adicional) en `/Y/...` → 403. En `/...`
  sin prefijo → redirect a su empresa PRINCIPAL `/X/...`. Ver `is_member`/`members_q`.
- Empresa inactiva → 404 (anónimo) / 403 (logueado, salvo superuser).
- Sin prefijo: anónimo solo ve login/reset genéricos; superuser en `/` va a /empresas/.

NUNCA llamar a `reverse()` desde un thread (p. ej. dentro de `send_mail_async`): el hilo
nuevo no tiene prefijo. Para links fuera de un request usar `company_path`/`company_url`.
"""
import re

from asgiref.local import Local
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import get_script_prefix, reverse, set_script_prefix

from .models import COMPANY_CACHE_KEY, RESERVED_SLUGS, Company

_SLUG_RE = re.compile(r'^[a-z][a-z0-9-]{1,30}$')
COMPANY_CACHE_TTL = 300

# Prefijo de script ORIGINAL del request (antes de agregar el slug) — lo usa
# company_path() para no duplicar el slug cuando se llama dentro de un request prefijado.
_state = Local()


def _admin_first_segment():
    return getattr(settings, 'ADMIN_URL', 'admin/').strip('/').split('/')[0]


def excluded_first_segments():
    """Primeros segmentos de ruta que nunca se interpretan como slug de empresa."""
    return RESERVED_SLUGS | {_admin_first_segment()}


def get_company_by_slug(slug):
    """Company por slug, cacheada (también los fallos: `None`). Slugs con formato
    inválido ni consultan ni ensucian el cache."""
    if not slug or not _SLUG_RE.match(slug):
        return None
    key = COMPANY_CACHE_KEY.format(slug)
    sentinel = object()
    # Redis caído no debe tumbar la app (mismo criterio que las sesiones cached_db):
    # sin cache se resuelve contra la DB en cada request y listo.
    try:
        company = cache.get(key, sentinel)
    except Exception:
        return Company.objects.filter(slug=slug).first()
    if company is sentinel:
        company = Company.objects.filter(slug=slug).first()
        try:
            cache.set(key, company, COMPANY_CACHE_TTL)
        except Exception:
            pass
    return company


def get_user_company(user):
    """Empresa del usuario vía Profile (None para anónimos, superuser global o sin perfil)."""
    if user is None or not user.is_authenticated:
        return None
    profile = getattr(user, 'profile', None)
    return profile.company if profile is not None else None


def get_user_company_id(user):
    if user is None or not user.is_authenticated:
        return None
    profile = getattr(user, 'profile', None)
    return profile.company_id if profile is not None else None


# ── Pertenencia (principal + adicionales) ─────────────────────────────────────
# Un usuario operativo tiene una empresa principal (Profile.company) y, esporádicamente,
# adicionales (Profile.extra_companies) donde opera con el mismo rol. Todo chequeo de
# "¿puede entrar a esta empresa?" pasa por acá — nunca comparar profile.company a mano.

def user_company_ids(user):
    """IDs de TODAS las empresas del usuario (principal + adicionales). Memoizado en el
    objeto `user` (una query M2M por request como máximo). Vacío para anónimos,
    superuser global y usuarios sin perfil."""
    if user is None or not user.is_authenticated:
        return frozenset()
    if '_company_ids' not in user.__dict__:
        profile = getattr(user, 'profile', None)
        ids = set()
        if profile is not None:
            if profile.company_id:
                ids.add(profile.company_id)
            ids.update(profile.extra_companies.values_list('pk', flat=True))
        user.__dict__['_company_ids'] = frozenset(ids)
    return user.__dict__['_company_ids']


def is_member(user, company):
    """True si `company` (instancia o id) es la principal o una adicional del usuario.
    El superuser NO es miembro de nada: su bypass se decide aparte, con is_superuser."""
    if company is None:
        return False
    company_id = getattr(company, 'pk', company)
    # Caso común (empresa principal): se resuelve sin la query M2M de adicionales.
    if company_id == get_user_company_id(user):
        return True
    return company_id in user_company_ids(user)


def user_companies(user):
    """Empresas ACTIVAS del usuario, la principal primero y el resto por nombre — para
    el selector "Cambiar de empresa" del menú."""
    ids = user_company_ids(user)
    if not ids:
        return []
    main_id = get_user_company_id(user)
    companies = list(Company.objects.filter(pk__in=ids, is_active=True).order_by('name'))
    companies.sort(key=lambda c: (c.pk != main_id, c.name))
    return companies


def members_q(company):
    """Q sobre `User` que matchea a los miembros de `company` (principal o adicional).
    El join M2M puede duplicar filas: el queryset que lo use lleva `.distinct()`."""
    from django.db.models import Q
    return Q(profile__company=company) | Q(profile__extra_companies=company)


def company_path(company, viewname, *args, **kwargs):
    """`reverse()` con el prefijo `/<slug>/` de `company`, funcione o no dentro de un
    request (y sin duplicar el slug si el request actual ya está prefijado)."""
    root = getattr(_state, 'root_prefix', None) or '/'
    old = get_script_prefix()
    set_script_prefix(f'{root}{company.slug}/')
    try:
        return reverse(viewname, args=args or None, kwargs=kwargs or None)
    finally:
        set_script_prefix(old)


def site_url():
    return (getattr(settings, 'SITE_URL', '') or '').rstrip('/')


def company_url(company, viewname, *args, **kwargs):
    """URL absoluta (para correos) de una vista dentro de la empresa."""
    return site_url() + company_path(company, viewname, *args, **kwargs)


def strip_company_prefix(path):
    """'/embol/123/' → ('embol', '/123/') si el primer segmento es una empresa; si no,
    (None, path). Para reescribir `next=` al cambiar de empresa (impersonación)."""
    seg, _, rest = path.lstrip('/').partition('/')
    if seg and seg not in excluded_first_segments() and get_company_by_slug(seg) is not None:
        return seg, '/' + rest
    return None, path


class CompanyMiddleware:
    """Ver el docstring del módulo. Debe ir al FINAL de MIDDLEWARE: necesita
    `request.user` (AuthenticationMiddleware), `request.real_user` (impersonación) y
    `messages` (MessageMiddleware) ya inicializados."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.company = None
        _state.root_prefix = get_script_prefix()
        first, _, rest = request.path_info.lstrip('/').partition('/')
        if first and first not in excluded_first_segments() and not first.isdigit():
            company = get_company_by_slug(first)
            if company is not None:
                return self._serve_company(request, company, first, rest)
        return self._serve_root(request, first)

    # ── Con prefijo de empresa ──────────────────────────────────────────────────
    def _serve_company(self, request, company, slug, rest):
        user = request.user
        real_user = getattr(request, 'real_user', None)
        is_super = user.is_authenticated and user.is_superuser
        if not company.is_active and not is_super and not (real_user is not None and real_user.is_superuser):
            if user.is_authenticated:
                return render(request, 'accounts/company_inactive.html', {'company': company}, status=403)
            raise Http404
        if user.is_authenticated and not user.is_superuser:
            if not is_member(user, company):
                own_company = get_user_company(user)
                if real_user is not None and real_user.is_superuser and own_company is not None:
                    # Superuser impersonando a alguien que no opera acá: seguirlo a su
                    # empresa principal.
                    query = f'?{request.META["QUERY_STRING"]}' if request.META.get('QUERY_STRING') else ''
                    return redirect(f'{_state.root_prefix}{own_company.slug}/{rest}{query}')
                raise PermissionDenied('Tu cuenta no pertenece a esta empresa.')
            # Empresa ACTIVA del request: las capacidades se resuelven con la matriz de
            # roles de esta empresa, no la de la principal (ver permissions._load_capability_set).
            user.__dict__['_active_company_id'] = company.pk
        request.company = company
        request.path_info = '/' + rest
        request.META['PATH_INFO'] = request.path_info
        old = get_script_prefix()
        set_script_prefix(f'{old}{slug}/')
        try:
            return self.get_response(request)
        finally:
            set_script_prefix(old)

    # ── Sin prefijo ─────────────────────────────────────────────────────────────
    def _serve_root(self, request, first):
        user = request.user
        if not user.is_authenticated:
            return self.get_response(request)
        if user.is_superuser:
            if request.path_info == '/':
                return redirect('companies:list')
            return self.get_response(request)
        company = get_user_company(user)
        if company is not None and company.is_active:
            if first in excluded_first_segments():
                # /empresas/, admin, etc.: rutas del servidor, no de la empresa — que la
                # vista decida (para un usuario de empresa son superuser-only → 403).
                return self.get_response(request)
            if request.method in ('GET', 'HEAD'):
                return redirect(f'{_state.root_prefix}{company.slug}{request.get_full_path()}')
            raise PermissionDenied
        # Usuario operativo sin empresa (o con la empresa desactivada): solo puede tocar
        # las rutas de cuenta (cerrar sesión, perfil) fuera de un prefijo.
        if first == 'acceso':
            return self.get_response(request)
        if company is not None:
            return render(request, 'accounts/company_inactive.html', {'company': company}, status=403)
        raise PermissionDenied('Tu cuenta no está asociada a ninguna empresa.')
