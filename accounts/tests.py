import io
import shutil
import tempfile
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from core.testing import DEFAULT_SLUG, TenantTestCase as TestCase, default_company, make_user, p

from .access import is_email_allowed, resolve_default_role
from .models import (
    AllowedDomain, AllowedEmail, BlockedEmail, Company, EmailConfig, NextcloudOAuthConfig,
    Profile, Role, RolePermission, UserPermission,
)
from .permissions import has_capability

User = get_user_model()

# Cache locmem (sesiones + rate-limit sin Redis) y estáticos sin manifest (sin collectstatic).
OV = dict(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    },
)


class AllowListTests(TestCase):
    def test_blocked_email_wins_over_allowed_domain_and_email(self):
        c = default_company()
        AllowedDomain.objects.create(company=c, domain='empresa.com')
        AllowedEmail.objects.create(company=c, email='vip@empresa.com', default_role=Role.COORDINADOR)
        BlockedEmail.objects.create(company=c, email='Ex@Empresa.com')     # se normaliza a minúsculas
        BlockedEmail.objects.create(company=c, email='vip@empresa.com')
        self.assertTrue(is_email_allowed(c, 'alguien@empresa.com'))
        self.assertFalse(is_email_allowed(c, 'ex@empresa.com'))
        self.assertFalse(is_email_allowed(c, 'EX@empresa.com'))
        self.assertFalse(is_email_allowed(c, 'vip@empresa.com'))          # bloqueo gana a la excepción
        # El bloqueo es por empresa.
        other = Company.objects.create(name='Otra', slug='otra', ticket_prefix='OTR')
        AllowedDomain.objects.create(company=other, domain='empresa.com')
        self.assertTrue(is_email_allowed(other, 'ex@empresa.com'))

    def test_allowed_and_default_role(self):
        c = default_company()
        AllowedDomain.objects.create(company=c, domain='empresa.com', default_role=Role.EXPERTO)
        AllowedEmail.objects.create(company=c, email='x@otro.com', default_role=Role.SEGUIMIENTO)
        self.assertTrue(is_email_allowed(c, 'a@empresa.com'))
        self.assertFalse(is_email_allowed(c, 'a@malo.com'))
        self.assertEqual(resolve_default_role(c, 'a@empresa.com'), Role.EXPERTO)
        self.assertEqual(resolve_default_role(c, 'x@otro.com'), Role.SEGUIMIENTO)
        self.assertEqual(resolve_default_role(c, 'a@malo.com'), Role.EJECUTOR)

    def test_allow_list_is_per_company(self):
        from .services import create_company
        c = default_company()
        other = create_company(name='Otra', slug='otra', ticket_prefix='OTRA')
        AllowedDomain.objects.create(company=other, domain='otra.com', default_role=Role.EXPERTO)
        self.assertTrue(is_email_allowed(other, 'a@otra.com'))
        self.assertFalse(is_email_allowed(c, 'a@otra.com'))
        self.assertEqual(resolve_default_role(c, 'a@otra.com'), Role.EJECUTOR)
        self.assertFalse(is_email_allowed(None, 'a@otra.com'))


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
        AllowedDomain.objects.create(company=default_company(), domain='empresa.com')

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
        AllowedDomain.objects.create(company=default_company(), domain='empresa.com', default_role=Role.EXPERTO)
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
        cfg = NextcloudConfig.for_company(default_company())
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.token, 'secreto123')

    def test_saving_with_blank_token_keeps_existing(self):
        from attachments.models import NextcloudConfig
        NextcloudConfig.objects.filter(company=default_company()).update(
            enabled=True, base_url='https://x/dav', user='u', token='original')
        self.client.force_login(self.superuser)
        self.client.post(reverse('accounts:nextcloud_config'), {
            'action': 'save', 'enabled': 'on',
            'base_url': 'https://x/dav', 'user': 'u', 'token': '', 'root': 'R',
        })
        cfg = NextcloudConfig.for_company(default_company())
        self.assertEqual(cfg.token, 'original')


