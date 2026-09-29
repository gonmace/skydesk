"""Multi-empresa: aislamiento entre empresas, reglas del middleware de prefijo,
correlativos por empresa, panel del superuser y helpers de URL."""
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import get_script_prefix, reverse

from attachments.models import NextcloudConfig
from core.testing import DEFAULT_SLUG, TenantClient, TenantTestCase, default_company, make_user, p
from tickets.forms import TicketForm
from tickets.models import Label, Project, Ticket

from .models import Company, NextcloudOAuthConfig, Profile, Role, RolePermission, UserPermission
from .permissions import CAPABILITY_KEYS, has_capability, users_with_capability
from .services import create_company
from .tenancy import company_path, company_url, get_company_by_slug

User = get_user_model()

OV = dict(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    ATTACHMENT_DEFAULT_BACKEND='memory',
    ATTACHMENT_BACKENDS={'memory': {'BACKEND': 'attachments.backends.memory.MemoryBackend', 'OPTIONS': {}}},
    STORAGES={
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    },
)


def demo_company():
    return create_company(name='Demo S.A.', slug='demo', ticket_prefix='DEMO', brand_name='Demo')


class DemoClient(TenantClient):
    slug = 'demo'


# ── Middleware ────────────────────────────────────────────────────────────────

@override_settings(**OV)
class CompanyMiddlewareTests(TestCase):
    """Rutas con y sin prefijo: quién entra dónde (ver accounts/tenancy.py)."""

    def setUp(self):
        self.embol = default_company()
        self.demo = demo_company()
        self.coord = make_user('coord@embol.com', Role.COORDINADOR)
        self.superuser = User.objects.create_superuser('root@x.com', 'root@x.com', 'x')
        self.client = Client()   # sin prefijo automático: acá probamos las rutas crudas

    def test_anonymous_root_redirects_to_generic_login(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.startswith('/acceso/login/'))

    def test_company_user_without_prefix_is_redirected_to_own_company(self):
        self.client.force_login(self.coord)
        r = self.client.get('/mis-tickets/?sort=vence')
        self.assertRedirects(r, '/embol/mis-tickets/?sort=vence', fetch_redirect_response=False)
        # POST sin prefijo no se redirige (perdería el body): 403.
        self.assertEqual(self.client.post('/mover/', {}).status_code, 403)

    def test_company_user_in_other_company_gets_403(self):
        self.client.force_login(self.coord)
        self.assertEqual(self.client.get('/demo/').status_code, 403)
        self.assertEqual(self.client.get('/demo/acceso/login/').status_code, 403)
        self.assertEqual(self.client.get('/embol/').status_code, 200)

    def test_superuser_root_goes_to_companies_panel_and_can_enter_any(self):
        self.client.force_login(self.superuser)
        self.assertRedirects(self.client.get('/'), reverse('companies:list'), fetch_redirect_response=False)
        self.assertEqual(self.client.get('/embol/').status_code, 200)
        self.assertEqual(self.client.get('/demo/').status_code, 200)
        self.assertEqual(self.client.get(reverse('companies:list')).status_code, 200)

    def test_unknown_slug_is_a_plain_404(self):
        self.assertEqual(self.client.get('/nope/').status_code, 404)
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get('/nope/').status_code, 404)

    def test_inactive_company(self):
        self.demo.is_active = False
        self.demo.save()
        self.assertEqual(self.client.get('/demo/acceso/login/').status_code, 404)   # anónimo: no existe
        demo_user = make_user('u@demo.com', company=self.demo)
        self.client.force_login(demo_user)
        r = self.client.get('/demo/')
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, 'desactivada', status_code=403)
        # El superuser sí entra (para administrarla).
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get('/demo/').status_code, 200)

    def test_user_without_company_is_forbidden_everywhere_but_can_log_out(self):
        orphan = User.objects.create_user('o@x.com', 'o@x.com', 'x', is_active=True)
        self.client.force_login(orphan)
        self.assertEqual(self.client.get('/embol/').status_code, 403)
        self.assertEqual(self.client.get('/').status_code, 403)
        self.assertEqual(self.client.post('/acceso/logout/').status_code, 302)

    def test_links_are_prefixed_and_script_prefix_is_restored(self):
        self.client.force_login(self.coord)
        r = self.client.get('/embol/')
        self.assertContains(r, 'href="/embol/mis-tickets/"')
        self.assertContains(r, 'action="/embol/acceso/logout/"')
        # El middleware restaura el prefijo al terminar: reverse() fuera del request sigue limpio.
        self.assertEqual(get_script_prefix(), '/')
        self.assertEqual(reverse('tickets:board'), '/')

    def test_login_required_redirects_to_prefixed_login_with_prefixed_next(self):
        r = self.client.get('/embol/mis-tickets/')
        self.assertRedirects(r, '/embol/acceso/login/?next=/embol/mis-tickets/', fetch_redirect_response=False)

    def test_append_slash_keeps_prefix(self):
        self.client.force_login(self.coord)
        r = self.client.get('/embol/mis-tickets')
        self.assertEqual(r.status_code, 301)
        self.assertTrue(r.url.endswith('/embol/mis-tickets/'))

    def test_reserved_and_invalid_slugs_are_rejected(self):
        for slug in ('acceso', 'empresas', 'static', 'admin', 'nuevo', 'proyectos', '123', 'Mayus', 'x'):
            with self.assertRaises(ValidationError, msg=slug):
                Company(name='X', slug=slug, ticket_prefix='XX').full_clean()
        Company(name='Ok', slug='ok-empresa', ticket_prefix='OK').full_clean()

    def test_slug_lookup_is_cached_and_invalidated_on_save(self):
        self.assertEqual(get_company_by_slug('demo').pk, self.demo.pk)
        self.assertIsNone(get_company_by_slug('cambiado'))
        self.demo.slug = 'cambiado'
        self.demo.save()
        self.assertIsNone(get_company_by_slug('demo'))
        self.assertEqual(get_company_by_slug('cambiado').pk, self.demo.pk)
        self.assertIsNone(get_company_by_slug('../etc'))   # formato inválido: ni consulta


