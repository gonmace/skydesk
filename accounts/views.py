import secrets
from functools import wraps
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import LoginView, PasswordResetView, redirect_to_login
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotModified, JsonResponse
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
from core.mail import resolve_from_email, send_mail_async, send_mail_now

from .access import is_email_allowed, is_email_blocked, resolve_default_role
from .forms import (
    ActivationForm, AdminUserEditForm, AllowedDomainForm, AllowedEmailForm, BlockedEmailForm,
    CompanySenderForm, EmailAuthenticationForm, EmailConfigForm, InviteForm,
    NextcloudOAuthConfigForm, ProfileNameForm, RequestAccessForm, role_choices_for,
)
from .models import (
    AllowedDomain, AllowedEmail, BlockedEmail, EmailConfig, NextcloudOAuthConfig,
    Profile, Role, RolePermission, UserPermission,
)
from .permissions import (
    CAPABILITIES, DEFAULT_ROLE_CAPS, INDIVIDUAL_OVERRIDE_ROLES, get_user_role,
    has_capability,
)
from .tenancy import company_path, get_user_company, is_member, members_q

User = get_user_model()

NEUTRAL_MSG = (
    'Si el correo está habilitado, te enviamos un enlace para activar tu cuenta. '
    'Revisá tu bandeja de entrada.'
)


# ── Helpers ───────────────────────────────────────────────────────────────────

class OtherCompanyError(Exception):
    """El correo ya pertenece a un usuario de OTRA empresa (un email = una empresa)."""


def _company_required(view):
    """Vistas que solo tienen sentido dentro de una empresa (`/<slug>/acceso/...`):
    sin prefijo no hay a qué empresa solicitar acceso, ni qué allow-list consultar."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if getattr(request, 'company', None) is None:
            raise Http404
        return view(request, *args, **kwargs)
    return wrapped


def _brand(request):
    company = getattr(request, 'company', None)
    return (company.brand_name if company is not None and company.brand_name else 'Kanban')


def _get_or_create_pending_user(email, company, role=''):
    """Obtiene/crea un usuario inactivo para el correo dentro de `company`. Si se pasa
    rol, fija el Profile (con la empresa). Un correo que ya es de otra empresa no se
    puede reutilizar: OtherCompanyError — salvo que el superuser ya lo haya sumado como
    miembro adicional de esta empresa (/empresas/), en cuyo caso solo se ajusta el rol
    (global) sin tocar su empresa principal."""
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        user = User.objects.create(username=email[:150], email=email, is_active=False)
        user.set_unusable_password()
        user.save()
    profile = Profile.objects.filter(user=user).first()
    if user.is_superuser:
        raise OtherCompanyError(email)
    if profile is not None and profile.company_id and profile.company_id != company.pk:
        if not is_member(user, company):
            raise OtherCompanyError(email)
        if role and profile.role != role:
            profile.role = role
            profile.save(update_fields=['role'])
        return user
    if role:
        Profile.objects.update_or_create(user=user, defaults={'role': role, 'company': company})
    elif profile is not None and profile.company_id is None:
        profile.company = company
        profile.save(update_fields=['company'])
    return user


def _send_activation_email(request, user, sync=False):
    """Manda el correo de activación. `sync=True` lo envía en el request y propaga
    cualquier error de SMTP (usado en `request_access`, donde el usuario espera ver
    si el envío funcionó); si no, se manda en segundo plano como el resto de la app.
    El link lleva el prefijo de la empresa (reverse() dentro del request prefijado)."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = request.build_absolute_uri(reverse('accounts:activate', args=[uid, token]))
    brand = _brand(request)
    body = render_to_string('accounts/emails/activation.txt', {
        'user': user, 'link': link, 'brand_name': brand,
    })
    subject = f'Activá tu cuenta — {brand}'
    if sync:
        send_mail_now(subject, body, [user.email], company=request.company)
    else:
        send_mail_async(subject, body, [user.email], company=request.company)


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