@override_settings(**OV)
class AccessAdminCoordinatorTests(TestCase):
    """La página Cuentas se abre a quien tenga accounts.manage (coordinador por
    defecto), pero sin ver superusers ni nada del rol ADMINISTRADOR."""

    def _make(self, email, role):
        u = User.objects.create_user(email, email, 'ClaveReal123', is_active=True)
        Profile.objects.update_or_create(user=u, defaults={'role': role, 'company': default_company()})
        return u

    def setUp(self):
        self.coord = self._make('coord@empresa.com', Role.COORDINADOR)
        self.ejec = self._make('ej@empresa.com', Role.EJECUTOR)
        self.admin_role = self._make('espia@empresa.com', Role.ADMINISTRADOR)
        self.superuser = User.objects.create_superuser('root@empresa.com', 'root@empresa.com', 'ClaveReal123')

    def test_coordinator_can_open_accounts_page(self):
        self.client.force_login(self.coord)
        r = self.client.get(reverse('accounts:access_admin'))
        self.assertEqual(r.status_code, 200)

    def test_ejecutor_forbidden(self):
        self.client.force_login(self.ejec)
        self.assertEqual(self.client.get(reverse('accounts:access_admin')).status_code, 403)

    def test_coordinator_does_not_see_superusers_nor_administrador(self):
        self.client.force_login(self.coord)
        content = self.client.get(reverse('accounts:access_admin')).content.decode()
        self.assertNotIn('root@empresa.com', content)
        self.assertNotIn('espia@empresa.com', content)
        # Tampoco se ofrece el rol Administrador en ningún select.
        self.assertNotIn('value="ADMINISTRADOR"', content)
        self.assertIn('ej@empresa.com', content)

    def test_superuser_still_sees_everything(self):
        self.client.force_login(self.superuser)
        content = self.client.get(reverse('accounts:access_admin')).content.decode()
        self.assertIn('espia@empresa.com', content)
        self.assertIn('value="ADMINISTRADOR"', content)

    def test_coordinator_cannot_touch_hidden_targets(self):
        self.client.force_login(self.coord)
        for target in (self.superuser, self.admin_role):
            r = self.client.post(reverse('accounts:access_admin'),
                                 {'action': 'toggle_user', 'id': target.pk})
            self.assertEqual(r.status_code, 403)
            r = self.client.post(reverse('accounts:access_admin'),
                                 {'action': 'delete_user', 'id': target.pk})
            self.assertEqual(r.status_code, 403)
            self.assertEqual(self.client.get(reverse('accounts:user_edit', args=[target.pk])).status_code, 403)

    def test_coordinator_can_manage_normal_user(self):
        self.client.force_login(self.coord)
        r = self.client.post(reverse('accounts:access_admin'),
                             {'action': 'toggle_user', 'id': self.ejec.pk})
        self.assertEqual(r.status_code, 302)
        self.ejec.refresh_from_db()
        self.assertFalse(self.ejec.is_active)

    def test_block_email_then_invite_and_request_access_are_rejected(self):
        AllowedDomain.objects.create(company=default_company(), domain='empresa.com')
        self.client.force_login(self.coord)
        r = self.client.post(reverse('accounts:access_admin'), {
            'action': 'add_blocked', 'email': 'Ex@Empresa.com', 'note': 'se fue',
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(BlockedEmail.objects.filter(company=default_company(), email='ex@empresa.com').exists())
        self.assertContains(self.client.get(reverse('accounts:access_admin')), 'ex@empresa.com')
        # Invitarlo desde Cuentas no crea nada.
        self.client.post(reverse('accounts:access_admin'), {
            'action': 'invite', 'email': 'ex@empresa.com', 'role': Role.EJECUTOR,
        })
        self.assertFalse(User.objects.filter(email__iexact='ex@empresa.com').exists())
        self.assertFalse(AllowedEmail.objects.filter(email='ex@empresa.com').exists())
        # Desbloquear lo quita de la lista.
        pk = BlockedEmail.objects.get(email='ex@empresa.com').pk
        self.client.post(reverse('accounts:access_admin'), {'action': 'delete_blocked', 'id': pk})
        self.assertFalse(BlockedEmail.objects.filter(pk=pk).exists())

    def test_blocked_email_cannot_request_access(self):
        AllowedDomain.objects.create(company=default_company(), domain='empresa.com')
        BlockedEmail.objects.create(company=default_company(), email='ex@empresa.com')
        self.client.logout()
        self.client.post(reverse('accounts:request_access'), {'email': 'ex@empresa.com'})
        self.assertFalse(User.objects.filter(email__iexact='ex@empresa.com').exists())

    def test_coordinator_cannot_invite_administrador(self):
        self.client.force_login(self.coord)
        self.client.post(reverse('accounts:access_admin'), {
            'action': 'invite', 'email': 'nuevo@empresa.com', 'role': Role.ADMINISTRADOR,
        })
        self.assertFalse(AllowedEmail.objects.filter(email='nuevo@empresa.com').exists())

    def test_coordinator_cannot_assign_administrador_role(self):
        self.client.force_login(self.coord)
        r = self.client.post(reverse('accounts:user_edit', args=[self.ejec.pk]), {
            'action': 'save_account', 'first_name': 'E', 'last_name': 'J',
            'role': Role.ADMINISTRADOR,
        })
        self.assertEqual(r.status_code, 200)   # form inválido: re-render con error
        self.ejec.refresh_from_db()
        self.assertEqual(self.ejec.profile.role, Role.EJECUTOR)

    def test_coordinator_cannot_edit_permission_overrides(self):
        other = self._make('coord2@empresa.com', Role.COORDINADOR)
        self.client.force_login(self.coord)
        r = self.client.post(reverse('accounts:user_edit', args=[other.pk]),
                             {'action': 'save_permissions', 'tickets.move': 'on'})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(UserPermission.objects.filter(user=other).exists())
        # Y la sección de overrides no se le muestra.
        content = self.client.get(reverse('accounts:user_edit', args=[other.pk])).content.decode()
        self.assertNotIn('Configuración específica de esta cuenta', content)

    def test_roles_and_config_pages_remain_superuser_only(self):
        self.client.force_login(self.coord)
        for name in ('accounts:roles_board', 'accounts:nextcloud_config'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        # El SMTP global vive en el panel de empresas (sin prefijo): a un usuario de
        # empresa el middleware lo manda de vuelta a su empresa — nunca ve la página.
        self.assertNotEqual(self.client.get(reverse('companies:email_config')).status_code, 200)


@override_settings(**OV)
class EmailConfigViewTests(TestCase):
    """Solo el superuser puede ver/editar la config de correo global (companies:email_config)."""

    def setUp(self):
        self.user = User.objects.create_user('u@empresa.com', 'u@empresa.com', 'ClaveReal123', is_active=True)
        self.superuser = User.objects.create_superuser('root@empresa.com', 'root@empresa.com', 'ClaveReal123')

    def test_non_superuser_redirected(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse('companies:email_config'))
        self.assertEqual(r.status_code, 302)

    def test_superuser_can_view_and_save(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(reverse('companies:email_config')).status_code, 200)
        r = self.client.post(reverse('companies:email_config'), {
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
        self.client.post(reverse('companies:email_config'), {
            'action': 'save', 'enabled': 'on', 'host': 'smtp.x.com', 'port': 587, 'password': '',
        })
        self.assertEqual(EmailConfig.load().password, 'original')

    def test_action_test_sends_email_without_saving(self):
        # Con `enabled` apagado la prueba usa el backend del settings (locmem en tests):
        # el correo queda en mail.outbox y la config NO se guarda.
        self.client.force_login(self.superuser)
        r = self.client.post(reverse('companies:email_config'), {'action': 'test', 'port': 587})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.superuser.email, mail.outbox[0].to)
        self.assertFalse(EmailConfig.load().enabled)


def _png_bytes(color='red'):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), color).save(buf, 'PNG')
    return buf.getvalue()


_BRANDING_MEDIA_ROOT = tempfile.mkdtemp(prefix='skydesk-test-branding-')


@override_settings(MEDIA_ROOT=_BRANDING_MEDIA_ROOT, **OV)
class CompanyBrandingTests(TestCase):
    """Marca POR EMPRESA (Company.brand_name/logo_*/favicon/colores): la edita el
    superuser en /empresas/<slug>/editar/; el logo lo sirve accounts:branding_logo
    (si solo se sube el claro, el oscuro cae al mismo) y los colores salen como hoja CSS
    propia (accounts:company_theme_css) porque la CSP no permite estilos inline."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_BRANDING_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user('u@empresa.com', 'u@empresa.com', 'ClaveReal123', is_active=True)
        self.superuser = User.objects.create_superuser('root@empresa.com', 'root@empresa.com', 'ClaveReal123')
        self.edit_url = reverse('companies:edit', args=[DEFAULT_SLUG])

    def _data(self, **extra):
        c = default_company()
        data = {'name': c.name, 'slug': c.slug, 'ticket_prefix': c.ticket_prefix,
                'is_active': 'on', 'brand_name': c.brand_name}
        data.update(extra)
        return data

    def test_non_superuser_cannot_edit_company(self):
        self.client.force_login(self.user)
        self.assertNotEqual(self.client.get(self.edit_url).status_code, 200)
        self.client.post(self.edit_url, self._data(brand_name='Hackeado'))
        self.assertNotEqual(default_company().brand_name, 'Hackeado')

    def test_logo_missing_returns_404(self):
        for variant in ('light', 'dark', 'favicon'):
            self.assertEqual(self.client.get(reverse('accounts:branding_logo', args=[variant])).status_code, 404)

    def test_invalid_variant_returns_404(self):
        self.assertEqual(self.client.get(reverse('accounts:branding_logo', args=['sepia'])).status_code, 404)

    def test_logo_without_company_prefix_returns_404(self):
        from django.test import Client
        self.assertEqual(Client().get('/acceso/marca/logo/light/').status_code, 404)
        self.assertEqual(Client().get('/acceso/marca/tema.css').status_code, 404)

    def test_light_only_falls_back_for_dark(self):
        self.client.force_login(self.superuser)
        upload = SimpleUploadedFile('logo.png', _png_bytes(), content_type='image/png')
        r = self.client.post(self.edit_url, self._data(logo_light=upload))
        self.assertEqual(r.status_code, 302)

        light = self.client.get(reverse('accounts:branding_logo', args=['light']))
        dark = self.client.get(reverse('accounts:branding_logo', args=['dark']))
        self.assertEqual(light.status_code, 200)
        self.assertEqual(dark.status_code, 200)
        self.assertEqual(b''.join(dark.streaming_content), b''.join(light.streaming_content))
        self.assertTrue(default_company().logo_light.name.startswith(f'branding/{DEFAULT_SLUG}/'))

    def test_both_uploaded_serve_independently(self):
        self.client.force_login(self.superuser)
        self.client.post(self.edit_url, self._data(
            logo_light=SimpleUploadedFile('light.png', _png_bytes('red'), content_type='image/png'),
            logo_dark=SimpleUploadedFile('dark.png', _png_bytes('blue'), content_type='image/png'),
        ))
        light = self.client.get(reverse('accounts:branding_logo', args=['light']))
        dark = self.client.get(reverse('accounts:branding_logo', args=['dark']))
        self.assertNotEqual(b''.join(light.streaming_content), b''.join(dark.streaming_content))

    def test_favicon_rejects_svg(self):
        self.client.force_login(self.superuser)
        r = self.client.post(self.edit_url, self._data(
            favicon=SimpleUploadedFile('f.svg', b'<svg/>', content_type='image/svg+xml'),
        ))
        self.assertEqual(r.status_code, 200)   # form inválido, re-render
        self.assertFalse(default_company().favicon)

    def test_board_uses_default_logo_when_unconfigured(self):
        self.client.force_login(self.superuser)
        r = self.client.get(reverse('tickets:board'))
        self.assertContains(r, 'img/logo.png')
        self.assertContains(r, 'img/logo-dark.png')
        self.assertNotContains(r, 'marca/tema.css')

    def test_brand_name_shows_on_login_and_title(self):
        self.client.force_login(self.superuser)
        self.client.post(self.edit_url, self._data(brand_name='Embol Tickets'))
        self.client.logout()
        r = self.client.get(reverse('accounts:login'))
        self.assertContains(r, 'Embol Tickets')
        self.assertContains(r, '· Embol Tickets</title>')

    def test_theme_css_reflects_colors_with_contrast_and_etag(self):
        self.client.force_login(self.superuser)
        self.client.post(self.edit_url, self._data(primary_color='#123456', accent_color='#ffee00'))
        board = self.client.get(reverse('tickets:board'))
        self.assertContains(board, 'marca/tema.css')

        css_url = reverse('accounts:company_theme_css')
        r = self.client.get(css_url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'text/css; charset=utf-8')
        body = r.content.decode()
        self.assertIn('html[data-theme="light"]{--color-primary:#123456;--color-primary-content:#FFFFFF;', body)
        self.assertIn('--color-accent:#FFEE00;--color-accent-content:#1A1516;', body)
        # Sin color oscuro propio, el modo oscuro reusa el claro.
        self.assertIn('html[data-theme="dark"]{--color-primary:#123456;', body)
        # Revalidación barata por ETag.
        r304 = self.client.get(css_url, HTTP_IF_NONE_MATCH=r['ETag'])
        self.assertEqual(r304.status_code, 304)

    def test_invalid_color_rejected(self):
        self.client.force_login(self.superuser)
        r = self.client.post(self.edit_url, self._data(primary_color='rojo'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(default_company().primary_color, '')


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
        NextcloudOAuthConfig.objects.filter(company=default_company()).update(
            enabled=True, base_url='https://nube.empresa.com',
            client_id='cid', client_secret='csecret',
        )
        AllowedDomain.objects.create(company=default_company(), domain='empresa.com')

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
        self.assertRedirects(r, p(reverse('accounts:login')))

    def test_callback_invalid_state_rejected(self):
        self.client.get(reverse('accounts:nextcloud_login'))
        r = self.client.get(reverse('accounts:nextcloud_callback'), {'code': 'abc', 'state': 'bogus'})
        self.assertRedirects(r, p(reverse('accounts:login')))
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
        self.assertRedirects(r, p(reverse('accounts:login')))
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
        self.assertRedirects(r, p(reverse('accounts:login')))
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
        self.user = make_user('user@empresa.com', password='RealPass123')
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
    """Impersonar usuario real: activo en todo entorno (no solo DEBUG), gateado solo por
    superuser. Una vez activa, `request.user` pasa a ser realmente ese usuario (sus
    tickets, su rol, sus capacidades) — no un rol simulado sin datos."""

    def setUp(self):
        self.superuser = User.objects.create_superuser('root@empresa.com', 'root@empresa.com', 'x')
        self.other = User.objects.create_user('u@empresa.com', 'u@empresa.com', 'x', is_active=True)
        self.ejecutor = User.objects.create_user('ej@empresa.com', 'ej@empresa.com', 'x', is_active=True)
        Profile.objects.update_or_create(user=self.ejecutor, defaults={'role': Role.EJECUTOR, 'company': default_company()})

        from tickets.models import Assignment, Ticket
        self.ticket = Ticket.objects.create(company=default_company(), title='Ticket de ej', reporter=self.superuser)
        Assignment.objects.create(ticket=self.ticket, user=self.ejecutor, kind=Assignment.Kind.EJECUTOR)

    @override_settings(**OV)
    def test_non_superuser_cannot_impersonate(self):
        self.client.force_login(self.other)
        r = self.client.post(reverse('accounts:dev_impersonate'), {'user_id': self.ejecutor.pk})
        self.assertEqual(r.status_code, 404)

    @override_settings(**OV)   # DEBUG=False (default forzado por el test runner): prueba el caso de producción
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

    @override_settings(**OV)
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
        Profile.objects.update_or_create(user=self.coord, defaults={'role': Role.COORDINADOR, 'company': default_company()})
        self.other_coord = User.objects.create_user('c2@empresa.com', 'c2@empresa.com', 'x', is_active=True)
        Profile.objects.update_or_create(user=self.other_coord, defaults={'role': Role.COORDINADOR, 'company': default_company()})
        RolePermission.objects.update_or_create(
            company=default_company(), role=Role.COORDINADOR, capability='tickets.view_all', defaults={'enabled': True},
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
            company=default_company(), role=Role.COORDINADOR, capability='tickets.edit_any', defaults={'enabled': False},
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
        Profile.objects.update_or_create(user=self.coord, defaults={'role': Role.COORDINADOR, 'company': default_company()})
        self.ejecutor = User.objects.create_user('ej@empresa.com', 'ej@empresa.com', 'x', is_active=True)
        Profile.objects.update_or_create(user=self.ejecutor, defaults={'role': Role.EJECUTOR, 'company': default_company()})
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


class SuperuserOnlyAdminTests(TestCase):
    """Empresas, SMTP y pertenencia a empresas (Profile) en el admin de Django: solo
    superuser, aunque una cuenta staff tenga todos los permisos de modelo."""

    def test_staff_with_model_perms_is_locked_out(self):
        from django.contrib import admin
        from django.contrib.auth.models import Permission
        from django.test import RequestFactory

        staff = make_user('staff@embol.com', Role.COORDINADOR)
        staff.is_staff = True
        staff.save(update_fields=['is_staff'])
        staff.user_permissions.set(Permission.objects.filter(content_type__app_label='accounts'))
        staff = User.objects.get(pk=staff.pk)  # sin cache de permisos
        root = User.objects.create_superuser('root@embol.com', 'root@embol.com', 'ClaveReal123')

        for model in (Company, EmailConfig, Profile):
            model_admin = admin.site._registry[model]
            for user, expected in ((staff, False), (root, True)):
                request = RequestFactory().get('/')
                request.user = user
                self.assertEqual(model_admin.has_module_permission(request), expected, model)
                self.assertEqual(model_admin.has_view_permission(request), expected, model)
                self.assertEqual(model_admin.has_add_permission(request), expected, model)
                self.assertEqual(model_admin.has_change_permission(request), expected, model)
                self.assertEqual(model_admin.has_delete_permission(request), expected, model)


@override_settings(**OV)
class CompanyLoginScopeTests(TestCase):
    """El login/reset de `/<slug>/` solo acepta miembros (o superuser)."""

    def setUp(self):
        self.other = Company.objects.create(name='Otra', slug='otra', ticket_prefix='OTR')

    def _login(self, email, password='ClaveReal123'):
        return self.client.post(reverse('accounts:login'), {'username': email, 'password': password})

    def test_main_member_logs_in(self):
        make_user('m@empresa.com', password='ClaveReal123')
        self.assertEqual(self._login('m@empresa.com').status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_extra_company_member_logs_in(self):
        make_user('x@empresa.com', password='ClaveReal123', company=self.other,
                  extra_companies=[self.company])
        self.assertEqual(self._login('x@empresa.com').status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_other_company_user_is_rejected(self):
        make_user('o@otra.com', password='ClaveReal123', company=self.other)
        r = self._login('o@otra.com')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertContains(r, 'no pertenece a')
        self.assertContains(r, '/otra/acceso/login/')

    def test_wrong_password_gives_generic_error(self):
        make_user('o@otra.com', password='ClaveReal123', company=self.other)
        r = self._login('o@otra.com', password='mala')
        self.assertNotContains(r, 'no pertenece a')

    def test_superuser_logs_in_any_company(self):
        User.objects.create_superuser('root@x.com', 'root@x.com', 'ClaveReal123')
        self.assertEqual(self._login('root@x.com').status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_reset_skips_users_of_other_company(self):
        make_user('o@otra.com', company=self.other)
        r = self.client.post(reverse('accounts:password_reset'), {'email': 'o@otra.com'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_sends_to_member(self):
        make_user('m@empresa.com')
        self.client.post(reverse('accounts:password_reset'), {'email': 'm@empresa.com'})
        self.assertEqual(len(mail.outbox), 1)
