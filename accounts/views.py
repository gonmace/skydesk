import secrets
from functools import wraps
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import LoginView, redirect_to_login
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import (
    url_has_allowed_host_and_scheme, urlsafe_base64_decode, urlsafe_base64_encode,
)
from django.views.decorators.http import require_POST

from attachments.forms import NextcloudConfigForm
from attachments.models import NextcloudConfig

from .access import is_email_allowed, resolve_default_role
from .forms import (
    ActivationForm, AdminUserEditForm, AllowedDomainForm, AllowedEmailForm,
    EmailAuthenticationForm, InviteForm, NextcloudOAuthConfigForm, ProfileNameForm,
    RequestAccessForm,
)
from .models import (
    AllowedDomain, AllowedEmail, NextcloudOAuthConfig, Profile, Role, RolePermission, UserPermission,
)
from .permissions import CAPABILITIES, DEFAULT_ROLE_CAPS, INDIVIDUAL_OVERRIDE_ROLES, get_user_role

User = get_user_model()

NEUTRAL_MSG = (
    'Si el correo está habilitado, te enviamos un enlace para activar tu cuenta. '
    'Revisá tu bandeja de entrada.'
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_or_create_pending_user(email, role=''):
    """Obtiene/crea un usuario inactivo para el correo. Si se pasa rol, fija el Profile."""
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        user = User.objects.create(username=email[:150], email=email, is_active=False)
        user.set_unusable_password()
        user.save()
    if role:
        Profile.objects.update_or_create(user=user, defaults={'role': role})
    return user


def _send_activation_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = request.build_absolute_uri(reverse('accounts:activate', args=[uid, token]))
    body = render_to_string('accounts/emails/activation.txt', {'user': user, 'link': link})
    user.email_user('Activá tu cuenta — SkyDesk Tickets', body)


def _superuser_required(view):
    # No usar user_passes_test tal cual: si el usuario ya está autenticado pero no es
    # superusuario, redirigir al login (con CustomLoginView.redirect_authenticated_user=True)
    # genera un ping-pong infinito de redirects login↔admin. Un no-superusuario autenticado
    # debe recibir 403; solo el anónimo va al login.
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.user.is_superuser:
            return view(request, *args, **kwargs)
        if request.user.is_authenticated:
            raise PermissionDenied
        return redirect_to_login(request.get_full_path(), reverse('accounts:login'))
    return wrapped


def _client_ip(request):
    # X-Real-IP (no XFF): el primer hop de X-Forwarded-For lo controla el cliente —
    # con XFF el throttle por IP se bypaseaba mandando un header falso por request.
    from core.client_ip import client_ip
    return client_ip(request)


def _request_access_allowed(request, email):
    """Throttle anti-abuso: cooldown por email (10 min) + tope por IP (10/h)."""
    ip = _client_ip(request)
    email_key = f'reqacc:email:{email.lower()}'
    ip_key = f'reqacc:ip:{ip}'
    if cache.get(email_key):
        return False
    ip_count = cache.get(ip_key, 0)
    if ip_count >= 10:
        return False
    cache.set(email_key, 1, 600)            # 10 minutos
    cache.set(ip_key, ip_count + 1, 3600)   # ventana de 1 hora
    return True


# ── Onboarding ──────────────────────────────────────────────────────────────

def request_access(request):
    if request.user.is_authenticated:
        return redirect('tickets:board')
    if request.method == 'POST':
        form = RequestAccessForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            # Throttle + allow-list. Solo se envía activación a cuentas que NUNCA activaron
            # (sin contraseña usable): así un usuario dado de baja no puede reactivarse solo.
            if _request_access_allowed(request, email) and is_email_allowed(email):
                user = _get_or_create_pending_user(email)
                if not user.is_active and not user.has_usable_password():
                    _send_activation_email(request, user)
            messages.success(request, NEUTRAL_MSG)
            return redirect('accounts:login')
    else:
        form = RequestAccessForm()
    return render(request, 'accounts/request_access.html', {'form': form})


def activate(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    valid = user is not None and default_token_generator.check_token(user, token)
    # Defensa en profundidad: una cuenta inactiva pero CON contraseña usable fue dada de baja
    # por el admin; no debe poder auto-reactivarse por este flujo (solo el admin la reactiva).
    if user is not None and not user.is_active and user.has_usable_password():
        valid = False
    if not valid:
        return render(request, 'accounts/activate.html', {'invalid': True})

    if request.method == 'POST':
        form = ActivationForm(user, request.POST)
        if form.is_valid():
            form.save()
            user.is_active = True
            user.save(update_fields=['is_active'])
            Profile.objects.get_or_create(
                user=user, defaults={'role': resolve_default_role(user.email)},
            )
            login(request, user, backend='accounts.backends.EmailBackend')
            messages.success(request, '¡Cuenta activada! Bienvenido/a.')
            return redirect('tickets:board')
    else:
        form = ActivationForm(user)
    return render(request, 'accounts/activate.html', {'form': form, 'invalid': False, 'email': user.email})


@login_required
def profile(request):
    if request.method == 'POST':
        form = ProfileNameForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Perfil actualizado.')
            return redirect('accounts:profile')
    else:
        form = ProfileNameForm(instance=request.user)
    return render(request, 'accounts/profile.html', {'form': form})


class CustomLoginView(LoginView):
    template_name = 'accounts/login.html'
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['nextcloud_login_enabled'] = NextcloudOAuthConfig.load().enabled
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        if not form.cleaned_data.get('remember_me'):
            self.request.session.set_expiry(0)  # expira al cerrar el navegador
        return response


# ── Allow-list (solo superuser) ──────────────────────────────────────────────

@_superuser_required
def access_admin(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_domain':
            form = AllowedDomainForm(request.POST)
            if form.is_valid():
                obj = form.save(commit=False)
                obj.created_by = request.user
                obj.save()
                messages.success(request, f'Dominio «{obj.domain}» agregado.')
            else:
                messages.error(request, 'Revisá los datos del dominio.')
        elif action == 'add_email':
            form = AllowedEmailForm(request.POST)
            if form.is_valid():
                obj = form.save(commit=False)
                obj.created_by = request.user
                obj.save()
                messages.success(request, f'Correo «{obj.email}» agregado.')
            else:
                messages.error(request, 'Revisá los datos del correo.')
        elif action == 'invite':
            form = InviteForm(request.POST)
            if form.is_valid():
                email = form.cleaned_data['email']
                role = form.cleaned_data['role']
                AllowedEmail.objects.update_or_create(
                    email=email,
                    defaults={'default_role': role, 'is_active': True, 'created_by': request.user},
                )
                user = _get_or_create_pending_user(email, role=role)
                if user.is_active:
                    messages.info(request, f'«{email}» ya tiene cuenta activa.')
                else:
                    _send_activation_email(request, user)
                    messages.success(request, f'Invitación enviada a «{email}».')
            else:
                messages.error(request, 'Correo inválido para invitar.')
        elif action == 'toggle_domain':
            obj = get_object_or_404(AllowedDomain, pk=request.POST.get('id'))
            obj.is_active = not obj.is_active
            obj.save(update_fields=['is_active'])
        elif action == 'toggle_email':
            obj = get_object_or_404(AllowedEmail, pk=request.POST.get('id'))
            obj.is_active = not obj.is_active
            obj.save(update_fields=['is_active'])
        elif action == 'delete_domain':
            get_object_or_404(AllowedDomain, pk=request.POST.get('id')).delete()
            messages.success(request, 'Dominio eliminado.')
        elif action == 'delete_email':
            get_object_or_404(AllowedEmail, pk=request.POST.get('id')).delete()
            messages.success(request, 'Correo eliminado.')
        elif action == 'set_email_role':
            obj = get_object_or_404(AllowedEmail, pk=request.POST.get('id'))
            role = request.POST.get('default_role', '')
            if role and role not in dict(Role.choices):
                messages.error(request, 'Rol inválido.')
            else:
                obj.default_role = role  # '' = sin rol (cae al default del dominio / EJECUTOR)
                obj.save(update_fields=['default_role'])
                messages.success(request, f'Rol de «{obj.email}» actualizado.')
        elif action == 'toggle_user':
            target = get_object_or_404(User, pk=request.POST.get('id'))
            if target.pk == request.user.pk or target.is_superuser:
                messages.error(request, 'No podés cambiar el estado de este usuario.')
            elif not target.is_active and not target.has_usable_password():
                # Todavía no activó su cuenta (sin contraseña): no se puede activar a mano,
                # tiene que pasar por el enlace de invitación (ver activate()/request_access()).
                messages.error(
                    request,
                    f'«{target.email or target.username}» todavía no activó su cuenta. '
                    'Usá «Reenviar invitación» en vez de activarla directamente.',
                )
            else:
                target.is_active = not target.is_active
                target.save(update_fields=['is_active'])
                estado = 'activado' if target.is_active else 'desactivado'
                messages.success(request, f'Usuario «{target.email or target.username}» {estado}.')
        elif action == 'resend_invite':
            target = get_object_or_404(User, pk=request.POST.get('id'))
            if target.is_active:
                messages.info(request, 'Ese usuario ya tiene la cuenta activa.')
            else:
                _send_activation_email(request, target)
                messages.success(request, f'Invitación reenviada a «{target.email}».')
        elif action == 'delete_user':
            target = get_object_or_404(User, pk=request.POST.get('id'))
            label = target.email or target.username
            if target.pk == request.user.pk or target.is_superuser:
                messages.error(request, 'No podés eliminar este usuario.')
            else:
                from tickets.models import Assignment
                if Assignment.objects.filter(user=target).exists():
                    messages.error(
                        request,
                        f'«{label}» tiene tickets asignados (historial de trabajo/tiempos). '
                        'Desactivá la cuenta en vez de eliminarla para no perder ese historial.',
                    )
                else:
                    target.delete()
                    messages.success(request, f'Cuenta «{label}» eliminada.')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            pending = list(messages.get_messages(request))
            last = pending[-1] if pending else None
            return JsonResponse({'message': str(last) if last else '', 'tag': last.tags if last else ''})
        return redirect('accounts:access_admin')

    users_qs = User.objects.select_related('profile').order_by('is_active', 'email')
    return render(request, 'accounts/access_admin.html', {
        'domains': AllowedDomain.objects.all(),
        'emails': AllowedEmail.objects.all(),
        'role_choices': Role.choices,
        'users': Paginator(users_qs, 20).get_page(request.GET.get('page')),
        'domain_form': AllowedDomainForm(),
        'email_form': AllowedEmailForm(),
        'invite_form': InviteForm(),
    })


@_superuser_required
def user_edit(request, pk):
    target = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        action = request.POST.get('action', 'save_account')
        # Los overrides individuales solo existen para roles en INDIVIDUAL_OVERRIDE_ROLES
        # (ver accounts/permissions.py) — igual se revalida acá server-side, no solo
        # ocultando la sección en el template.
        if action in ('save_permissions', 'reset_permissions'):
            if get_user_role(target) not in INDIVIDUAL_OVERRIDE_ROLES:
                messages.error(request, 'Este rol no admite configuración individual.')
                return redirect('accounts:user_edit', pk=target.pk)
            if action == 'reset_permissions':
                UserPermission.objects.filter(user=target).delete()
                messages.success(request, 'Se restableció el default del rol.')
            else:
                for cap_key, _label in CAPABILITIES:
                    enabled = request.POST.get(cap_key) == 'on'
                    UserPermission.objects.update_or_create(
                        user=target, capability=cap_key, defaults={'enabled': enabled},
                    )
                messages.success(request, 'Permisos personalizados de la cuenta actualizados.')
            return redirect('accounts:user_edit', pk=target.pk)

        form = AdminUserEditForm(request.POST, instance=target)
        if form.is_valid():
            form.save()
            new_role = form.cleaned_data['role']
            Profile.objects.update_or_create(user=target, defaults={'role': new_role})
            if new_role not in INDIVIDUAL_OVERRIDE_ROLES:
                # Deja de ser elegible para overrides individuales — se limpian para no
                # dejar una config "fantasma" si el rol vuelve a cambiar más adelante.
                UserPermission.objects.filter(user=target).delete()
            messages.success(request, f'Cuenta «{target.email or target.username}» actualizada.')
            return redirect('accounts:access_admin')
    else:
        form = AdminUserEditForm(instance=target)

    target_role = get_user_role(target)
    show_overrides = target_role in INDIVIDUAL_OVERRIDE_ROLES
    permission_rows = []
    if show_overrides:
        overrides = {up.capability: up.enabled for up in UserPermission.objects.filter(user=target)}
        role_defaults = {
            rp.capability: rp.enabled for rp in RolePermission.objects.filter(role=target_role)
        }
        for cap_key, cap_label in CAPABILITIES:
            permission_rows.append({
                'key': cap_key, 'label': cap_label,
                'enabled': overrides.get(cap_key, role_defaults.get(cap_key, False)),
                'role_default': role_defaults.get(cap_key, False),
                'is_overridden': cap_key in overrides,
            })

    return render(request, 'accounts/user_edit.html', {
        'form': form, 'target': target,
        'show_overrides': show_overrides,
        'permission_rows': permission_rows,
        'has_overrides': any(r['is_overridden'] for r in permission_rows),
    })


@_superuser_required
def roles_board(request):
    roles = Role.choices  # [(value, label), ...]

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save_matrix':
            for role_value, _ in roles:
                for cap_key, _label in CAPABILITIES:
                    enabled = request.POST.get(f'{role_value}:{cap_key}') == 'on'
                    RolePermission.objects.update_or_create(
                        role=role_value, capability=cap_key, defaults={'enabled': enabled},
                    )
            messages.success(request, 'Permisos actualizados.')
        return redirect('accounts:roles_board')

    # Matriz actual {(role, cap): enabled}
    current = {
        (rp.role, rp.capability): rp.enabled
        for rp in RolePermission.objects.all()
    }
    matrix = []
    for cap_key, cap_label in CAPABILITIES:
        row = {'key': cap_key, 'label': cap_label, 'cells': []}
        for role_value, role_label in roles:
            row['cells'].append({
                'role': role_value,
                'label': role_label,
                'enabled': current.get((role_value, cap_key), False),
            })
        matrix.append(row)

    return render(request, 'accounts/roles_board.html', {
        'roles': roles,
        'matrix': matrix,
    })


@_superuser_required
def nextcloud_config(request):
    """Config de Nextcloud editable solo por el superuser: dos tarjetas independientes —
    storage WebDAV (pisa a la de .env si `enabled`) y login OAuth2 (credenciales de
    naturaleza distinta, ver NextcloudOAuthConfig)."""
    config = NextcloudConfig.load()
    oauth_config = NextcloudOAuthConfig.load()
    form = NextcloudConfigForm(instance=config)
    oauth_form = NextcloudOAuthConfigForm(instance=oauth_config)

    if request.method == 'POST':
        action = request.POST.get('action', 'save')
        if action in ('save', 'test'):
            form = NextcloudConfigForm(request.POST, instance=config)
            if action == 'test':
                if form.is_valid():
                    from attachments.backends.nextcloud import NextcloudBackend, NextcloudError
                    try:
                        backend = NextcloudBackend(
                            base_url=form.cleaned_data['base_url'],
                            user=form.cleaned_data['user'],
                            token=form.cleaned_data['token'],
                            root=form.cleaned_data['root'],
                        )
                        if backend.exists(''):
                            messages.success(request, 'Conexión con Nextcloud OK (la carpeta raíz existe).')
                        else:
                            messages.warning(
                                request,
                                'Se conectó, pero la carpeta raíz todavía no existe (se crea sola al '
                                'subir el primer archivo) o las credenciales no tienen acceso a ella.',
                            )
                    except NextcloudError as exc:
                        messages.error(request, f'No se pudo conectar: {exc}')
                    except Exception as exc:
                        messages.error(request, f'No se pudo conectar: {exc}')
                else:
                    messages.error(request, 'Completá URL, usuario y app-password para probar la conexión.')
            else:
                if form.is_valid():
                    form.save()
                    messages.success(request, 'Configuración de Nextcloud actualizada.')
                    return redirect('accounts:nextcloud_config')
                else:
                    messages.error(request, 'Revisá los datos.')
        elif action == 'save_oauth':
            oauth_form = NextcloudOAuthConfigForm(request.POST, instance=oauth_config)
            if oauth_form.is_valid():
                oauth_form.save()
                messages.success(request, 'Configuración de login con Nextcloud actualizada.')
                return redirect('accounts:nextcloud_config')
            else:
                messages.error(request, 'Revisá los datos de login con Nextcloud.')

    return render(request, 'accounts/nextcloud_config.html', {
        'form': form, 'config': config,
        'oauth_form': oauth_form, 'oauth_config': oauth_config,
    })


# ── Login con Nextcloud (OAuth2) ────────────────────────────────────────────────

def nextcloud_login(request):
    """Redirige a Nextcloud para autorizar. El usuario nunca escribe su password de
    Nextcloud acá — vuelve con un `code` que se canjea server-side en el callback."""
    config = NextcloudOAuthConfig.load()
    if not (config.enabled and config.base_url and config.client_id):
        messages.error(request, 'El login con Nextcloud no está habilitado.')
        return redirect('accounts:login')

    state = secrets.token_urlsafe(32)
    request.session['nc_oauth_state'] = state
    next_url = request.GET.get('next', '')
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        request.session['nc_oauth_next'] = next_url

    redirect_uri = request.build_absolute_uri(reverse('accounts:nextcloud_callback'))
    params = urlencode({
        'response_type': 'code',
        'client_id': config.client_id,
        'redirect_uri': redirect_uri,
        'state': state,
    })
    return redirect(f'{config.resolved_authorize_url()}?{params}')


def nextcloud_callback(request):
    """Canjea el `code` por un token, resuelve el email vía la API OCS de Nextcloud, y
    loguea (creando la cuenta si hace falta) — todo gateado por la allow-list existente
    (`is_email_allowed`/`resolve_default_role`), la misma que gobierna el onboarding
    normal por correo."""
    config = NextcloudOAuthConfig.load()
    if not config.enabled:
        raise Http404

    next_url = request.session.pop('nc_oauth_next', '') or reverse('tickets:board')
    expected_state = request.session.pop('nc_oauth_state', None)
    state = request.GET.get('state', '')
    if not expected_state or state != expected_state:
        messages.error(request, 'La sesión de login con Nextcloud expiró o no es válida. Probá de nuevo.')
        return redirect('accounts:login')

    code = request.GET.get('code', '')
    if not code:
        messages.error(request, 'Nextcloud no devolvió un código de autorización.')
        return redirect('accounts:login')

    redirect_uri = request.build_absolute_uri(reverse('accounts:nextcloud_callback'))
    try:
        token_resp = requests.post(config.resolved_token_url(), data={
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
            'client_id': config.client_id,
            'client_secret': config.client_secret,
        }, timeout=10)
        token_resp.raise_for_status()
        access_token = token_resp.json()['access_token']

        info_resp = requests.get(config.resolved_userinfo_url(), headers={
            'Authorization': f'Bearer {access_token}',
            'OCS-APIRequest': 'true',
            'Accept': 'application/json',
        }, timeout=10)
        info_resp.raise_for_status()
        data = info_resp.json()['ocs']['data']
        email = (data.get('email') or '').strip().lower()
        display_name = (data.get('displayname') or '').strip()
    except (requests.RequestException, ValueError, KeyError):
        messages.error(request, 'No se pudo completar el login con Nextcloud. Probá de nuevo.')
        return redirect('accounts:login')

    if not email:
        messages.error(request, 'Tu usuario de Nextcloud no tiene un email configurado.')
        return redirect('accounts:login')
    if not is_email_allowed(email):
        messages.error(request, 'Tu cuenta de Nextcloud no está habilitada para acceder a SkyDesk.')
        return redirect('accounts:login')

    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        user = User.objects.create(username=email[:150], email=email, is_active=True)
        if display_name:
            first, _, last = display_name.partition(' ')
            user.first_name, user.last_name = first, last
        user.set_unusable_password()
        user.save()
        Profile.objects.get_or_create(user=user, defaults={'role': resolve_default_role(email)})
    elif not user.is_active:
        # Misma defensa en profundidad que `activate`: una cuenta dada de baja (inactiva
        # PERO con password usable) no se reactiva sola por este flujo.
        if user.has_usable_password():
            messages.error(request, 'Esta cuenta fue dada de baja. Contactá al administrador.')
            return redirect('accounts:login')
        user.is_active = True
        user.save(update_fields=['is_active'])
        Profile.objects.get_or_create(user=user, defaults={'role': resolve_default_role(email)})

    login(request, user, backend='accounts.backends.EmailBackend')
    messages.success(request, f'Bienvenido/a, {user.get_full_name() or user.email}.')
    return redirect(next_url)


@login_required
@require_POST
def dev_impersonate(request):
    """Impersonar a un usuario real (solo DEBUG + superuser): guarda su id en la sesión;
    `DevImpersonationMiddleware` reemplaza `request.user` por ese usuario en cada request
    siguiente, así se ve la app con sus datos reales (tickets asignados, notificaciones).
    No existe fuera de DEBUG ni para no-superuser — 404 directo, sin insinuar que el
    feature existe en producción.

    `request.real_user` es el superuser real cuando ya se está impersonando a alguien
    (lo cuelga el middleware); se usa acá en vez de `request.user` para permitir cambiar
    de usuario impersonado sin tener que salir primero."""
    real_user = getattr(request, 'real_user', request.user)
    if not settings.DEBUG or not real_user.is_superuser:
        raise Http404
    user_id = request.POST.get('user_id', '')
    if user_id and User.objects.filter(pk=user_id, is_active=True).exists():
        request.session['impersonate_id'] = user_id
    else:
        request.session.pop('impersonate_id', None)
    next_url = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse('tickets:board')
    return redirect(next_url)