def _accounts_manager_required(view):
    """Gate de la página Cuentas: superuser o capability accounts.manage (coordinador
    por defecto). Mismo criterio de redirects que _superuser_required."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.user.is_authenticated:
            if has_capability(request.user, 'accounts.manage'):
                return view(request, *args, **kwargs)
            raise PermissionDenied
        return redirect_to_login(request.get_full_path(), reverse('accounts:login'))
    return wrapped


def _can_manage_target(viewer, target):
    """Un gestor de cuentas no-superuser (coordinador) no ve ni toca superusers ni
    cuentas con rol ADMINISTRADOR — para él no existen (se filtran del listado y
    cualquier POST directo sobre ellas rebota)."""
    if viewer.is_superuser:
        return True
    return not target.is_superuser and get_user_role(target) != Role.ADMINISTRADOR


def _client_ip(request):
    # X-Real-IP (no XFF): el primer hop de X-Forwarded-For lo controla el cliente —
    # con XFF el throttle por IP se bypaseaba mandando un header falso por request.
    from core.client_ip import client_ip
    return client_ip(request)


def _access_throttle_check(request, email):
    """Solo lectura: 'ok' si se puede mandar activación, o el motivo del bloqueo
    ('email' = cooldown de ese correo, 'ip' = tope de la IP). No toca la cache —
    separado de `_access_throttle_bump_ip`/`_access_throttle_set_email` para poder
    avisar el motivo sin fingir éxito ni consumir cupo cuando el envío después falla."""
    ip = _client_ip(request)
    if cache.get(f'reqacc:email:{email.lower()}'):
        return 'email'
    if cache.get(f'reqacc:ip:{ip}', 0) >= 10:
        return 'ip'
    return 'ok'


def _access_throttle_bump_ip(request):
    ip = _client_ip(request)
    ip_key = f'reqacc:ip:{ip}'
    cache.set(ip_key, cache.get(ip_key, 0) + 1, 3600)   # ventana de 1 hora


def _access_throttle_set_email(email):
    cache.set(f'reqacc:email:{email.lower()}', 1, 600)  # 10 minutos


def _neutral(reason):
    """Respuesta neutra anti-enumeración; en DEBUG agrega el motivo real (solo dev)."""
    msgs = [{'text': NEUTRAL_MSG, 'tag': 'info'}]
    if settings.DEBUG:
        msgs.append({'text': f'[DEV] No se envió correo: {reason}', 'tag': 'warning'})
    return {'ok': True, 'messages': msgs}


def _process_access_request(request, email):
    """Decide y ejecuta qué pasa con una solicitud de acceso; devuelve el resultado
    para que la vista lo muestre (AJAX) o lo vuelque a `messages` (fallback sin JS).

    Anti-enumeración: si el correo NO está habilitado, se responde con el mensaje
    neutro de siempre (no confirma que no existe). Si SÍ está habilitado, ahora se
    confirma explícitamente y se intenta el envío en el momento (sync) para poder
    mostrar el error real de SMTP en vez de tragarlo en el log."""
    _access_throttle_bump_ip(request)  # el tope por IP corre siempre, esté o no habilitado
    if not is_email_allowed(request.company, email):
        return _neutral(f'el correo no está habilitado (ni AllowedEmail ni AllowedDomain activos, '
                        f'o está bloqueado) en la empresa «{request.company.slug}».')

    if _access_throttle_check(request, email) != 'ok':
        return {'ok': False, 'messages': [{
            'text': 'Ya te enviamos un enlace hace poco. Esperá unos minutos e intentá de nuevo.',
            'tag': 'warning',
        }]}

    # Solo se envía activación a cuentas que NUNCA activaron (sin contraseña usable):
    # así un usuario dado de baja no puede reactivarse solo.
    try:
        user = _get_or_create_pending_user(email, request.company)
    except OtherCompanyError:
        # Mismo mensaje neutro: no revelar que el correo existe en otra empresa.
        return _neutral('el correo ya pertenece a otra empresa (o es de un superuser).')
    if user.is_active or user.has_usable_password():
        return {'ok': True, 'messages': [{
            'text': 'Esa cuenta ya está activa. Iniciá sesión.', 'tag': 'info',
        }]}

    try:
        _send_activation_email(request, user, sync=True)
    except Exception as exc:
        # No se fija el cooldown de email: se puede reintentar de una vez tras arreglar el SMTP.
        return {'ok': False, 'messages': [{
            'text': f'Correo habilitado ({email}), pero no se pudo enviar: {exc}', 'tag': 'error',
        }]}

    _access_throttle_set_email(email)
    return {'ok': True, 'messages': [
        {'text': f'Correo habilitado ({email}).', 'tag': 'success'},
        {'text': 'Te enviamos el enlace de activación. Revisá tu bandeja de entrada.', 'tag': 'success'},
    ]}


_MESSAGE_LEVEL = {
    'success': messages.SUCCESS, 'error': messages.ERROR,
    'warning': messages.WARNING, 'info': messages.INFO,
}


# ── Onboarding ──────────────────────────────────────────────────────────────

@_company_required
def request_access(request):
    if request.user.is_authenticated:
        return redirect('tickets:board')
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if request.method == 'POST':
        form = RequestAccessForm(request.POST)
        if form.is_valid():
            result = _process_access_request(request, form.cleaned_data['email'])
            if is_ajax:
                return JsonResponse(result, status=200 if result['ok'] else 400)
            for m in result['messages']:
                messages.add_message(request, _MESSAGE_LEVEL[m['tag']], m['text'])
            return redirect('accounts:login')
        if is_ajax:
            return JsonResponse({'ok': False, 'messages': [
                {'text': 'Ingresá un correo válido.', 'tag': 'error'},
            ]}, status=400)
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

    # Empresa de la cuenta: la del Profile (invitación) o la del prefijo del link
    # (solicitud de acceso). Un link de una empresa de la que no es miembro no activa nada.
    profile = Profile.objects.filter(user=user).first()
    company = profile.company if (profile is not None and profile.company_id) else request.company
    if company is None:
        return render(request, 'accounts/activate.html', {'invalid': True})
    if request.company is not None and request.company.pk != company.pk:
        if not is_member(user, request.company):
            return render(request, 'accounts/activate.html', {'invalid': True})
        company = request.company

    if request.method == 'POST':
        form = ActivationForm(user, request.POST)
        if form.is_valid():
            form.save()
            user.is_active = True
            user.save(update_fields=['is_active'])
            profile, _ = Profile.objects.get_or_create(
                user=user,
                defaults={'role': resolve_default_role(company, user.email), 'company': company},
            )
            if profile.company_id is None:
                profile.company = company
                profile.save(update_fields=['company'])
            login(request, user, backend='accounts.backends.EmailBackend')
            messages.success(request, '¡Cuenta activada! Bienvenido/a.')
            return redirect(company_path(company, 'tickets:board'))
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


class BrandedPasswordResetView(PasswordResetView):
    """PasswordResetView con la marca de la empresa del prefijo en el asunto/firma del
    correo (el `{% url %}` del cuerpo ya sale prefijado por ser reverse() en request)."""

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = getattr(self.request, 'company', None)
        return kwargs

    def form_valid(self, form):
        self.extra_email_context = {**(self.extra_email_context or {}), 'brand_name': _brand(self.request)}
        return super().form_valid(form)


class CustomLoginView(LoginView):
    template_name = 'accounts/login.html'
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = getattr(self.request, 'company', None)
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = getattr(self.request, 'company', None)
        ctx['nextcloud_login_enabled'] = bool(company) and NextcloudOAuthConfig.objects.filter(
            company=company, enabled=True).exists()
        # Sin prefijo de empresa no hay a quién pedirle acceso: el login genérico es
        # para el superuser (y para quien llegue sin saber su empresa).
        ctx['show_request_access'] = company is not None
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        if not form.cleaned_data.get('remember_me'):
            self.request.session.set_expiry(0)  # expira al cerrar el navegador
        return response


# ── Allow-list y cuentas (por empresa) ───────────────────────────────────────

def _company_user_or_404(request, pk):
    """Usuario miembro (principal o adicional) de la empresa del request (los superusers
    no tienen empresa: nunca aparecen acá, ni siquiera para otro superuser)."""
    return get_object_or_404(User.objects.filter(members_q(request.company)).distinct(), pk=pk)


@_company_required
@_accounts_manager_required
def access_admin(request):
    company = request.company
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_domain':
            form = AllowedDomainForm(request.POST, viewer=request.user, company=company)
            if form.is_valid():
                obj = form.save(commit=False)
                obj.created_by = request.user
                obj.save()
                messages.success(request, f'Dominio «{obj.domain}» agregado.')
            else:
                messages.error(request, 'Revisá los datos del dominio.')
        elif action == 'add_email':
            form = AllowedEmailForm(request.POST, viewer=request.user, company=company)
            if form.is_valid():
                obj = form.save(commit=False)
                obj.created_by = request.user
                obj.save()
                messages.success(request, f'Correo «{obj.email}» agregado.')
            else:
                messages.error(request, 'Revisá los datos del correo.')
        elif action == 'add_blocked':
            form = BlockedEmailForm(request.POST, company=company)
            if form.is_valid():
                obj = form.save(commit=False)
                obj.created_by = request.user
                obj.save()
                messages.success(request, f'Correo «{obj.email}» bloqueado.')
                if User.objects.filter(email__iexact=obj.email, is_active=True).filter(members_q(company)).exists():
                    messages.warning(
                        request,
                        f'«{obj.email}» ya tiene una cuenta activa en esta empresa: el bloqueo solo '
                        'impide nuevas solicitudes e invitaciones. Desactivá la cuenta si corresponde.',
                    )
            else:
                messages.error(request, form.errors.get('email', ['Revisá el correo.'])[0])
        elif action == 'delete_blocked':
            obj = get_object_or_404(BlockedEmail, pk=request.POST.get('id'), company=company)
            obj.delete()
            messages.success(request, f'Correo «{obj.email}» desbloqueado.')
        elif action == 'invite':
            form = InviteForm(request.POST, viewer=request.user)
            if form.is_valid() and is_email_blocked(company, form.cleaned_data['email']):
                messages.error(
                    request,
                    f'«{form.cleaned_data["email"]}» está en la lista de correos bloqueados; '
                    'quitalo de ahí antes de invitarlo.',
                )
            elif form.is_valid():
                email = form.cleaned_data['email']
                role = form.cleaned_data['role']
                try:
                    user = _get_or_create_pending_user(email, company, role=role)
                except OtherCompanyError:
                    messages.error(request, f'«{email}» ya tiene cuenta en otra empresa.')
                else:
                    AllowedEmail.objects.update_or_create(
                        company=company, email=email,
                        defaults={'default_role': role, 'is_active': True, 'created_by': request.user},
                    )
                    if user.is_active:
                        messages.info(request, f'«{email}» ya tiene cuenta activa.')
                    else:
                        _send_activation_email(request, user)
                        messages.success(request, f'Invitación enviada a «{email}».')
            else:
                messages.error(request, 'Correo inválido para invitar.')
        elif action == 'save_sender':
            # Remitente de la empresa: es parte de su ficha (Marca) → solo superuser.
            if not request.user.is_superuser:
                raise PermissionDenied
            form = CompanySenderForm(request.POST, instance=company)
            if form.is_valid():
                form.save()
                messages.success(request, 'Remitente actualizado.')
            else:
                # is_valid() ya pisó los atributos de request.company con el POST inválido.
                company.refresh_from_db()
                error = next(iter(form.errors.values()))[0]
                messages.error(request, f'Remitente inválido: {error}')
        elif action == 'toggle_domain':
            obj = get_object_or_404(AllowedDomain, pk=request.POST.get('id'), company=company)
            obj.is_active = not obj.is_active
            obj.save(update_fields=['is_active'])
        elif action == 'toggle_email':
            obj = get_object_or_404(AllowedEmail, pk=request.POST.get('id'), company=company)
            obj.is_active = not obj.is_active
            obj.save(update_fields=['is_active'])
        elif action == 'delete_domain':
            get_object_or_404(AllowedDomain, pk=request.POST.get('id'), company=company).delete()
            messages.success(request, 'Dominio eliminado.')
        elif action == 'delete_email':
            get_object_or_404(AllowedEmail, pk=request.POST.get('id'), company=company).delete()
            messages.success(request, 'Correo eliminado.')
        elif action == 'set_email_role':
            obj = get_object_or_404(AllowedEmail, pk=request.POST.get('id'), company=company)
            role = request.POST.get('default_role', '')
            # role_choices_for: para un no-superuser, ADMINISTRADOR no es un rol válido.
            if role and role not in dict(role_choices_for(request.user)):
                messages.error(request, 'Rol inválido.')
            else:
                obj.default_role = role  # '' = sin rol (cae al default del dominio / EJECUTOR)
                obj.save(update_fields=['default_role'])
                messages.success(request, f'Rol de «{obj.email}» actualizado.')
        elif action == 'toggle_user':
            target = _company_user_or_404(request, request.POST.get('id'))
            if not _can_manage_target(request.user, target):
                raise PermissionDenied
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
            target = _company_user_or_404(request, request.POST.get('id'))
            if not _can_manage_target(request.user, target):
                raise PermissionDenied
            if target.is_active:
                messages.info(request, 'Ese usuario ya tiene la cuenta activa.')
            else:
                _send_activation_email(request, target)
                messages.success(request, f'Invitación reenviada a «{target.email}».')
        elif action == 'delete_user':
            target = _company_user_or_404(request, request.POST.get('id'))
            if not _can_manage_target(request.user, target):
                raise PermissionDenied
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

    users_qs = (User.objects.filter(members_q(company)).distinct()
                .select_related('profile__company').order_by('is_active', 'email'))
    domains = AllowedDomain.objects.filter(company=company)
    emails = AllowedEmail.objects.filter(company=company)
    if not request.user.is_superuser:
        # Para el coordinador con accounts.manage, los superusers y el rol
        # ADMINISTRADOR (espía solo-lectura) no existen: ni en el listado de cuentas
        # ni en los dominios/correos habilitados con ese rol por defecto.
        users_qs = users_qs.exclude(is_superuser=True).exclude(profile__role=Role.ADMINISTRADOR)
        domains = domains.exclude(default_role=Role.ADMINISTRADOR)
        emails = emails.exclude(default_role=Role.ADMINISTRADOR)
    return render(request, 'accounts/access_admin.html', {
        'domains': domains,
        'emails': emails,
        'role_choices': role_choices_for(request.user),
        'users': Paginator(users_qs, 20).get_page(request.GET.get('page')),
        'domain_form': AllowedDomainForm(viewer=request.user, company=company),
        'email_form': AllowedEmailForm(viewer=request.user, company=company),
        'blocked': BlockedEmail.objects.filter(company=company),
        'blocked_form': BlockedEmailForm(company=company),
        'invite_form': InviteForm(viewer=request.user),
        # Solo el remitente de ESTA empresa (superuser). El SMTP es global del servidor:
        # se configura en /empresas/correo/, no acá.
        'sender_form': CompanySenderForm(instance=company) if request.user.is_superuser else None,
        'sender_effective': resolve_from_email(company) if request.user.is_superuser else None,
    })


@_company_required
@_accounts_manager_required
def user_edit(request, pk):
    target = _company_user_or_404(request, pk)
    if not _can_manage_target(request.user, target):
        raise PermissionDenied
    if request.method == 'POST':
        action = request.POST.get('action', 'save_account')
        # Los overrides individuales solo existen para roles en INDIVIDUAL_OVERRIDE_ROLES
        # (ver accounts/permissions.py) — igual se revalida acá server-side, no solo
        # ocultando la sección en el template. Editarlos es gestión de privilegios:
        # queda reservado al superuser (el coordinador solo edita nombre/rol).
        if action in ('save_permissions', 'reset_permissions'):
            if not request.user.is_superuser:
                raise PermissionDenied
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

        form = AdminUserEditForm(request.POST, instance=target, viewer=request.user)
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
        form = AdminUserEditForm(instance=target, viewer=request.user)

    target_role = get_user_role(target)
    show_overrides = target_role in INDIVIDUAL_OVERRIDE_ROLES and request.user.is_superuser
    permission_rows = []
    if show_overrides:
        overrides = {up.capability: up.enabled for up in UserPermission.objects.filter(user=target)}
        role_defaults = {
            rp.capability: rp.enabled
            for rp in RolePermission.objects.filter(company=request.company, role=target_role)
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


@_company_required
@_superuser_required
def roles_board(request):
    """Matriz rol × capacidad DE ESTA EMPRESA (cada cliente tiene la suya)."""
    roles = Role.choices  # [(value, label), ...]

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save_matrix':
            for role_value, _ in roles:
                for cap_key, _label in CAPABILITIES:
                    enabled = request.POST.get(f'{role_value}:{cap_key}') == 'on'
                    RolePermission.objects.update_or_create(
                        company=request.company, role=role_value, capability=cap_key,
                        defaults={'enabled': enabled},
                    )
            messages.success(request, 'Permisos actualizados.')
        return redirect('accounts:roles_board')

    # Matriz actual {(role, cap): enabled}
    current = {
        (rp.role, rp.capability): rp.enabled
        for rp in RolePermission.objects.filter(company=request.company)
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


@_company_required
@_superuser_required
def nextcloud_config(request):
    """Config de Nextcloud DE ESTA EMPRESA, editable solo por el superuser: dos tarjetas
    independientes — storage WebDAV (pisa a la de .env si `enabled`) y login OAuth2
    (credenciales de naturaleza distinta, ver NextcloudOAuthConfig)."""
    config = NextcloudConfig.for_company(request.company)
    oauth_config = NextcloudOAuthConfig.for_company(request.company)
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


def _send_test_email(request, data):
    """Envía un correo de prueba al superuser logueado con la config del form (sin
    guardar): SMTP propio si `enabled` + host, o el backend del settings si no —
    exactamente lo que quedaría efectivo al guardar."""
    from django.core.mail import get_connection, send_mail
    to = request.user.email
    if not to:
        messages.error(request, 'Tu cuenta no tiene email — no hay a dónde enviar la prueba.')
        return
    connection = None
    from_email = settings.DEFAULT_FROM_EMAIL
    if data['enabled'] and data['host']:
        connection = get_connection(
            'django.core.mail.backends.smtp.EmailBackend',
            host=data['host'], port=data['port'], username=data['username'],
            password=data['password'], use_tls=data['use_tls'],
            timeout=getattr(settings, 'EMAIL_TIMEOUT', 10),
        )
        from_email = data['from_email'] or from_email
    try:
        send_mail(
            'Kanban: correo de prueba',
            'Si estás leyendo esto, la configuración de correo saliente funciona.',
            from_email, [to], connection=connection, fail_silently=False,
        )
        messages.success(request, f'Correo de prueba enviado a {to}.')
    except Exception as exc:
        messages.error(request, f'No se pudo enviar el correo de prueba: {exc}')


def _smtp_cert_names(host, port, use_tls):
    """(nombres del certificado, nombre con que se identifica el servidor). Valida la
    cadena pero NO el nombre — para sugerir el host correcto cuando el certificado es de
    otro nombre (típico en hosting compartido: mail.dominio → premiumNNN.web-hosting.com)."""
    import smtplib
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    try:
        conn = smtplib.SMTP(host, port, timeout=10)
        try:
            _code, banner = conn.ehlo()
            server_name = (banner or b'').decode(errors='replace').split()[0] if banner else ''
            if use_tls:
                conn.starttls(context=ctx)
            cert = conn.sock.getpeercert() or {}
        finally:
            conn.close()
        return [v for k, v in cert.get('subjectAltName', ()) if k == 'DNS'], server_name
    except Exception:
        return [], ''


def _verify_smtp(request, data):
    """Verifica la configuración SMTP SIN enviar ningún correo: conecta, negocia el
    cifrado, y autentica. Usa lo que está en el formulario (si `enabled` + host) o, si
    no, el SMTP del .env — lo mismo que quedaría en uso. Cada fallo se traduce a un
    mensaje con la causa probable y cómo corregirla."""
    import smtplib
    import socket
    import ssl

    if data['enabled'] and data['host']:
        origen = 'del formulario'
        host, port, user = data['host'], data['port'], data['username']
        password, use_tls = data['password'], data['use_tls']
    elif getattr(settings, 'EMAIL_HOST', ''):
        origen = 'del .env del servidor'
        host, port, user = settings.EMAIL_HOST, settings.EMAIL_PORT, settings.EMAIL_HOST_USER
        password, use_tls = settings.EMAIL_HOST_PASSWORD, settings.EMAIL_USE_TLS
    else:
        messages.info(request, 'No hay ningún SMTP configurado (ni acá ni en el .env): los correos van a la consola.')
        return

    destino = f'{host}:{port}'
    if port in (993, 143, 995, 110):
        messages.error(
            request,
            f'El puerto {port} es de IMAP/POP (recibir correo), no de SMTP. Para enviar usá el 587 con TLS.',
        )
        return
    if port == 465 and use_tls:
        messages.error(
            request,
            'El puerto 465 usa SSL directo y esta app negocia TLS por STARTTLS: usá el puerto 587 con «Usar TLS».',
        )
        return

    timeout = getattr(settings, 'EMAIL_TIMEOUT', 10)
    paso = 'conectar'
    try:
        conn = smtplib.SMTP(host, port, timeout=timeout)
        try:
            conn.ehlo()
            if use_tls:
                paso = 'negociar el cifrado TLS'
                conn.starttls(context=ssl.create_default_context())
                conn.ehlo()
            if user:
                paso = 'autenticar'
                conn.login(user, password)
        finally:
            try:
                conn.quit()
            except Exception:
                conn.close()
    except ssl.SSLCertVerificationError as exc:
        from fnmatch import fnmatch
        names, server_name = _smtp_cert_names(host, port, use_tls)
        if server_name and any(fnmatch(server_name.lower(), n.lower()) for n in names):
            # El servidor se identifica con un nombre que SÍ cubre su certificado.
            hint = f' Usá «{server_name}» como servidor SMTP (así se identifica y para ese nombre es su certificado).'
        elif names:
            hint = f' El certificado es válido para: {", ".join(names[:4])}.'
        else:
            hint = ''
        messages.error(
            request,
            f'{destino}: el certificado TLS del servidor no corresponde a «{host}».{hint} ({exc.verify_message})',
        )
    except smtplib.SMTPAuthenticationError as exc:
        messages.error(
            request,
            f'{destino}: el servidor rechazó el usuario o la contraseña de «{user}» '
            f'({exc.smtp_code}). Revisá la contraseña; con Gmail/Google Workspace tiene que ser una contraseña de aplicación.',
        )
    except smtplib.SMTPNotSupportedError as exc:
        messages.error(request, f'{destino}: el servidor no soporta lo pedido al {paso} ({exc}). Probá con/sin «Usar TLS».')
    except smtplib.SMTPServerDisconnected as exc:
        messages.error(
            request,
            f'{destino}: el servidor cortó la conexión al {paso} ({exc}). Si fue al autenticar, suele ser '
            'usuario inexistente o demasiados intentos fallidos; si fue al conectar, puerto o cifrado equivocados.',
        )
    except smtplib.SMTPException as exc:
        # OJO: las excepciones de smtplib heredan de OSError — este bloque va antes.
        messages.error(request, f'{destino}: error SMTP al {paso}: {exc}')
    except (socket.timeout, TimeoutError):
        messages.error(
            request,
            f'{destino}: sin respuesta al {paso} (timeout de {timeout}s). Suele ser el puerto equivocado '
            'o un firewall que bloquea la salida del servidor.',
        )
    except OSError as exc:
        messages.error(request, f'{destino}: no se pudo {paso} ({exc}). Revisá el nombre del servidor y el puerto.')
    else:
        detalle = f'autenticado como {user}' if user else 'sin autenticación'
        cifrado = 'con TLS' if use_tls else 'SIN cifrado'
        messages.success(
            request,
            f'Conexión SMTP correcta con {destino} ({cifrado}, {detalle}) — configuración tomada {origen}. '
            'No se envió ningún correo.',
        )


def _email_effective_source(config):
    """Qué configuración de correo saliente está en uso AHORA: la de la base (esta
    pantalla) si está activa con host, si no la del .env del servidor, y si tampoco hay
    SMTP, la consola (solo desarrollo). Para mostrarlo en la pantalla de correo."""
    if config.enabled and config.host:
        return {'source': 'db', 'label': 'Esta configuración (base de datos)',
                'host': config.host, 'port': config.port, 'user': config.username,
                'from_email': config.from_email or settings.DEFAULT_FROM_EMAIL}
    if getattr(settings, 'EMAIL_HOST', ''):
        return {'source': 'env', 'label': 'Archivo .env del servidor',
                'host': settings.EMAIL_HOST, 'port': settings.EMAIL_PORT,
                'user': settings.EMAIL_HOST_USER, 'from_email': settings.DEFAULT_FROM_EMAIL}
    return {'source': 'console', 'label': 'Consola (sin SMTP — solo desarrollo)',
            'host': '', 'port': '', 'user': '', 'from_email': settings.DEFAULT_FROM_EMAIL}


def _email_config_form(config, data=None):
    """Form de EmailConfig. Si en la base no hay servidor cargado, se precargan los
    valores SMTP del .env (host, puerto, TLS, usuario, remitente — la contraseña nunca)
    para que el superuser vea qué hay configurado y pueda copiarlo/probarlo sin
    tipearlo de nuevo. `enabled` queda apagado: probar sin activar usa el .env tal cual."""
    initial = None
    if not config.host and getattr(settings, 'EMAIL_HOST', ''):
        initial = {
            'host': settings.EMAIL_HOST, 'port': settings.EMAIL_PORT,
            'use_tls': settings.EMAIL_USE_TLS, 'username': settings.EMAIL_HOST_USER,
            'from_email': settings.DEFAULT_FROM_EMAIL,
        }
    if data is not None:
        return EmailConfigForm(data, instance=config)
    return EmailConfigForm(instance=config, initial=initial)


@_superuser_required
def email_config(request):
    """Config de correo GLOBAL (el SMTP es del servidor, no de cada empresa — el
    remitente por empresa vive en Company), editable solo por el superuser desde el
    panel /empresas/correo/: SMTP (pisa al .env si `enabled`) + qué eventos mandan
    email (los mensajes de chat arrancan apagados — un chat activo es un correo por
    mensaje)."""
    config = EmailConfig.load()
    form = _email_config_form(config)
    # `next`: la sección "Correo saliente" de Cuentas (/<slug>/acceso/admin/) postea acá
    # y quiere volver allí — tanto al guardar como tras la prueba (los messages viajan
    # en la sesión). Sin next, o con uno inválido, se queda en /empresas/correo/.
    next_url = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = ''

    if request.method == 'POST':
        form = _email_config_form(config, request.POST)
        action = request.POST.get('action')
        if action in ('test', 'verify'):
            # Ni la prueba ni la verificación guardan nada: usan los valores del form.
            if form.is_valid():
                if action == 'verify':
                    _verify_smtp(request, form.cleaned_data)
                else:
                    _send_test_email(request, form.cleaned_data)
                if next_url:
                    return redirect(next_url)
            else:
                messages.error(request, 'Revisá los datos antes de probar la configuración.')
        elif form.is_valid():
            form.save()
            messages.success(request, 'Configuración de correo actualizada.')
            return redirect(next_url or 'companies:email_config')
        else:
            messages.error(request, 'Revisá los datos.')

    return render(request, 'accounts/email_config.html', {
        'form': form, 'config': config, 'email_source': _email_effective_source(config),
    })


def branding_logo(request, variant):
    """Sirve el logo/favicon de la empresa del request. No usa la URL de MEDIA_ROOT
    porque nginx no expone `/media/` en producción (ver el comentario en `nginx.conf`);
    acá el request ya pasó por nginx `location /` hasta Django, así que sirve en
    cualquier entorno sin configuración adicional. Público (sin login): es solo la
    marca del header/login, no hay nada sensible que proteger. Si no hay logo oscuro
    propio pero sí claro, el oscuro cae al claro (mismo criterio que
    `company_branding`)."""
    company = getattr(request, 'company', None)
    if company is None or variant not in ('light', 'dark', 'favicon'):
        raise Http404
    if variant == 'favicon':
        field = company.favicon
    else:
        field = company.logo_dark if (variant == 'dark' and company.logo_dark) else company.logo_light
    if not field:
        raise Http404
    response = FileResponse(field.open('rb'))  # FileResponse adivina el content-type por la extensión
    response['Cache-Control'] = 'public, max-age=300'
    # Por si alguien abre el archivo directo: que nunca corra como documento del origen.
    response['Content-Security-Policy'] = 'sandbox'
    return response


def _hex_to_rgb(value):
    value = value.lstrip('#')
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _contrast_text(hex_color):
    """Blanco o casi-negro según la luminancia relativa (WCAG) del color de fondo —
    para `--color-primary-content` y compañía."""
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(x) for x in _hex_to_rgb(hex_color))
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return '#1A1516' if luminance > 0.5 else '#FFFFFF'


def _theme_block(selector, primary, accent):
    rules = []
    if primary:
        rules.append(f'--color-primary:{primary};--color-primary-content:{_contrast_text(primary)};')
    if accent:
        rules.append(f'--color-accent:{accent};--color-accent-content:{_contrast_text(accent)};')
    return f'{selector}{{{"".join(rules)}}}' if rules else ''


def company_theme_css(request):
    """Hoja CSS por empresa con sus colores de marca. La CSP (`style-src 'self'`) no
    permite `<style>` inline, así que los tokens se sirven como un stylesheet del mismo
    origen, cargado DESPUÉS de tailwind_css (ver templates/base.html). Sobrescribe las
    custom properties de daisyUI (`--color-primary`, `--color-accent` y sus `-content`)
    bajo `html[data-theme=...]`: todos los componentes ya leen `var(--color-*)`, así que
    el cambio se propaga solo. ETag por (empresa, updated) + cache corto."""
    company = getattr(request, 'company', None)
    if company is None:
        raise Http404
    etag = f'"{company.pk}-{company.theme_version()}"'
    if request.headers.get('If-None-Match') == etag:
        return HttpResponseNotModified()
    css = '\n'.join(filter(None, [
        '/* Colores de marca de la empresa — generado por accounts.views.company_theme_css */',
        _theme_block('html[data-theme="light"]', company.primary_color, company.accent_color),
        _theme_block(
            'html[data-theme="dark"]',
            company.primary_color_dark or company.primary_color,
            company.accent_color_dark or company.accent_color,
        ),
    ])) + '\n'
    response = HttpResponse(css, content_type='text/css; charset=utf-8')
    response['ETag'] = etag
    response['Cache-Control'] = 'public, max-age=300'
    return response


# ── Login con Nextcloud (OAuth2) ────────────────────────────────────────────────

@_company_required
def nextcloud_login(request):
    """Redirige a Nextcloud para autorizar. El usuario nunca escribe su password de
    Nextcloud acá — vuelve con un `code` que se canjea server-side en el callback.
    El `redirect_uri` lleva el prefijo de la empresa: cada cliente registra
    `https://host/<slug>/acceso/nextcloud/callback/` en su app OAuth2."""
    config = NextcloudOAuthConfig.objects.filter(company=request.company).first()
    if config is None or not (config.enabled and config.base_url and config.client_id):
        messages.error(request, 'El login con Nextcloud no está habilitado.')
        return redirect('accounts:login')

    state = secrets.token_urlsafe(32)
    request.session['nc_oauth_state'] = state
    next_url = request.GET.get('next', '')
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        request.session['nc_oauth_next'] = next_url
    # `embedded=1` llega del JS de login.html cuando detecta window.self !== window.top:
    # este request ya viene de un target="_top" (fuera del iframe), así que el callback
    # sabe que debe devolver al usuario a Nextcloud en vez de al board de SkyDesk.
    request.session['nc_oauth_embedded'] = request.GET.get('embedded') == '1'

    redirect_uri = request.build_absolute_uri(reverse('accounts:nextcloud_callback'))
    params = urlencode({
        'response_type': 'code',
        'client_id': config.client_id,
        'redirect_uri': redirect_uri,
        'state': state,
    })
    return redirect(f'{config.resolved_authorize_url()}?{params}')


@_company_required
def nextcloud_callback(request):
    """Canjea el `code` por un token, resuelve el email vía la API OCS de Nextcloud, y
    loguea (creando la cuenta si hace falta) — todo gateado por la allow-list DE LA
    EMPRESA (`is_email_allowed`/`resolve_default_role`), la misma que gobierna el
    onboarding normal por correo."""
    company = request.company
    config = NextcloudOAuthConfig.objects.filter(company=company).first()
    if config is None or not config.enabled:
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
        nc_uid = (data.get('id') or '').strip()
    except (requests.RequestException, ValueError, KeyError):
        messages.error(request, 'No se pudo completar el login con Nextcloud. Probá de nuevo.')
        return redirect('accounts:login')

    if not email:
        messages.error(request, 'Tu usuario de Nextcloud no tiene un email configurado.')
        return redirect('accounts:login')
    if not is_email_allowed(company, email):
        messages.error(request, f'Tu cuenta de Nextcloud no está habilitada para acceder a {_brand(request)}.')
        return redirect('accounts:login')

    profile_defaults = {'role': resolve_default_role(company, email), 'company': company}
    user = User.objects.filter(email__iexact=email).first()
    if user is not None:
        existing = Profile.objects.filter(user=user).first()
        if user.is_superuser or (
            existing is not None and existing.company_id and existing.company_id != company.pk
            and not is_member(user, company)
        ):
            # Un email = una cuenta: no se "roba" la cuenta desde otra empresa (salvo que
            # el superuser ya lo haya sumado como miembro adicional de esta).
            messages.error(request, 'Esa cuenta pertenece a otra empresa.')
            return redirect('accounts:login')
    if user is None:
        user = User.objects.create(username=email[:150], email=email, is_active=True)
        if display_name:
            first, _, last = display_name.partition(' ')
            user.first_name, user.last_name = first, last
        user.set_unusable_password()
        user.save()
        Profile.objects.get_or_create(user=user, defaults=profile_defaults)
    elif not user.is_active:
        # Misma defensa en profundidad que `activate`: una cuenta dada de baja (inactiva
        # PERO con password usable) no se reactiva sola por este flujo.
        if user.has_usable_password():
            messages.error(request, 'Esta cuenta fue dada de baja. Contactá al administrador.')
            return redirect('accounts:login')
        user.is_active = True
        user.save(update_fields=['is_active'])
        Profile.objects.get_or_create(user=user, defaults=profile_defaults)

    profile, _ = Profile.objects.get_or_create(user=user, defaults=profile_defaults)
    if profile.company_id is None:
        profile.company = company
        profile.save(update_fields=['company'])
    if nc_uid:
        # Se actualiza en cada login (no solo al crear la cuenta) para detectar, dentro del
        # iframe de Nextcloud, que la sesión quedó de un usuario de Nextcloud distinto al
        # que está logueado ahora ahí — ver NextcloudUidMismatchMiddleware.
        if profile.nextcloud_uid != nc_uid:
            profile.nextcloud_uid = nc_uid
            profile.save(update_fields=['nextcloud_uid'])

    login(request, user, backend='accounts.backends.EmailBackend')
    messages.success(request, f'Bienvenido/a, {user.get_full_name() or user.email}.')

    if request.session.pop('nc_oauth_embedded', False) and settings.NEXTCLOUD_RETURN_URL:
        # Login iniciado desde dentro del iframe de Nextcloud: este request ya es top-level
        # (llegó vía target="_top"), así que un redirect normal a una URL absoluta externa
        # devuelve el tab a Nextcloud. Al recargar esa página, el iframe de SkyDesk vuelve
        # a pedirse y ya lleva la cookie de sesión (SameSite=None) recién seteada.
        return redirect(settings.NEXTCLOUD_RETURN_URL)
    return redirect(next_url)


@login_required
@require_POST
def dev_impersonate(request):
    """Impersonar a un usuario real (solo superuser): guarda su id en la sesión;
    `DevImpersonationMiddleware` reemplaza `request.user` por ese usuario en cada request
    siguiente, así se ve la app con sus datos reales (tickets asignados, notificaciones).
    No existe para no-superuser — 404 directo, sin insinuar que el feature existe.

    `request.real_user` es el superuser real cuando ya se está impersonando a alguien
    (lo cuelga el middleware); se usa acá en vez de `request.user` para permitir cambiar
    de usuario impersonado sin tener que salir primero."""
    real_user = getattr(request, 'real_user', request.user)
    if not real_user.is_superuser:
        raise Http404
    user_id = request.POST.get('user_id', '')
    target = User.objects.filter(pk=user_id, is_active=True).first() if user_id else None
    if target is not None:
        request.session['impersonate_id'] = str(target.pk)
    else:
        request.session.pop('impersonate_id', None)
    next_url = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse('tickets:board')
    # Si el impersonado no opera en la empresa del request, seguirlo a su principal
    # (el middleware igual lo redirigiría, pero mejor caer directo en su tablero).
    target_company = get_user_company(target) if target is not None else None
    current = getattr(request, 'company', None)
    if target_company is not None and (current is None or not is_member(target, current)):
        next_url = company_path(target_company, 'tickets:board')
    return redirect(next_url)