# ── Aislamiento de datos ──────────────────────────────────────────────────────

@override_settings(**OV)
class IsolationTests(TenantTestCase):
    """Nada de una empresa se ve, se lista ni se puede tocar desde otra."""

    def setUp(self):
        self.embol = default_company()
        self.demo = demo_company()
        self.coord = make_user('coord@embol.com', Role.COORDINADOR)
        self.ej = make_user('ej@embol.com', Role.EJECUTOR)
        self.demo_coord = make_user('coord@demo.com', Role.COORDINADOR, company=self.demo)
        self.demo_ej = make_user('ej@demo.com', Role.EJECUTOR, company=self.demo)
        self.demo_project = Project.objects.create(company=self.demo, name='Secreto', code='SEC')
        self.demo_label = Label.objects.create(company=self.demo, name='secreta')
        self.demo_ticket = Ticket.objects.create(title='Ticket secreto de demo', reporter=self.demo_coord)
        self.embol_ticket = Ticket.objects.create(title='Ticket de embol', reporter=self.coord)

    def test_board_and_lists_only_show_own_company(self):
        self.client.force_login(self.coord)
        for name in ('tickets:board', 'tickets:seguimiento', 'tickets:archived', 'tickets:my_tickets'):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)
            self.assertNotContains(r, 'Ticket secreto de demo', msg_prefix=name)
        board = self.client.get(reverse('tickets:board'))
        self.assertContains(board, 'Ticket de embol')
        self.assertNotContains(board, 'ej@demo.com')   # select de filtro por asignado
        self.assertNotContains(board, 'Secreto')       # select de filtro por proyecto

    def test_foreign_ticket_by_pk_is_404_even_with_view_all(self):
        self.client.force_login(self.coord)
        pk = self.demo_ticket.pk
        self.assertEqual(self.client.get(reverse('tickets:detail', args=[pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('tickets:edit', args=[pk])).status_code, 404)
        for name in ('tickets:approve', 'tickets:reject', 'tickets:suspend', 'tickets:derive',
                     'tickets:divide', 'tickets:archive', 'tickets:unarchive'):
            r = self.client.post(reverse(name, args=[pk]), {'feedback': 'x'})
            self.assertEqual(r.status_code, 404, name)
        self.demo_ticket.refresh_from_db()
        self.assertIsNone(self.demo_ticket.suspended_at)

    def test_ticket_form_offers_only_own_company_options(self):
        form = TicketForm(company=self.embol, user=self.coord)
        self.assertNotIn(self.demo_project, form.fields['project'].queryset)
        self.assertNotIn(self.demo_label, form.fields['labels'].queryset)
        self.assertNotIn(self.demo_ej, form.fields['executors'].queryset)
        self.assertIn(self.ej, form.fields['executors'].queryset)
        # Y el POST tampoco acepta ids ajenos.
        form = TicketForm({
            'title': 'x', 'solicitante': 's', 'priority': 'MEDIUM',
            'project': self.demo_project.pk, 'executors': [self.demo_ej.pk],
        }, company=self.embol, user=self.coord)
        self.assertFalse(form.is_valid())
        self.assertIn('project', form.errors)
        self.assertIn('executors', form.errors)

    def test_created_ticket_belongs_to_request_company(self):
        self.client.force_login(self.coord)
        r = self.client.post(reverse('tickets:create'), {
            'title': 'Nuevo', 'solicitante': 'Alguien', 'priority': 'MEDIUM',
        })
        self.assertEqual(r.status_code, 302)
        t = Ticket.objects.get(title='Nuevo')
        self.assertEqual(t.company, self.embol)
        self.assertTrue(t.code.startswith('EMBOL-'))

    def test_users_with_capability_is_scoped(self):
        closers = users_with_capability(self.embol, 'tickets.close')
        self.assertIn(self.coord, closers)
        self.assertNotIn(self.demo_coord, closers)
        self.assertFalse(users_with_capability(None, 'tickets.close').exists())

    def test_role_matrix_is_independent_per_company(self):
        self.assertTrue(has_capability(self.demo_coord, 'tickets.close'))
        RolePermission.objects.filter(company=self.demo, role=Role.COORDINADOR,
                                      capability='tickets.close').update(enabled=False)
        fresh_demo = User.objects.get(pk=self.demo_coord.pk)
        fresh_embol = User.objects.get(pk=self.coord.pk)
        self.assertFalse(has_capability(fresh_demo, 'tickets.close'))
        self.assertTrue(has_capability(fresh_embol, 'tickets.close'))

    def test_roles_board_edits_only_current_company(self):
        superuser = User.objects.create_superuser('root@x.com', 'root@x.com', 'x')
        demo_client = DemoClient()
        demo_client.force_login(superuser)
        data = {'action': 'save_matrix'}   # todo apagado para demo
        self.assertEqual(demo_client.post(reverse('accounts:roles_board'), data).status_code, 302)
        self.assertFalse(RolePermission.objects.filter(company=self.demo, enabled=True).exists())
        self.assertTrue(RolePermission.objects.filter(company=self.embol, enabled=True).exists())

    def test_accounts_page_lists_only_own_users(self):
        self.client.force_login(self.coord)
        content = self.client.get(reverse('accounts:access_admin')).content.decode()
        self.assertIn('ej@embol.com', content)
        self.assertNotIn('ej@demo.com', content)
        self.assertEqual(self.client.get(reverse('accounts:user_edit', args=[self.demo_ej.pk])).status_code, 404)
        r = self.client.post(reverse('accounts:access_admin'), {'action': 'toggle_user', 'id': self.demo_ej.pk})
        self.assertEqual(r.status_code, 404)
        self.demo_ej.refresh_from_db()
        self.assertTrue(self.demo_ej.is_active)

    def test_invite_email_from_other_company_is_rejected(self):
        self.client.force_login(self.coord)
        self.client.post(reverse('accounts:access_admin'), {
            'action': 'invite', 'email': 'ej@demo.com', 'role': Role.EJECUTOR,
        })
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Profile.objects.get(user=self.demo_ej).company, self.demo)

    def test_request_access_needs_company_prefix_and_own_allow_list(self):
        from .models import AllowedDomain
        AllowedDomain.objects.create(company=self.demo, domain='solo-demo.com')
        # Sin prefijo no hay a qué empresa pedir acceso.
        self.assertEqual(Client().post('/acceso/solicitar/', {'email': 'a@solo-demo.com'}).status_code, 404)
        # Con el prefijo de embol, el dominio de demo no está habilitado: mensaje neutro, sin mail.
        self.client.post(reverse('accounts:request_access'), {'email': 'a@solo-demo.com'})
        self.assertEqual(len(mail.outbox), 0)
        DemoClient().post(reverse('accounts:request_access'), {'email': 'a@solo-demo.com'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/demo/acceso/activar/', mail.outbox[0].body)
        self.assertIn('Demo', mail.outbox[0].subject)

    def test_projects_and_labels_are_per_company(self):
        self.client.force_login(self.coord)
        self.assertNotContains(self.client.get(reverse('tickets:projects')), 'Secreto')
        self.assertNotContains(self.client.get(reverse('tickets:labels')), 'secreta')
        # Mismo código de proyecto en dos empresas: válido.
        r = self.client.post(reverse('tickets:projects'), {'action': 'add', 'name': 'Mío', 'code': 'SEC', 'status': 'ACTIVE'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Project.objects.filter(code='SEC').count(), 2)
        # Borrar el proyecto ajeno por id: 404.
        r = self.client.post(reverse('tickets:projects'), {'action': 'delete', 'id': self.demo_project.pk})
        self.assertEqual(r.status_code, 404)
        self.assertTrue(Project.objects.filter(pk=self.demo_project.pk).exists())

    def test_dashboard_counts_only_own_company(self):
        for _ in range(3):
            Ticket.objects.create(title='demo extra', reporter=self.demo_coord)
        self.client.force_login(self.coord)
        r = self.client.get(reverse('tickets:dashboard'))
        self.assertEqual(r.status_code, 200)
        kpis = {k['label']: k['count'] for k in r.context['kpis']}
        self.assertEqual(kpis['Activos'], 1)

    def test_impersonating_user_of_other_company_follows_them(self):
        superuser = User.objects.create_superuser('root@x.com', 'root@x.com', 'x')
        self.client.force_login(superuser)
        r = self.client.post(reverse('accounts:dev_impersonate'), {'user_id': self.demo_ej.pk, 'next': '/'})
        self.assertRedirects(r, '/demo/', fetch_redirect_response=False)
        # Ya impersonando a alguien de demo, /embol/ lo manda a /demo/ (no 403).
        r = self.client.get(reverse('tickets:board'))
        self.assertRedirects(r, '/demo/', fetch_redirect_response=False)


# ── Correlativos ──────────────────────────────────────────────────────────────

class TicketCodeTests(TestCase):
    def setUp(self):
        self.embol = default_company()
        self.demo = demo_company()
        self.coord = make_user('coord@embol.com', Role.COORDINADOR)
        self.demo_coord = make_user('coord@demo.com', Role.COORDINADOR, company=self.demo)

    def test_sequences_are_independent_and_use_company_prefix(self):
        t1 = Ticket.objects.create(title='a', reporter=self.coord)
        d1 = Ticket.objects.create(title='b', reporter=self.demo_coord)
        t2 = Ticket.objects.create(title='c', reporter=self.coord)
        self.assertEqual((t1.code, t2.code), ('EMBOL-0001', 'EMBOL-0002'))
        self.assertEqual(d1.code, 'DEMO-0001')
        child = d1.create_child(title='hijo', reporter=self.demo_coord)
        self.assertEqual(child.code, 'DEMO-0001-1')
        self.assertEqual(child.company, self.demo)

    def test_changing_prefix_keeps_sequence(self):
        Ticket.objects.create(title='a', reporter=self.demo_coord)
        self.demo.ticket_prefix = 'ACME'
        self.demo.save()
        t = Ticket.objects.create(title='b', reporter=self.demo_coord)
        self.assertEqual(t.code, 'ACME-0002')

    def test_ticket_without_company_or_reporter_is_rejected(self):
        with self.assertRaises(ValueError):
            Ticket.objects.create(title='huérfano')

    def test_company_comes_from_parent_before_reporter(self):
        parent = Ticket.objects.create(title='p', reporter=self.demo_coord)
        child = Ticket(title='c', parent=parent, reporter=self.coord)   # reporter de OTRA empresa
        child.save()
        self.assertEqual(child.company, self.demo)


# ── Servicios y URLs ──────────────────────────────────────────────────────────

class CreateCompanyServiceTests(TestCase):
    def test_creates_matrix_and_configs_from_defaults(self):
        c = create_company(name='Nueva', slug='nueva', ticket_prefix='NUEVA')
        self.assertEqual(RolePermission.objects.filter(company=c).count(), len(Role.values) * len(CAPABILITY_KEYS))
        self.assertTrue(RolePermission.objects.get(company=c, role=Role.COORDINADOR, capability='tickets.close').enabled)
        self.assertFalse(RolePermission.objects.get(company=c, role=Role.EJECUTOR, capability='tickets.close').enabled)
        self.assertTrue(NextcloudConfig.objects.filter(company=c).exists())
        self.assertTrue(NextcloudOAuthConfig.objects.filter(company=c).exists())

    def test_template_copies_current_matrix_of_other_company(self):
        embol = default_company()
        RolePermission.objects.filter(company=embol, role=Role.EJECUTOR, capability='tickets.close').update(enabled=True)
        c = create_company(name='Copia', slug='copia', ticket_prefix='COPIA', template=embol)
        self.assertTrue(RolePermission.objects.get(company=c, role=Role.EJECUTOR, capability='tickets.close').enabled)

    def test_invalid_data_is_rejected_atomically(self):
        with self.assertRaises(ValidationError):
            create_company(name='Mal', slug='acceso', ticket_prefix='MAL')
        self.assertFalse(Company.objects.filter(name='Mal').exists())

    def test_prefix_and_slug_unique(self):
        with self.assertRaises(ValidationError):
            create_company(name='Dup', slug='dup', ticket_prefix=default_company().ticket_prefix)


@override_settings(SITE_URL='https://sky.example.com')
class CompanyUrlTests(TestCase):
    def test_company_path_and_url_outside_request(self):
        c = default_company()
        self.assertEqual(company_path(c, 'tickets:detail', 5), '/embol/5/')
        self.assertEqual(company_path(c, 'tickets:board'), '/embol/')
        self.assertEqual(company_url(c, 'accounts:login'), 'https://sky.example.com/embol/acceso/login/')
        self.assertEqual(reverse('tickets:board'), '/')   # no quedó prefijo colgado


# ── Panel de empresas ─────────────────────────────────────────────────────────

@override_settings(**OV)
class CompanyPanelTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser('root@x.com', 'root@x.com', 'x')
        self.coord = make_user('coord@embol.com', Role.COORDINADOR)
        self.client = Client()

    def test_only_superuser(self):
        self.client.force_login(self.coord)
        self.assertNotEqual(self.client.get(reverse('companies:list')).status_code, 200)
        self.assertNotEqual(self.client.get(reverse('companies:create')).status_code, 200)

    def test_create_company_from_panel(self):
        self.client.force_login(self.superuser)
        r = self.client.post(reverse('companies:create'), {
            'name': 'Acme S.A.', 'slug': 'acme', 'ticket_prefix': 'acme', 'is_active': 'on',
            'brand_name': 'Acme', 'primary_color': '#00aa00',
        })
        self.assertRedirects(r, reverse('companies:list'), fetch_redirect_response=False)
        c = Company.objects.get(slug='acme')
        self.assertEqual(c.ticket_prefix, 'ACME')       # normalizado a mayúsculas
        self.assertEqual(c.primary_color, '#00AA00')
        self.assertTrue(RolePermission.objects.filter(company=c).exists())
        self.assertTrue(NextcloudConfig.objects.filter(company=c).exists())
        # La lista la muestra y se puede entrar.
        self.assertContains(self.client.get(reverse('companies:list')), '/acme/')
        self.assertEqual(self.client.get('/acme/').status_code, 200)
        self.assertContains(self.client.get('/acme/acceso/login/'), 'Acme')

    def test_reserved_slug_shows_form_error(self):
        self.client.force_login(self.superuser)
        r = self.client.post(reverse('companies:create'), {
            'name': 'X', 'slug': 'acceso', 'ticket_prefix': 'XX', 'is_active': 'on', 'brand_name': 'X',
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'coincide con una ruta')
        self.assertFalse(Company.objects.filter(slug='acceso').exists())

    def test_superuser_nav_shows_companies_and_company_tabs_only_inside(self):
        self.client.force_login(self.superuser)
        panel = self.client.get(reverse('companies:list'))
        self.assertContains(panel, 'Empresas')
        self.assertNotContains(panel, 'Mis tickets')
        inside = self.client.get('/embol/')
        self.assertContains(inside, 'Mis tickets')
        self.assertContains(inside, reverse('companies:edit', args=[DEFAULT_SLUG]))


# ── Miembros adicionales (usuario en más de una empresa) ─────────────────────

@override_settings(**OV)
class ExtraMembershipTests(TestCase):
    """Un usuario tiene una empresa principal y puede operar en otras (mismo rol) si el
    superuser lo suma en /empresas/<slug>/editar/ — ver accounts.tenancy.is_member."""

    def setUp(self):
        self.embol = default_company()
        self.demo = demo_company()
        self.superuser = User.objects.create_superuser('root@x.com', 'root@x.com', 'x')
        # Coordinador de embol que TAMBIÉN opera en demo.
        self.multi = make_user('multi@embol.com', Role.COORDINADOR, extra_companies=[self.demo])
        self.embol_only = make_user('solo@embol.com', Role.EJECUTOR)
        self.demo_coord = make_user('coord@demo.com', Role.COORDINADOR, company=self.demo)
        self.client = Client()

    def test_member_enters_both_companies_non_member_still_403(self):
        self.client.force_login(self.multi)
        self.assertEqual(self.client.get('/embol/').status_code, 200)
        self.assertEqual(self.client.get('/demo/').status_code, 200)
        self.client.force_login(self.embol_only)
        self.assertEqual(self.client.get('/embol/').status_code, 200)
        self.assertEqual(self.client.get('/demo/').status_code, 403)

    def test_root_redirects_to_main_company(self):
        self.client.force_login(self.multi)
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.startswith('/embol/'), r.url)

    def test_capabilities_follow_active_company_matrix(self):
        # En demo los coordinadores NO pueden crear tickets; en embol sí (default).
        RolePermission.objects.filter(
            company=self.demo, role=Role.COORDINADOR, capability='tickets.create').update(enabled=False)
        self.client.force_login(self.multi)
        self.assertEqual(self.client.get('/embol/nuevo/').status_code, 200)
        self.assertEqual(self.client.get('/demo/nuevo/').status_code, 403)

    def test_selector_only_for_multi_company_users(self):
        self.client.force_login(self.multi)
        r = self.client.get('/embol/')
        self.assertContains(r, 'Cambiar de empresa')
        self.assertContains(r, '/demo/')
        self.client.force_login(self.embol_only)
        self.assertNotContains(self.client.get('/embol/'), 'Cambiar de empresa')

    def test_listed_as_member_in_demo_accounts_and_assignee_dropdowns(self):
        self.client.force_login(self.demo_coord)
        accounts_page = self.client.get('/demo/acceso/admin/')
        self.assertContains(accounts_page, 'multi@embol.com')
        self.assertNotContains(accounts_page, 'solo@embol.com')
        form = TicketForm(company=self.demo, user=self.demo_coord)
        emails = set(form.fields['executors'].queryset.values_list('email', flat=True))
        self.assertIn('multi@embol.com', emails)
        self.assertNotIn('solo@embol.com', emails)
        # Y recibe las notificaciones de "quien puede X" en demo.
        self.assertIn(self.multi, users_with_capability(self.demo, 'tickets.assign'))
        self.assertIn(self.multi, users_with_capability(self.embol, 'tickets.assign'))

    def test_demo_coord_can_edit_extra_member_role_but_not_outsider(self):
        self.client.force_login(self.demo_coord)
        self.assertEqual(self.client.get(f'/demo/acceso/cuenta/{self.multi.pk}/').status_code, 200)
        self.assertEqual(self.client.get(f'/demo/acceso/cuenta/{self.embol_only.pk}/').status_code, 404)

    def test_panel_add_and_remove_membership(self):
        self.client.force_login(self.superuser)
        r = self.client.post(reverse('companies:member_add', args=['demo']), {'email': 'SOLO@embol.com'})
        self.assertRedirects(r, reverse('companies:edit', args=['demo']), fetch_redirect_response=False)
        self.embol_only.refresh_from_db()
        self.assertTrue(self.embol_only.profile.extra_companies.filter(pk=self.demo.pk).exists())
        page = self.client.get(reverse('companies:edit', args=['demo']))
        self.assertContains(page, 'solo@embol.com')
        r = self.client.post(reverse('companies:member_remove', args=['demo', self.embol_only.pk]))
        self.assertRedirects(r, reverse('companies:edit', args=['demo']), fetch_redirect_response=False)
        self.assertFalse(self.embol_only.profile.extra_companies.exists())

    def test_panel_rejects_unknown_superuser_and_main_company(self):
        self.client.force_login(self.superuser)
        for email in ('nadie@x.com', 'root@x.com', 'coord@demo.com'):
            self.client.post(reverse('companies:member_add', args=['demo']), {'email': email})
        self.assertFalse(Profile.objects.filter(extra_companies=self.demo).exclude(user=self.multi).exists())

    def test_panel_is_superuser_only(self):
        self.client.force_login(self.demo_coord)
        r = self.client.post(reverse('companies:member_add', args=['demo']), {'email': 'solo@embol.com'})
        self.assertNotEqual(r.status_code, 302)
        self.assertFalse(self.embol_only.profile.extra_companies.exists())

    def test_remove_blocked_while_assigned_in_that_company(self):
        from tickets.models import Assignment
        ticket = Ticket.objects.create(title='Demo con multi', reporter=self.demo_coord)
        Assignment.objects.create(ticket=ticket, user=self.multi, kind=Assignment.Kind.EJECUTOR)
        self.client.force_login(self.superuser)
        self.client.post(reverse('companies:member_remove', args=['demo', self.multi.pk]))
        self.assertTrue(self.multi.profile.extra_companies.filter(pk=self.demo.pk).exists())

    def test_notification_from_other_company_opens_with_its_prefix(self):
        from notifications.models import Notification
        ticket = Ticket.objects.create(title='Aviso demo', reporter=self.demo_coord)
        n = Notification.objects.create(recipient=self.multi, actor=self.demo_coord, verb='x', ticket=ticket)
        self.client.force_login(self.multi)
        r = self.client.get(f'/embol/notificaciones/{n.pk}/abrir/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, f'/demo/{ticket.pk}/')

    def test_invite_existing_member_from_demo_only_updates_role(self):
        self.client.force_login(self.demo_coord)
        self.client.post('/demo/acceso/admin/', {
            'action': 'invite', 'email': 'multi@embol.com', 'role': Role.EJECUTOR,
        })
        self.multi.profile.refresh_from_db()
        self.assertEqual(self.multi.profile.company, self.embol)     # la principal no cambia
        self.assertEqual(self.multi.profile.role, Role.EJECUTOR)

    def test_impersonated_member_stays_in_current_company(self):
        self.client.force_login(self.superuser)
        r = self.client.post('/demo/acceso/dev/impersonar/', {'user_id': self.multi.pk, 'next': '/demo/'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.startswith('/demo/'), r.url)
        self.assertEqual(self.client.get('/demo/').status_code, 200)
