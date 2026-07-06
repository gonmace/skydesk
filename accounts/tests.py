from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .access import is_email_allowed, resolve_default_role
from .models import (
    AllowedDomain, AllowedEmail, EmailConfig, NextcloudOAuthConfig, Profile, Role,
    RolePermission, UserPermission,
)
from .permissions import has_capability

User = get_user_model()

# Middleware real + el de impersonación (que en settings.py solo se agrega si DEBUG ya
# era True al arrancar el proceso — acá lo sumamos explícitamente para poder probarlo sin
# depender de con qué DEBUG arrancó el test runner). Se excluye BrowserReloadMiddleware:
# manage.py test fuerza DEBUG=False para toda la corrida (setup_test_environment), así que
# las urls de django_browser_reload (registradas condicionalmente en core/urls.py, ya
# importado para entonces) no existen — dejarlo en la cadena rompería cualquier response.
_IMPERSONATE_MW = 'accounts.middleware.DevImpersonationMiddleware'
_BROWSER_RELOAD_MW = 'django_browser_reload.middleware.BrowserReloadMiddleware'
MIDDLEWARE_WITH_IMPERSONATION = [m for m in settings.MIDDLEWARE if m != _BROWSER_RELOAD_MW]
if _IMPERSONATE_MW not in MIDDLEWARE_WITH_IMPERSONATION:
    MIDDLEWARE_WITH_IMPERSONATION.append(_IMPERSONATE_MW)

# Cache locmem (sesiones + rate-limit sin Redis) y estáticos sin manifest (sin collectstatic).
OV = dict(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    },
)


class AllowListTests(TestCase):
    def test_allowed_and_default_role(self):
        AllowedDomain.objects.create(domain='empresa.com', default_role=Role.EXPERTO)
        AllowedEmail.objects.create(email='x@otro.com', default_role=Role.SEGUIMIENTO)
        self.assertTrue(is_email_allowed('a@empresa.com'))
        self.assertFalse(is_email_allowed('a@malo.com'))
        self.assertEqual(resolve_default_role('a@empresa.com'), Role.EXPERTO)
        self.assertEqual(resolve_default_role('x@otro.com'), Role.SEGUIMIENTO)
        self.assertEqual(resolve_default_role('a@malo.com'), Role.EJECUTOR)


@override_settings(**OV)
class LogoutTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user('u@empresa.com', 'u@empresa.com', 'ClaveReal123', is_active=True)

    def test_logout_requires_post(self):
        self.client.force_login(self.u)
        self.assertEqual(self.client.get(reverse('accounts:logout')).status_code, 405)
        r = self.client.post(reverse('accounts:logout'))
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)


@override_settings(**OV)
class RequestAccessTests(TestCase):
    def setUp(self):
        AllowedDomain.objects.create(domain='empresa.com')

    def test_new_email_sends_invite(self):
        self.client.post(reverse('accounts:request_access'), {'email': 'nuevo@empresa.com'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(User.objects.filter(email='nuevo@empresa.com', is_active=False).exists())

    def test_disallowed_no_send_no_user(self):
        self.client.post(reverse('accounts:request_access'), {'email': 'x@malo.com'})
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(User.objects.filter(email='x@malo.com').exists())

    def test_banned_user_cannot_reactivate(self):
        User.objects.create_user('ban@empresa.com', 'ban@empresa.com', 'RealPass123', is_active=False)
        self.client.post(reverse('accounts:request_access'), {'email': 'ban@empresa.com'})
        self.assertEqual(len(mail.outbox), 0)

    def test_email_cooldown(self):
        self.client.post(reverse('accounts:request_access'), {'email': 'a@empresa.com'})
        self.client.post(reverse('accounts:request_access'), {'email': 'a@empresa.com'})
        self.assertEqual(len(mail.outbox), 1)


@override_settings(**OV)
class ActivateTests(TestCase):
    def _link(self, user):
        return reverse('accounts:activate', args=[
            urlsafe_base64_encode(force_bytes(user.pk)),
            default_token_generator.make_token(user),
        ])

    def test_activation_sets_role_and_logs_in(self):
        AllowedDomain.objects.create(domain='empresa.com', default_role=Role.EXPERTO)
        u = User.objects.create(username='n@empresa.com', email='n@empresa.com', is_active=False)
        u.set_unusable_password()
        u.save()
        r = self.client.post(self._link(u), {
            'first_name': 'Juan', 'last_name': 'Pérez',
            'new_password1': 'ClaveSegura123', 'new_password2': 'ClaveSegura123',
        })
        self.assertEqual(r.status_code, 302)
        u.refresh_from_db()
        self.assertTrue(u.is_active)
        self.assertEqual(u.get_full_name(), 'Juan Pérez')
        self.assertEqual(u.profile.role, Role.EXPERTO)
        self.assertIn('_auth_user_id', self.client.session)

    def test_banned_user_cannot_self_activate(self):
        u = User.objects.create_user('ban@empresa.com', 'ban@empresa.com', 'RealPass123', is_active=False)
        r = self.client.get(self._link(u))
        self.assertContains(r, 'inválido')


@override_settings(**OV)
class NextcloudConfigViewTests(TestCase):
    """Solo el superuser puede ver/editar la config de Nextcloud (accounts:nextcloud_config)."""

    def setUp(self):
        self.user = User.objects.create_user('u@empresa.com', 'u@empresa.com', 'ClaveReal123', is_active=True)
        self.superuser = User.objects.create_superuser('root@empresa.com', 'root@empresa.com', 'ClaveReal123')

    def test_non_superuser_redirected(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse('accounts:nextcloud_config'))
        self.assertEqual(r.status_code, 302)

    def test_superuser_can_view_and_save(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(reverse('accounts:nextcloud_config')).status_code, 200)
        r = self.client.post(reverse('accounts:nextcloud_config'), {
            'action': 'save', 'enabled': 'on',
            'base_url': 'https://nube.empresa.com/dav', 'user': 'bot', 'token': 'secreto123', 'root': 'R',
        })
        self.assertEqual(r.status_code, 302)
        from attachments.models import NextcloudConfig
        cfg = NextcloudConfig.load()
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.token, 'secreto123')

    def test_saving_with_blank_token_keeps_existing(self):
        from attachments.models import NextcloudConfig
        NextcloudConfig.objects.create(pk=1, enabled=True, base_url='https://x/dav', user='u', token='original')
        self.client.force_login(self.superuser)
        self.client.post(reverse('accounts:nextcloud_config'), {
            'action': 'save', 'enabled': 'on',
            'base_url': 'https://x/dav', 'user': 'u', 'token': '', 'root': 'R',
        })
        cfg = NextcloudConfig.load()
        self.assertEqual(cfg.token, 'original')


@override_settings(**OV)
class EmailConfigViewTests(TestCase):
    """Solo el superuser puede ver/editar la config de correo (accounts:email_config)."""

    def setUp(self):
        self.user = User.objects.create_user('u@empresa.com', 'u@empresa.com', 'ClaveReal123', is_active=True)
        self.superuser = User.objects.create_superuser('root@empresa.com', 'root@empresa.com', 'ClaveReal123')

    def test_non_superuser_redirected(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse('accounts:email_config'))
        self.assertEqual(r.status_code, 302)

    def test_superuser_can_view_and_save(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(reverse('accounts:email_config')).status_code, 200)
        r = self.client.post(reverse('accounts:email_config'), {
            'action': 'save', 'enabled': 'on', 'host': 'smtp.empresa.com', 'port': 465,
            'username': 'bot@empresa.com', 'password': 'secreto123',
            'from_email': 'SkyDesk <noreply@empresa.com>', 'notify_comment': 'on',
        })
        self.assertEqual(r.status_code, 302)
        cfg = EmailConfig.load()
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.host, 'smtp.empresa.com')
        self.assertEqual(cfg.port, 465)
        self.assertEqual(cfg.password, 'secreto123')
        self.assertFalse(cfg.use_tls)          # checkbox apagado en el POST
        self.assertFalse(cfg.notify_assignment)
        self.assertTrue(cfg.notify_comment)

    def test_saving_with_blank_password_keeps_existing(self):
        EmailConfig.objects.create(pk=1, enabled=True, host='smtp.x.com', password='original')
        self.client.force_login(self.superuser)
        self.client.post(reverse('accounts:email_config'), {
            'action': 'save', 'enabled': 'on', 'host': 'smtp.x.com', 'port': 587, 'password': '',
        })
        self.assertEqual(EmailConfig.load().password, 'original')

    def test_action_test_sends_email_without_saving(self):
        # Con `enabled` apagado la prueba usa el backend del settings (locmem en tests):
        # el correo queda en mail.outbox y la config NO se guarda.
        self.client.force_login(self.superuser)
        r = self.client.post(reverse('accounts:email_config'), {'action': 'test', 'port': 587})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.superuser.email, mail.outbox[0].to)
        self.assertFalse(EmailConfig.load().enabled)


@override_settings(**OV)
class SendMailAsyncTests(TestCase):
    """core.mail.send_mail_async: inline con locmem (tests), thread daemon en runtime."""

    def test_locmem_sends_inline(self):
        from core.mail import send_mail_async
        send_mail_async('Asunto', 'Cuerpo', ['a@empresa.com'])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, 'Asunto')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend')
    def test_non_locmem_spawns_daemon_thread(self):
        from core.mail import send_mail_async
        with patch('core.mail.threading.Thread') as thread_cls:
            send_mail_async('Asunto', 'Cuerpo', ['a@empresa.com'])
        thread_cls.assert_called_once()
        self.assertTrue(thread_cls.call_args.kwargs['daemon'])
        thread_cls.return_value.start.assert_called_once()

    def test_connection_from_config_when_enabled(self):
        from core.mail import get_mail_connection
        self.assertIsNone(get_mail_connection())   # sin config -> backend del settings
        EmailConfig.objects.create(
            pk=1, enabled=True, host='smtp.x.com', port=465, use_tls=False,
            username='bot', password='s3cret',
        )
        conn = get_mail_connection()
        self.assertIsNotNone(conn)
        self.assertEqual(conn.host, 'smtp.x.com')
        self.assertEqual(conn.port, 465)
        self.assertEqual(conn.username, 'bot')
        self.assertFalse(conn.use_tls)


@override_settings(**OV)
class NextcloudLoginTests(TestCase):
    """Login vía OAuth2 con Nextcloud: gateado por la allow-list existente, sin backend
    de auth nuevo (reusa EmailBackend) y sin tocar django-axes (no hay authenticate() con
    password de por medio)."""

    def setUp(self):
        NextcloudOAuthConfig.objects.create(
            pk=1, enabled=True, base_url='https://nube.empresa.com',
            client_id='cid', client_secret='csecret',
        )
        AllowedDomain.objects.create(domain='empresa.com')

    def _token_and_userinfo_mocks(self, email='nuevo@empresa.com', displayname='Nuevo Usuario', uid=''):
        token_resp = Mock(status_code=200)
        token_resp.raise_for_status = Mock()
        token_resp.json.return_value = {'access_token': 'tok123'}
        info_resp = Mock(status_code=200)
        info_resp.raise_for_status = Mock()
        info_resp.json.return_value = {'ocs': {'data': {'email': email, 'displayname': displayname, 'id': uid}}}
        return token_resp, info_resp

    def test_login_view_redirects_to_authorize_with_state(self):
        r = self.client.get(reverse('accounts:nextcloud_login'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('nube.empresa.com/index.php/apps/oauth2/authorize', r.url)
        self.assertIn('client_id=cid', r.url)
        self.assertIn('nc_oauth_state', self.client.session)

    def test_login_view_disabled_redirects_to_login(self):
        NextcloudOAuthConfig.objects.update(enabled=False)
        r = self.client.get(reverse('accounts:nextcloud_login'))
        self.assertRedirects(r, reverse('accounts:login'))

    def test_callback_invalid_state_rejected(self):
        self.client.get(reverse('accounts:nextcloud_login'))
        r = self.client.get(reverse('accounts:nextcloud_callback'), {'code': 'abc', 'state': 'bogus'})
        self.assertRedirects(r, reverse('accounts:login'))
        self.assertNotIn('_auth_user_id', self.client.session)

    @patch('accounts.views.requests.get')
    @patch('accounts.views.requests.post')
    def test_callback_success_creates_user_and_logs_in(self, mock_post, mock_get):
        self.client.get(reverse('accounts:nextcloud_login'))
        state = self.client.session['nc_oauth_state']
        mock_post.return_value, mock_get.return_value = self._token_and_userinfo_mocks()

        r = self.client.get(reverse('accounts:nextcloud_callback'), {'code': 'abc', 'state': state})
        self.assertEqual(r.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

        user = User.objects.get(email='nuevo@empresa.com')
        self.assertTrue(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.first_name, 'Nuevo')
        self.assertEqual(user.profile.role, Role.EJECUTOR)

    @patch('accounts.views.requests.get')
    @patch('accounts.views.requests.post')
    def test_callback_email_not_allowed_blocked(self, mock_post, mock_get):
        self.client.get(reverse('accounts:nextcloud_login'))
        state = self.client.session['nc_oauth_state']
        mock_post.return_value, mock_get.return_value = self._token_and_userinfo_mocks(email='x@malo.com')

        r = self.client.get(reverse('accounts:nextcloud_callback'), {'code': 'abc', 'state': state})
        self.assertRedirects(r, reverse('accounts:login'))
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertFalse(User.objects.filter(email='x@malo.com').exists())

    @patch('accounts.views.requests.get')
    @patch('accounts.views.requests.post')
    def test_callback_inactive_user_with_password_blocked(self, mock_post, mock_get):
        User.objects.create_user('ban@empresa.com', 'ban@empresa.com', 'RealPass123', is_active=False)
        self.client.get(reverse('accounts:nextcloud_login'))
        state = self.client.session['nc_oauth_state']
        mock_post.return_value, mock_get.return_value = self._token_and_userinfo_mocks(email='ban@empresa.com')

        r = self.client.get(reverse('accounts:nextcloud_callback'), {'code': 'abc', 'state': state})
        self.assertRedirects(r, reverse('accounts:login'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_callback_disabled_config_404(self):
        NextcloudOAuthConfig.objects.update(enabled=False)
        r = self.client.get(reverse('accounts:nextcloud_callback'), {'code': 'abc', 'state': 'x'})
        self.assertEqual(r.status_code, 404)

    @override_settings(NEXTCLOUD_RETURN_URL='https://sky.empresa.com/apps/external/1')
    @patch('accounts.views.requests.get')
    @patch('accounts.views.requests.post')
    def test_callback_embedded_redirects_to_nextcloud_return_url(self, mock_post, mock_get):
        # Simula el login iniciado desde dentro del iframe (target="_top", ?embedded=1):
        # el callback debe devolver el tab a Nextcloud en vez de al board de SkyDesk.
        self.client.get(reverse('accounts:nextcloud_login'), {'embedded': '1'})
        state = self.client.session['nc_oauth_state']
        mock_post.return_value, mock_get.return_value = self._token_and_userinfo_mocks()

        r = self.client.get(reverse('accounts:nextcloud_callback'), {'code': 'abc', 'state': state})
        self.assertRedirects(r, 'https://sky.empresa.com/apps/external/1', fetch_redirect_response=False)
        self.assertIn('_auth_user_id', self.client.session)

    @patch('accounts.views.requests.get')
    @patch('accounts.views.requests.post')
    def test_callback_saves_nextcloud_uid_to_profile(self, mock_post, mock_get):
        self.client.get(reverse('accounts:nextcloud_login'))
        state = self.client.session['nc_oauth_state']
        mock_post.return_value, mock_get.return_value = self._token_and_userinfo_mocks(uid='nuevo.nc')

        self.client.get(reverse('accounts:nextcloud_callback'), {'code': 'abc', 'state': state})
        user = User.objects.get(email='nuevo@empresa.com')
        self.assertEqual(user.profile.nextcloud_uid, 'nuevo.nc')


class NextcloudUidMismatchMiddlewareTests(TestCase):
    """Si la URL del iframe trae ?nc_uid=<otro> distinto al de la sesión activa (guardado en
    el login vía Profile.nextcloud_uid), la sesión de SkyDesk se cierra — evita que quede
    logueado el usuario anterior al cambiar de cuenta en Nextcloud sin recargar SkyDesk."""

    def setUp(self):
        self.user = User.objects.create_user('user@empresa.com', 'user@empresa.com', 'RealPass123')
        Profile.objects.filter(user=self.user).update(nextcloud_uid='user.nc')
        self.client.force_login(self.user)

    def test_mismatched_nc_uid_logs_out(self):
        r = self.client.get(reverse('tickets:board'), {'nc_uid': 'otro.nc'})
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(r.status_code, 302)  # login_required redirige tras el logout

    def test_matching_nc_uid_keeps_session(self):
        self.client.get(reverse('tickets:board'), {'nc_uid': 'user.nc'})
        self.assertIn('_auth_user_id', self.client.session)

    def test_no_nc_uid_param_keeps_session(self):
        self.client.get(reverse('tickets:board'))
        self.assertIn('_auth_user_id', self.client.session)


class DevImpersonationTests(TestCase):
    """Impersonar usuario dev: no existe fuera de DEBUG ni para no-superuser; una vez
    activa, `request.user` pasa a ser realmente ese usuario (sus tickets, su rol, sus
    capacidades) — no un rol simulado sin datos."""

    def setUp(self):
        self.superuser = User.objects.create_superuser('root@empresa.com', 'root@empresa.com', 'x')
        self.other = User.objects.create_user('u@empresa.com', 'u@empresa.com', 'x', is_active=True)
        self.ejecutor = User.objects.create_user('ej@empresa.com', 'ej@empresa.com', 'x', is_active=True)
        Profile.objects.update_or_create(user=self.ejecutor, defaults={'role': Role.EJECUTOR})

        from tickets.models import Assignment, Ticket
        self.ticket = Ticket.objects.create(title='Ticket de ej', reporter=self.superuser)
        Assignment.objects.create(ticket=self.ticket, user=self.ejecutor, kind=Assignment.Kind.EJECUTOR)

    @override_settings(**OV)   # la página 404 default también renderiza {% static %}
    def test_disabled_without_debug(self):
        # DEBUG=False es lo que corre por defecto en tests (Django lo fuerza así), así que
        # esto ya prueba el caso real de producción sin necesidad de override.
        self.client.force_login(self.superuser)
        r = self.client.post(reverse('accounts:dev_impersonate'), {'user_id': self.ejecutor.pk})
        self.assertEqual(r.status_code, 404)

    @override_settings(DEBUG=True, MIDDLEWARE=MIDDLEWARE_WITH_IMPERSONATION, **OV)
    def test_non_superuser_cannot_impersonate(self):
        self.client.force_login(self.other)
        r = self.client.post(reverse('accounts:dev_impersonate'), {'user_id': self.ejecutor.pk})
        self.assertEqual(r.status_code, 404)

    @override_settings(DEBUG=True, MIDDLEWARE=MIDDLEWARE_WITH_IMPERSONATION, **OV)
    def test_superuser_impersonates_and_sees_real_data(self):
        self.client.force_login(self.superuser)
        # Sin impersonar: el superuser ve el dashboard (bypassa todos los checks).
        self.assertEqual(self.client.get(reverse('tickets:dashboard')).status_code, 200)

        r = self.client.post(reverse('accounts:dev_impersonate'), {'user_id': self.ejecutor.pk, 'next': '/'})
        self.assertEqual(r.status_code, 302)

        # Impersonando al Ejecutor real: dashboard.view no está en su capacidad → 403.
        self.assertEqual(self.client.get(reverse('tickets:dashboard')).status_code, 403)
        board = self.client.get(reverse('tickets:board'))
        self.assertNotContains(board, 'Cuentas')      # nav de superuser oculta mientras impersona
        self.assertContains(board, 'Ticket de ej')    # ve SU ticket real, no uno vacío

    @override_settings(DEBUG=True, MIDDLEWARE=MIDDLEWARE_WITH_IMPERSONATION, **OV)
    def test_clearing_impersonation_restores_superuser_view(self):
        self.client.force_login(self.superuser)
        self.client.post(reverse('accounts:dev_impersonate'), {'user_id': self.ejecutor.pk})
        self.assertEqual(self.client.get(reverse('tickets:dashboard')).status_code, 403)

        self.client.post(reverse('accounts:dev_impersonate'), {'user_id': ''})
        self.assertEqual(self.client.get(reverse('tickets:dashboard')).status_code, 200)


class UserPermissionOverrideTests(TestCase):
    """has_capability(): un override individual (UserPermission) pisa el default del
    rol (RolePermission) para ese usuario puntual, sin afectar al resto del rol."""

    def setUp(self):
        self.coord = User.objects.create_user('coord@empresa.com', 'coord@empresa.com', 'x', is_active=True)
        Profile.objects.update_or_create(user=self.coord, defaults={'role': Role.COORDINADOR})
        self.other_coord = User.objects.create_user('c2@empresa.com', 'c2@empresa.com', 'x', is_active=True)
        Profile.objects.update_or_create(user=self.other_coord, defaults={'role': Role.COORDINADOR})
        RolePermission.objects.update_or_create(
            role=Role.COORDINADOR, capability='tickets.view_all', defaults={'enabled': True},
        )

    def test_no_override_falls_back_to_role_default(self):
        self.assertTrue(has_capability(self.coord, 'tickets.view_all'))

    def test_override_false_beats_role_default_true(self):
        UserPermission.objects.create(user=self.coord, capability='tickets.view_all', enabled=False)
        self.assertFalse(has_capability(self.coord, 'tickets.view_all'))
        # No afecta a otro usuario con el mismo rol.
        self.assertTrue(has_capability(self.other_coord, 'tickets.view_all'))

    def test_override_true_beats_role_default_false(self):
        RolePermission.objects.update_or_create(
            role=Role.COORDINADOR, capability='tickets.edit_any', defaults={'enabled': False},
        )
        UserPermission.objects.create(user=self.coord, capability='tickets.edit_any', enabled=True)
        self.assertTrue(has_capability(self.coord, 'tickets.edit_any'))
        self.assertFalse(has_capability(self.other_coord, 'tickets.edit_any'))


@override_settings(**OV)
class UserEditPermissionOverrideViewTests(TestCase):
    """Sección de overrides individuales en accounts:user_edit: visible solo para
    Coordinador/Seguimiento, guarda/resetea UserPermission, y se limpia si el rol
    de la cuenta cambia a uno no elegible."""

    def setUp(self):
        self.superuser = User.objects.create_superuser('root@empresa.com', 'root@empresa.com', 'x')
        self.coord = User.objects.create_user('coord@empresa.com', 'coord@empresa.com', 'x', is_active=True)
        Profile.objects.update_or_create(user=self.coord, defaults={'role': Role.COORDINADOR})
        self.ejecutor = User.objects.create_user('ej@empresa.com', 'ej@empresa.com', 'x', is_active=True)
        Profile.objects.update_or_create(user=self.ejecutor, defaults={'role': Role.EJECUTOR})
        self.client.force_login(self.superuser)

    def test_shows_overrides_section_for_coordinador(self):
        r = self.client.get(reverse('accounts:user_edit', args=[self.coord.pk]))
        self.assertContains(r, 'Configuración específica de esta cuenta')

    def test_hides_overrides_section_for_ejecutor(self):
        r = self.client.get(reverse('accounts:user_edit', args=[self.ejecutor.pk]))
        self.assertNotContains(r, 'Configuración específica de esta cuenta')

    def test_save_permissions_creates_override_for_eligible_role(self):
        self.client.post(reverse('accounts:user_edit', args=[self.coord.pk]), {
            'action': 'save_permissions', 'tickets.view_all': 'on',
        })
        override = UserPermission.objects.get(user=self.coord, capability='tickets.view_all')
        self.assertTrue(override.enabled)
        self.assertFalse(
            UserPermission.objects.filter(user=self.coord, capability='tickets.edit_any').get().enabled
        )

    def test_save_permissions_rejected_for_ineligible_role(self):
        self.client.post(reverse('accounts:user_edit', args=[self.ejecutor.pk]), {
            'action': 'save_permissions', 'tickets.view_all': 'on',
        })
        self.assertFalse(UserPermission.objects.filter(user=self.ejecutor).exists())

    def test_reset_permissions_clears_overrides(self):
        UserPermission.objects.create(user=self.coord, capability='tickets.view_all', enabled=False)
        self.client.post(reverse('accounts:user_edit', args=[self.coord.pk]), {'action': 'reset_permissions'})
        self.assertFalse(UserPermission.objects.filter(user=self.coord).exists())

    def test_changing_role_away_from_eligible_clears_overrides(self):
        UserPermission.objects.create(user=self.coord, capability='tickets.view_all', enabled=False)
        self.client.post(reverse('accounts:user_edit', args=[self.coord.pk]), {
            'first_name': 'Coord', 'last_name': 'Uno', 'role': Role.EJECUTOR.value,
        })
        self.assertFalse(UserPermission.objects.filter(user=self.coord).exists())
