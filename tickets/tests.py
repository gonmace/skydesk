import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import EmailConfig, Profile, Role
from attachments import services
from attachments.backends.memory import MemoryBackend
from notifications.models import Notification

from .models import Assignment, Comment, Label, Project, Ticket, TicketEvent

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


def make_user(email, role):
    u = User.objects.create_user(email, email, 'x', is_active=True)
    Profile.objects.update_or_create(user=u, defaults={'role': role})
    return u


@override_settings(**OV)
class BoardVisibilityTests(TestCase):
    def setUp(self):
        self.ej = make_user('ej@e.com', Role.EJECUTOR)
        self.sup = make_user('sup@e.com', Role.EXPERTO)
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        mine = Ticket.objects.create(title='MINE', reporter=self.ej)
        Assignment.objects.create(ticket=mine, user=self.ej, kind=Assignment.Kind.EJECUTOR)
        mine.recompute_status()   # como en la app real (_sync_assignments): BACKLOG -> TODO
        other = Ticket.objects.create(title='OTHER', reporter=self.sup)
        Assignment.objects.create(ticket=other, user=self.sup, kind=Assignment.Kind.EJECUTOR)
        other.recompute_status()

    def test_ejecutor_sees_only_own(self):
        self.client.force_login(self.ej)
        r = self.client.get(reverse('tickets:board'))
        self.assertContains(r, 'MINE')
        self.assertNotContains(r, 'OTHER')

    def test_experto_sees_only_own(self):
        # Experto ya no tiene tickets.view_all: solo ve los tickets en los que participa.
        self.client.force_login(self.sup)
        r = self.client.get(reverse('tickets:board'))
        self.assertContains(r, 'OTHER')
        self.assertNotContains(r, 'MINE')

    def test_coordinador_sees_all(self):
        self.client.force_login(self.coord)
        r = self.client.get(reverse('tickets:board'))
        self.assertContains(r, 'MINE')
        self.assertContains(r, 'OTHER')


@override_settings(**OV)
class BacklogColumnVisibilityTests(TestCase):
    """Solo quien puede asignar (Coordinador) ve la columna "Entrada" (BACKLOG) —
    a Ejecutor/Experto/Seguimiento les aporta ruido, no la ven."""

    def test_coordinador_sees_entrada(self):
        self.client.force_login(make_user('coord@e.com', Role.COORDINADOR))
        r = self.client.get(reverse('tickets:board'))
        self.assertContains(r, 'data-status="BACKLOG"')

    def test_experto_does_not_see_entrada(self):
        self.client.force_login(make_user('exp@e.com', Role.EXPERTO))
        r = self.client.get(reverse('tickets:board'))
        self.assertNotContains(r, 'data-status="BACKLOG"')

    def test_seguimiento_does_not_see_entrada(self):
        self.client.force_login(make_user('seg@e.com', Role.SEGUIMIENTO))
        r = self.client.get(reverse('tickets:board'))
        self.assertNotContains(r, 'data-status="BACKLOG"')

    def test_ejecutor_does_not_see_entrada(self):
        self.client.force_login(make_user('ej@e.com', Role.EJECUTOR))
        r = self.client.get(reverse('tickets:board'))
        self.assertNotContains(r, 'data-status="BACKLOG"')


@override_settings(**OV)
class WaitingColumnVisibilityTests(TestCase):
    """Solo Coordinador y Seguimiento (`tickets.view_waiting`) ven la columna
    "Suspendido/Cancelado" — a Experto y Ejecutor no les aporta."""

    def test_coordinador_sees_suspendido(self):
        self.client.force_login(make_user('coord@e.com', Role.COORDINADOR))
        r = self.client.get(reverse('tickets:board'))
        self.assertContains(r, 'Suspendido/Cancelado')

    def test_seguimiento_sees_suspendido(self):
        self.client.force_login(make_user('seg@e.com', Role.SEGUIMIENTO))
        r = self.client.get(reverse('tickets:board'))
        self.assertContains(r, 'Suspendido/Cancelado')

    def test_experto_does_not_see_suspendido(self):
        self.client.force_login(make_user('exp@e.com', Role.EXPERTO))
        r = self.client.get(reverse('tickets:board'))
        self.assertNotContains(r, 'Suspendido/Cancelado')

    def test_ejecutor_does_not_see_suspendido(self):
        self.client.force_login(make_user('ej@e.com', Role.EJECUTOR))
        r = self.client.get(reverse('tickets:board'))
        self.assertNotContains(r, 'Suspendido/Cancelado')


@override_settings(**OV)
class ExpertoRestrictedVisibilityTests(TestCase):
    """Experto perdió tickets.view_all y chat.view_all: solo ve/abre los tickets en los
    que participa, y ya no tiene acceso a la vista global de Seguimiento."""

    def setUp(self):
        self.exp = make_user('exp@e.com', Role.EXPERTO)
        other_reporter = make_user('otro@e.com', Role.EJECUTOR)
        self.mine = Ticket.objects.create(title='DEL EXPERTO', reporter=self.exp)
        self.ajeno = Ticket.objects.create(title='AJENO', reporter=other_reporter)

    def test_cannot_open_detail_of_unrelated_ticket(self):
        self.client.force_login(self.exp)
        self.assertEqual(self.client.get(reverse('tickets:detail', args=[self.mine.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('tickets:detail', args=[self.ajeno.pk])).status_code, 403)

    def test_seguimiento_page_forbidden(self):
        self.client.force_login(self.exp)
        self.assertEqual(self.client.get(reverse('tickets:seguimiento')).status_code, 403)

    def test_dashboard_still_allowed(self):
        # dashboard.view no cambió — no es una lista de tickets.
        self.client.force_login(self.exp)
        self.assertEqual(self.client.get(reverse('tickets:dashboard')).status_code, 200)


@override_settings(**OV)
class CoordinadorOwnFirstMutedRestTests(TestCase):
    """Coordinador ve todos los tickets, pero los propios (reporter o participante)
    aparecen primero y el resto se marca como "apagado" (data-muted + opacity-50)."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        other_reporter = make_user('otro@e.com', Role.EJECUTOR)
        self.propio = Ticket.objects.create(title='PROPIO', reporter=self.coord, status=Ticket.Status.TODO)
        self.ajeno = Ticket.objects.create(title='AJENO', reporter=other_reporter, status=Ticket.Status.TODO)

    def test_propio_primero_y_ajeno_apagado(self):
        self.client.force_login(self.coord)
        r = self.client.get(reverse('tickets:board'))
        content = r.content.decode()
        self.assertLess(content.index('PROPIO'), content.index('AJENO'))

        # Ventana de atributos del tag de apertura de cada card — no depender del orden
        # exacto de atributos (puede cambiar si se agregan otros como data-priority).
        propio_i = content.index(f'data-ticket-id="{self.propio.pk}"')
        ajeno_i = content.index(f'data-ticket-id="{self.ajeno.pk}"')
        propio_tag = content[propio_i:propio_i + 300]
        ajeno_tag = content[ajeno_i:ajeno_i + 300]

        self.assertIn('data-status="TODO"', propio_tag)
        self.assertNotIn('data-muted="1"', propio_tag)
        self.assertIn('data-status="TODO"', ajeno_tag)
        self.assertIn('data-muted="1"', ajeno_tag)


@override_settings(**OV)
class SeguimientoSeesAllUnstyledTests(TestCase):
    """Seguimiento ve todo por igual: sin reordenar por participación ni marcar cards."""

    def test_no_muted_marker_for_anyone(self):
        seg = make_user('seg@e.com', Role.SEGUIMIENTO)
        other_reporter = make_user('otro@e.com', Role.EJECUTOR)
        Ticket.objects.create(title='PROPIO', reporter=seg, status=Ticket.Status.TODO)
        Ticket.objects.create(title='AJENO', reporter=other_reporter, status=Ticket.Status.TODO)
        self.client.force_login(seg)
        r = self.client.get(reverse('tickets:board'))
        self.assertContains(r, 'PROPIO')
        self.assertContains(r, 'AJENO')
        self.assertNotContains(r, 'data-muted')


@override_settings(**OV)
class SubproductCoordinatorBoardTests(TestCase):
    """En el tablero del coordinador (y Experto/Seguimiento, que comparten el mismo
    tablero por ticket), un ticket con subproductos se muestra como cards por
    subticket — igual que ve el propio ejecutor — en vez de una sola card agregada.
    Así, si un ejecutor ya concluyó pero el otro no, el coordinador ve esa parte en
    Concluido en lugar de que todo el ticket quede encallado en En progreso."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.dev1 = make_user('d1@e.com', Role.EJECUTOR)
        self.dev2 = make_user('d2@e.com', Role.EJECUTOR)
        self.mixed = Ticket.objects.create(title='Mixto', reporter=self.coord, has_subproducts=True)
        Assignment.objects.create(ticket=self.mixed, user=self.dev1, kind=Assignment.Kind.EJECUTOR,
                                   status=Ticket.Status.IN_PROGRESS)
        Assignment.objects.create(ticket=self.mixed, user=self.dev2, kind=Assignment.Kind.EJECUTOR,
                                   status=Ticket.Status.TODO)
        self.mixed.recompute_status()   # BACKLOG -> IN_PROGRESS (como en la app real)
        self.aligned = Ticket.objects.create(title='Alineado', reporter=self.coord, has_subproducts=True)
        Assignment.objects.create(ticket=self.aligned, user=self.dev1, kind=Assignment.Kind.EJECUTOR,
                                   status=Ticket.Status.TODO)
        Assignment.objects.create(ticket=self.aligned, user=self.dev2, kind=Assignment.Kind.EJECUTOR,
                                   status=Ticket.Status.TODO)
        self.aligned.recompute_status()   # BACKLOG -> TODO

    def _cards(self, content, ticket):
        cards = []
        start = 0
        needle = f'data-ticket-id="{ticket.pk}"'
        while True:
            i = content.find(needle, start)
            if i < 0:
                break
            cards.append(content[i:i + 2000])
            start = i + len(needle)
        return cards

    def test_mixed_progress_shows_two_separate_subticket_cards(self):
        self.client.force_login(self.coord)
        r = self.client.get(reverse('tickets:board'))
        content = r.content.decode()
        cards = self._cards(content, self.mixed)
        self.assertEqual(len(cards), 2, cards)
        statuses = {c.split('data-status="')[1].split('"')[0] for c in cards}
        self.assertEqual(statuses, {'IN_PROGRESS', 'TODO'})
        self.assertTrue(all('data-merged="1"' not in c for c in cards))
        # El coordinador SÍ arrastra los subtickets ajenos (tiene tickets.move) —
        # las cards no van como solo-lectura, pero conservan el badge del ejecutor.
        self.assertTrue(all('data-readonly="1"' not in c for c in cards))
        self.assertTrue(any('d1@e.com' in c for c in cards))

    def test_experto_cards_are_readonly(self):
        # El experto comparte el tablero por ticket pero no tiene tickets.move:
        # sus cards de subticket siguen siendo solo-lectura.
        exp = make_user('exp2@e.com', Role.EXPERTO)
        Assignment.objects.create(ticket=self.mixed, user=exp, kind=Assignment.Kind.EXPERTO)
        self.client.force_login(exp)
        r = self.client.get(reverse('tickets:board'))
        cards = self._cards(r.content.decode(), self.mixed)
        self.assertTrue(cards)
        self.assertTrue(all('data-readonly="1"' in c for c in cards))

    def test_coordinator_merged_card_carries_group_assignment_ids(self):
        self.client.force_login(self.coord)
        r = self.client.get(reverse('tickets:board'))
        cards = self._cards(r.content.decode(), self.aligned)
        self.assertEqual(len(cards), 1, cards)
        pks = sorted(self.aligned.assignments.values_list('pk', flat=True))
        ids_attr = cards[0].split('data-assignment-ids="')[1].split('"')[0]
        self.assertEqual(sorted(int(x) for x in ids_attr.split(',')), pks)
        self.assertNotIn('data-readonly="1"', cards[0])
        self.assertNotIn('data-ghost="1"', cards[0])

    def test_aligned_progress_merges_into_one_card(self):
        self.client.force_login(self.coord)
        r = self.client.get(reverse('tickets:board'))
        content = r.content.decode()
        cards = self._cards(content, self.aligned)
        self.assertEqual(len(cards), 1, cards)
        self.assertIn('data-merged="1"', cards[0])
        self.assertIn('data-status="TODO"', cards[0])

    def test_one_done_one_in_progress_shows_done_card(self):
        # El caso reportado: un ejecutor concluyó, el otro no — el coordinador debe ver
        # esa parte ya en Concluido, no todo el ticket encallado en En progreso.
        self.mixed.assignments.filter(user=self.dev1).update(status=Ticket.Status.DONE)
        self.mixed.recompute_status()   # sigue IN_PROGRESS a nivel agregado (models.py:234)
        self.client.force_login(self.coord)
        r = self.client.get(reverse('tickets:board'))
        content = r.content.decode()
        cards = self._cards(content, self.mixed)
        self.assertEqual(len(cards), 2)
        statuses = {c.split('data-status="')[1].split('"')[0] for c in cards}
        self.assertEqual(statuses, {'DONE', 'TODO'})
        done_card = next(c for c in cards if 'data-status="DONE"' in c)
        self.assertIn('Pendiente de aprobación', done_card)

    def test_experto_also_sees_subticket_cards(self):
        exp = make_user('exp@e.com', Role.EXPERTO)
        Assignment.objects.create(ticket=self.mixed, user=exp, kind=Assignment.Kind.EXPERTO)
        self.client.force_login(exp)
        r = self.client.get(reverse('tickets:board'))
        content = r.content.decode()
        self.assertEqual(len(self._cards(content, self.mixed)), 2)

    def test_collaborative_ticket_still_shows_single_aggregate_card(self):
        # Sin subproductos, el ticket sigue siendo una sola card agregada (no se parte).
        collab = Ticket.objects.create(title='Colaborativo', reporter=self.coord)
        Assignment.objects.create(ticket=collab, user=self.dev1, kind=Assignment.Kind.EJECUTOR,
                                   status=Ticket.Status.IN_PROGRESS)
        Assignment.objects.create(ticket=collab, user=self.dev2, kind=Assignment.Kind.EJECUTOR,
                                   status=Ticket.Status.IN_PROGRESS)
        collab.recompute_status()
        self.client.force_login(self.coord)
        r = self.client.get(reverse('tickets:board'))
        content = r.content.decode()
        self.assertEqual(len(self._cards(content, collab)), 1)

    def test_ticket_without_executors_shows_aggregate_backlog_card(self):
        # has_subproducts=True pero sin ejecutores asignados: no hay nada que partir.
        empty = Ticket.objects.create(title='Sin asignar', reporter=self.coord, has_subproducts=True)
        self.client.force_login(self.coord)
        r = self.client.get(reverse('tickets:board'))
        content = r.content.decode()
        self.assertEqual(len(self._cards(content, empty)), 1)


@override_settings(**OV)
class TicketMoveTests(TestCase):
    def setUp(self):
        self.ej = make_user('ej@e.com', Role.EJECUTOR)
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.t = Ticket.objects.create(title='x', reporter=self.ej,
                                       status=Ticket.Status.BACKLOG)

    def _move(self, status):
        return self.client.post(reverse('tickets:move'),
                                data=json.dumps({'status': status, 'order': [self.t.pk]}),
                                content_type='application/json')

    def test_move_to_done_sets_closed_date(self):
        self.client.force_login(self.coord)
        self.assertEqual(self._move('DONE').status_code, 200)
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, Ticket.Status.DONE)
        self.assertIsNotNone(self.t.closed_date)

    def test_move_out_of_done_clears_closed_date(self):
        self.client.force_login(self.coord)
        self._move('DONE')
        self._move('TODO')
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, Ticket.Status.TODO)
        self.assertIsNone(self.t.closed_date)

    def test_ejecutor_cannot_use_ticket_move(self):
        """Ejecutor tiene tickets.move (para su propio tablero por subticket vía
        assignment_move) pero no tickets.board_by_ticket: no puede tocar cards ajenas."""
        self.client.force_login(self.ej)
        self.assertEqual(self._move('DONE').status_code, 403)

    def test_move_blocked_while_suspended(self):
        self.t.suspended_at = timezone.now()
        self.t.save(update_fields=['suspended_at'])
        self.client.force_login(self.coord)
        self._move('DONE')
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, Ticket.Status.BACKLOG)   # sin cambios: sigue bloqueado

    def test_move_syncs_executor_assignments(self):
        """El drag del coordinador ya no desincroniza Ticket.status de Assignment.status
        (ver comentario histórico en _spawn_child)."""
        dev = make_user('dev@e.com', Role.EJECUTOR)
        a = Assignment.objects.create(ticket=self.t, user=dev, kind=Assignment.Kind.EJECUTOR)
        self.client.force_login(self.coord)
        self.assertEqual(self._move('IN_PROGRESS').status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.status, Ticket.Status.IN_PROGRESS)

    def test_move_to_backlog_blocked_when_has_executors(self):
        dev = make_user('dev@e.com', Role.EJECUTOR)
        Assignment.objects.create(ticket=self.t, user=dev, kind=Assignment.Kind.EJECUTOR,
                                  status=Ticket.Status.TODO)
        self.t.status = Ticket.Status.TODO
        self.t.save(update_fields=['status'])
        self.client.force_login(self.coord)
        self._move('BACKLOG')
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, Ticket.Status.TODO)   # se ignora el movimiento inválido


def _png_bytes():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), 'red').save(buf, 'PNG')
    return buf.getvalue()


@override_settings(**OV)
class AttachmentAccessTests(TestCase):
    def setUp(self):
        MemoryBackend.clear()
        self.owner = make_user('a@e.com', Role.EJECUTOR)
        self.other = make_user('b@e.com', Role.EJECUTOR)
        self.t = Ticket.objects.create(title='secret', reporter=self.owner)
        self.content = _png_bytes()
        f = SimpleUploadedFile('f.png', self.content, content_type='image/png')
        self.att = services.store(f, owner=self.owner, content_object=self.t)

    def test_owner_can_view(self):
        self.client.force_login(self.owner)
        r = self.client.get(reverse('tickets:attachment_serve', args=[self.att.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b''.join(r.streaming_content), self.content)

    def test_safe_image_served_inline(self):
        self.client.force_login(self.owner)
        r = self.client.get(reverse('tickets:attachment_serve', args=[self.att.pk]))
        self.assertTrue(r['Content-Disposition'].startswith('inline'))

    def test_unsafe_type_served_as_attachment(self):
        docx = services.store(
            SimpleUploadedFile('doc.docx', b'x',
                               content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
            owner=self.owner, content_object=self.t,
        )
        self.client.force_login(self.owner)
        r = self.client.get(reverse('tickets:attachment_serve', args=[docx.pk]))
        self.assertTrue(r['Content-Disposition'].startswith('attachment'))

    def test_other_ejecutor_forbidden_idor(self):
        self.client.force_login(self.other)
        r = self.client.get(reverse('tickets:attachment_serve', args=[self.att.pk]))
        self.assertEqual(r.status_code, 403)


@override_settings(**OV)
class CommentGatingTests(TestCase):
    def setUp(self):
        self.owner = make_user('a@e.com', Role.EJECUTOR)
        self.other = make_user('b@e.com', Role.EJECUTOR)
        self.t = Ticket.objects.create(title='x', reporter=self.owner)

    def test_owner_can_comment(self):
        self.client.force_login(self.owner)
        r = self.client.post(reverse('tickets:comment_add', args=[self.t.pk]), {'body': 'hola'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.t.comments.count(), 1)

    def test_non_participant_forbidden(self):
        self.client.force_login(self.other)
        r = self.client.post(reverse('tickets:comment_add', args=[self.t.pk]), {'body': 'hola'})
        self.assertEqual(r.status_code, 403)


AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


@override_settings(**OV)
class CommentAjaxTests(TestCase):
    """comment_add con X-Requested-With devuelve el mensaje renderizado en JSON
    (sin redirect) — el fallback no-AJAX (302) lo cubre CommentGatingTests."""

    def setUp(self):
        self.owner = make_user('a@e.com', Role.EJECUTOR)
        self.t = Ticket.objects.create(title='x', reporter=self.owner)
        self.url = reverse('tickets:comment_add', args=[self.t.pk])
        self.client.force_login(self.owner)

    def test_ajax_comment_returns_rendered_message(self):
        r = self.client.post(self.url, {'body': 'hola ajax'}, **AJAX)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data['ok'])
        comment = self.t.comments.get()
        self.assertEqual(data['comment_id'], comment.pk)
        self.assertIn('hola ajax', data['html'])
        self.assertIn(f'data-comment-id="{comment.pk}"', data['html'])
        self.assertEqual(data['warnings'], [])

    def test_ajax_empty_comment_returns_400(self):
        r = self.client.post(self.url, {'body': '   '}, **AJAX)
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()['ok'])
        self.assertEqual(self.t.comments.count(), 0)

    def test_ajax_duplicate_attachment_returns_warning(self):
        f1 = SimpleUploadedFile('a.txt', b'contenido', content_type='text/plain')
        self.client.post(self.url, {'body': 'con adjunto', 'files': f1}, **AJAX)
        f2 = SimpleUploadedFile('a.txt', b'contenido', content_type='text/plain')
        r = self.client.post(self.url, {'body': 'repetido', 'files': f2}, **AJAX)
        data = r.json()
        self.assertTrue(data['ok'])
        self.assertEqual(len(data['warnings']), 1)
        self.assertEqual(data['warnings'][0]['tag'], 'info')

    def test_comment_email_off_by_default(self):
        dev = make_user('dev@e.com', Role.EJECUTOR)
        Assignment.objects.create(ticket=self.t, user=dev, kind=Assignment.Kind.EJECUTOR)
        self.client.post(self.url, {'body': 'hola'}, **AJAX)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Notification.objects.filter(recipient=dev, verb__icontains='coment').exists())

    def test_comment_email_when_enabled_in_config(self):
        cfg = EmailConfig.load()
        cfg.notify_comment = True
        cfg.save()
        dev = make_user('dev@e.com', Role.EJECUTOR)
        Assignment.objects.create(ticket=self.t, user=dev, kind=Assignment.Kind.EJECUTOR)
        self.client.post(self.url, {'body': 'hola'}, **AJAX)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(dev.email, mail.outbox[0].to)


@override_settings(**OV)
class CommentsSinceTests(TestCase):
    """comments_since devuelve solo los mensajes con pk > after, en orden, para el
    append en vivo del chat (push 'comment.new')."""

    def setUp(self):
        self.owner = make_user('a@e.com', Role.EJECUTOR)
        self.outsider = make_user('b@e.com', Role.EJECUTOR)
        self.t = Ticket.objects.create(title='x', reporter=self.owner)
        self.url = reverse('tickets:comments_since', args=[self.t.pk])

    def test_returns_only_newer_comments_in_order(self):
        c1 = Comment.objects.create(ticket=self.t, author=self.owner, body='uno')
        c2 = Comment.objects.create(ticket=self.t, author=self.owner, body='dos')
        c3 = Comment.objects.create(ticket=self.t, author=self.owner, body='tres')
        self.client.force_login(self.owner)
        r = self.client.get(self.url, {'after': c1.pk})
        data = r.json()
        self.assertTrue(data['ok'])
        self.assertNotIn('uno', data['html'])
        self.assertIn(f'data-comment-id="{c2.pk}"', data['html'])
        self.assertIn(f'data-comment-id="{c3.pk}"', data['html'])
        self.assertLess(data['html'].index('dos'), data['html'].index('tres'))

    def test_outsider_forbidden(self):
        self.client.force_login(self.outsider)
        r = self.client.get(self.url, {'after': 0})
        self.assertEqual(r.status_code, 403)

    def test_invalid_after_is_400(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 400)
        self.assertEqual(self.client.get(self.url, {'after': 'zzz'}).status_code, 400)

    def test_includes_inherited_parent_comments(self):
        parent_comment = Comment.objects.create(ticket=self.t, author=self.owner, body='del padre')
        child = Ticket.objects.create(title='hija', reporter=self.owner, parent=self.t)
        self.client.force_login(self.owner)
        r = self.client.get(reverse('tickets:comments_since', args=[child.pk]), {'after': 0})
        data = r.json()
        self.assertIn(f'data-comment-id="{parent_comment.pk}"', data['html'])
        self.assertIn('heredado', data['html'])  # badge de mensaje heredado


@override_settings(**OV)
class AssignmentNotifyTests(TestCase):
    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.dev = make_user('dev@e.com', Role.EJECUTOR)

    def test_create_with_executor_notifies_and_goes_to_todo(self):
        self.client.force_login(self.coord)
        r = self.client.post(reverse('tickets:create'), {
            'title': 'Nuevo', 'solicitante': 'Gerencia', 'priority': 'MEDIUM',
            'executors': [self.dev.pk],
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Notification.objects.filter(recipient=self.dev, verb__icontains='asign').exists())
        self.assertEqual(len(mail.outbox), 1)
        ticket = Ticket.objects.get(title='Nuevo')
        self.assertEqual(ticket.assignments.filter(user=self.dev, kind='EJECUTOR').count(), 1)
        # Si ya se designó ejecutor en el mismo formulario, el ticket pasa directo a Por
        # hacer — solo queda en Entrada cuando se crea sin ejecutores.
        self.assertEqual(ticket.status, Ticket.Status.TODO)

    def test_create_without_executor_stays_in_backlog(self):
        self.client.force_login(self.coord)
        r = self.client.post(reverse('tickets:create'), {
            'title': 'Sin ejecutor', 'solicitante': 'Gerencia', 'priority': 'MEDIUM',
        })
        self.assertEqual(r.status_code, 302)
        ticket = Ticket.objects.get(title='Sin ejecutor')
        self.assertEqual(ticket.status, Ticket.Status.BACKLOG)

    def test_reassign_notifies_new_executor(self):
        t = Ticket.objects.create(title='x', reporter=self.coord)
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:edit', args=[t.pk]), {
            'title': 'x', 'solicitante': 'Gerencia', 'priority': 'MEDIUM',
            'executors': [self.dev.pk],
        })
        self.assertTrue(Notification.objects.filter(recipient=self.dev).exists())

    def test_assignment_email_disabled_by_config(self):
        cfg = EmailConfig.load()
        cfg.notify_assignment = False
        cfg.save()
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:create'), {
            'title': 'Sin correo', 'solicitante': 'Gerencia', 'priority': 'MEDIUM',
            'executors': [self.dev.pk],
        })
        # La notificación in-app sale igual; solo se apaga el email.
        self.assertTrue(Notification.objects.filter(recipient=self.dev, verb__icontains='asign').exists())
        self.assertEqual(len(mail.outbox), 0)


@override_settings(**OV)
class CommentModerationTests(TestCase):
    def setUp(self):
        self.owner = make_user('a@e.com', Role.EJECUTOR)
        self.other = make_user('b@e.com', Role.EJECUTOR)
        self.sup = make_user('s@e.com', Role.COORDINADOR)
        self.t = Ticket.objects.create(title='x', reporter=self.owner)
        self.c = Comment.objects.create(ticket=self.t, author=self.owner, body='hola')

    def test_author_can_edit(self):
        self.client.force_login(self.owner)
        r = self.client.post(reverse('tickets:comment_edit', args=[self.c.pk]), {'body': 'editado'})
        self.assertEqual(r.status_code, 302)
        self.c.refresh_from_db()
        self.assertEqual(self.c.body, 'editado')

    def test_other_cannot_delete(self):
        self.client.force_login(self.other)
        r = self.client.post(reverse('tickets:comment_delete', args=[self.c.pk]))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Comment.objects.filter(pk=self.c.pk).exists())

    def test_moderator_can_delete(self):
        self.client.force_login(self.sup)
        r = self.client.post(reverse('tickets:comment_delete', args=[self.c.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Comment.objects.filter(pk=self.c.pk).exists())

    def test_old_comment_cannot_be_edited(self):
        Comment.objects.create(ticket=self.t, author=self.other, body='nuevo')
        self.client.force_login(self.owner)
        r = self.client.post(reverse('tickets:comment_edit', args=[self.c.pk]), {'body': 'editado'})
        self.assertEqual(r.status_code, 403)
        self.c.refresh_from_db()
        self.assertEqual(self.c.body, 'hola')

    def test_old_comment_cannot_be_deleted_even_by_moderator(self):
        Comment.objects.create(ticket=self.t, author=self.other, body='nuevo')
        self.client.force_login(self.sup)
        r = self.client.post(reverse('tickets:comment_delete', args=[self.c.pk]))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Comment.objects.filter(pk=self.c.pk).exists())

    def test_old_comment_attachment_cannot_be_deleted(self):
        MemoryBackend.clear()
        att = services.store(
            SimpleUploadedFile('f.png', _png_bytes(), content_type='image/png'),
            owner=self.owner, content_object=self.c,
        )
        Comment.objects.create(ticket=self.t, author=self.other, body='nuevo')
        self.client.force_login(self.owner)
        r = self.client.post(reverse('tickets:attachment_delete', args=[att.pk]))
        self.assertEqual(r.status_code, 403)

    def test_last_comment_attachment_can_be_deleted(self):
        MemoryBackend.clear()
        att = services.store(
            SimpleUploadedFile('f.png', _png_bytes(), content_type='image/png'),
            owner=self.owner, content_object=self.c,
        )
        self.client.force_login(self.owner)
        r = self.client.post(reverse('tickets:attachment_delete', args=[att.pk]))
        self.assertEqual(r.status_code, 302)


@override_settings(**OV)
class DashboardAccessTests(TestCase):
    def test_ejecutor_forbidden(self):
        self.client.force_login(make_user('ej@e.com', Role.EJECUTOR))
        self.assertEqual(self.client.get(reverse('tickets:dashboard')).status_code, 403)

    def test_supervisor_allowed(self):
        self.client.force_login(make_user('sup@e.com', Role.EXPERTO))
        self.assertEqual(self.client.get(reverse('tickets:dashboard')).status_code, 200)


@override_settings(**OV)
class ProjectTests(TestCase):
    def setUp(self):
        self.sup = make_user('sup@e.com', Role.COORDINADOR)
        self.ej = make_user('ej@e.com', Role.EJECUTOR)
        self.proj = Project.objects.create(name='Red Sur', code='SUR', city='Córdoba')
        self.t_in = Ticket.objects.create(title='CONPROY', reporter=self.sup, project=self.proj)
        self.t_out = Ticket.objects.create(title='SINPROY', reporter=self.sup)

    def test_board_filters_by_project(self):
        self.client.force_login(self.sup)
        r = self.client.get(reverse('tickets:board') + f'?project={self.proj.pk}')
        self.assertContains(r, 'CONPROY')
        self.assertNotContains(r, 'SINPROY')

    def test_projects_page_requires_capability(self):
        self.client.force_login(self.ej)
        self.assertEqual(self.client.get(reverse('tickets:projects')).status_code, 403)
        self.client.force_login(self.sup)
        self.assertEqual(self.client.get(reverse('tickets:projects')).status_code, 200)

    def test_code_uppercased_on_save(self):
        p = Project.objects.create(name='Cloud', code='cl ')
        self.assertEqual(p.code, 'CL')


@override_settings(**OV)
class SubticketFlowTests(TestCase):
    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.dev1 = make_user('d1@e.com', Role.EJECUTOR)
        self.dev2 = make_user('d2@e.com', Role.EJECUTOR)
        self.ticket = Ticket.objects.create(title='T', reporter=self.coord, solicitante='X',
                                            has_subproducts=True)
        self.a1 = Assignment.objects.create(ticket=self.ticket, user=self.dev1, kind=Assignment.Kind.EJECUTOR)
        self.a2 = Assignment.objects.create(ticket=self.ticket, user=self.dev2, kind=Assignment.Kind.EJECUTOR)
        self.ticket.recompute_status()

    def _move(self, user, aid, status):
        self.client.force_login(user)
        return self.client.post(reverse('tickets:assignment_move'),
                                data=json.dumps({'assignment': aid, 'status': status}),
                                content_type='application/json')

    def test_assigned_ticket_is_todo(self):
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.TODO)

    def test_executor_moves_only_own_subticket(self):
        r = self._move(self.dev1, self.a1.pk, 'IN_PROGRESS')
        self.assertEqual(r.status_code, 200)
        self.a1.refresh_from_db(); self.a2.refresh_from_db()
        self.assertEqual(self.a1.status, 'IN_PROGRESS')
        self.assertEqual(self.a2.status, 'TODO')
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.IN_PROGRESS)

    def test_executor_cannot_move_others_subticket(self):
        # 403 (no 404): el assignment existe, pero mover subtickets ajenos requiere
        # tickets.assign (coordinador) — ver CoordinatorMovesSubticketsTests.
        self.assertEqual(self._move(self.dev1, self.a2.pk, 'IN_PROGRESS').status_code, 403)

    def test_can_drag_to_done(self):
        r = self._move(self.dev1, self.a1.pk, 'DONE')
        self.assertEqual(r.status_code, 200)
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.status, 'DONE')
        self.assertIsNotNone(self.a1.closed_date)

    def test_conclude_without_text_is_allowed(self):
        self.client.force_login(self.dev1)
        self.client.post(reverse('tickets:assignment_conclude', args=[self.a1.pk]), {'conclusion': ''})
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.status, 'DONE')
        self.assertEqual(self.a1.conclusion, '')

    def test_conclude_then_coordinator_approves(self):
        self.client.force_login(self.dev1)
        self.client.post(reverse('tickets:assignment_conclude', args=[self.a1.pk]), {'conclusion': 'listo http://x'})
        self.client.force_login(self.dev2)
        self.client.post(reverse('tickets:assignment_conclude', args=[self.a2.pk]), {'conclusion': 'ok'})
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.status, 'DONE')
        self.assertIsNone(self.a1.approved_at)
        self.ticket.refresh_from_db()
        self.assertNotEqual(self.ticket.status, Ticket.Status.DONE)
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:approve', args=[self.ticket.pk]))
        self.a1.refresh_from_db(); self.ticket.refresh_from_db()
        self.assertIsNotNone(self.a1.approved_at)
        self.assertEqual(self.ticket.status, Ticket.Status.DONE)

    def test_suspend_by_coordinator(self):
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:suspend', args=[self.ticket.pk]))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.WAITING)


@override_settings(**OV)
class CoordinatorMovesSubticketsTests(TestCase):
    """El coordinador (tickets.assign) también arrastra los subtickets ajenos de un
    ticket multiproducto — de a uno o el grupo fusionado entero (`assignments`)."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.dev1 = make_user('d1@e.com', Role.EJECUTOR)
        self.dev2 = make_user('d2@e.com', Role.EJECUTOR)
        self.ticket = Ticket.objects.create(title='T', reporter=self.coord, has_subproducts=True)
        self.a1 = Assignment.objects.create(ticket=self.ticket, user=self.dev1, kind=Assignment.Kind.EJECUTOR)
        self.a2 = Assignment.objects.create(ticket=self.ticket, user=self.dev2, kind=Assignment.Kind.EJECUTOR)
        self.ticket.recompute_status()

    def _move(self, user, payload):
        self.client.force_login(user)
        return self.client.post(reverse('tickets:assignment_move'),
                                data=json.dumps(payload), content_type='application/json')

    def test_coordinator_moves_others_subticket(self):
        r = self._move(self.coord, {'assignment': self.a1.pk, 'status': 'IN_PROGRESS'})
        self.assertEqual(r.status_code, 200)
        self.a1.refresh_from_db(); self.a2.refresh_from_db()
        self.assertEqual(self.a1.status, 'IN_PROGRESS')
        self.assertEqual(self.a2.status, 'TODO')
        self.assertTrue(TicketEvent.objects.filter(
            ticket=self.ticket, detail__icontains='movió el subticket de').exists())

    def test_coordinator_moves_merged_group(self):
        r = self._move(self.coord, {'assignments': [self.a1.pk, self.a2.pk], 'status': 'IN_PROGRESS'})
        self.assertEqual(r.status_code, 200)
        self.a1.refresh_from_db(); self.a2.refresh_from_db()
        self.assertEqual(self.a1.status, 'IN_PROGRESS')
        self.assertEqual(self.a2.status, 'IN_PROGRESS')
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.IN_PROGRESS)

    def test_coordinator_drags_others_subticket_to_done(self):
        r = self._move(self.coord, {'assignment': self.a1.pk, 'status': 'DONE'})
        self.assertEqual(r.status_code, 200)
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.status, 'DONE')
        self.assertIsNotNone(self.a1.closed_date)
        self.assertIsNone(self.a1.approved_at)   # sigue pendiente de aprobación
        self.assertTrue(TicketEvent.objects.filter(
            ticket=self.ticket, detail__icontains='concluyó el subticket de').exists())

    def test_group_must_belong_to_one_ticket(self):
        other = Ticket.objects.create(title='Otro', reporter=self.coord, has_subproducts=True)
        b1 = Assignment.objects.create(ticket=other, user=self.dev1, kind=Assignment.Kind.EJECUTOR)
        r = self._move(self.coord, {'assignments': [self.a1.pk, b1.pk], 'status': 'IN_PROGRESS'})
        self.assertEqual(r.status_code, 400)

    def test_executor_cannot_move_group_with_foreign_assignment(self):
        r = self._move(self.dev1, {'assignments': [self.a1.pk, self.a2.pk], 'status': 'IN_PROGRESS'})
        self.assertEqual(r.status_code, 403)
        self.a2.refresh_from_db()
        self.assertEqual(self.a2.status, 'TODO')

    def test_unknown_assignment_is_404(self):
        r = self._move(self.coord, {'assignment': 999999, 'status': 'IN_PROGRESS'})
        self.assertEqual(r.status_code, 404)


@override_settings(**OV)
class MergedSubticketCardTests(TestCase):
    """Con subproductos, si 2+ subtickets del mismo ticket coinciden en la misma
    columna, se fusionan en una sola card — se separan de nuevo en cuanto alguno
    cambie de estado."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.dev1 = make_user('d1@e.com', Role.EJECUTOR)
        self.dev2 = make_user('d2@e.com', Role.EJECUTOR)
        self.dev3 = make_user('d3@e.com', Role.EJECUTOR)
        self.ticket = Ticket.objects.create(title='T', reporter=self.coord, solicitante='X',
                                            has_subproducts=True)
        self.a1 = Assignment.objects.create(ticket=self.ticket, user=self.dev1, kind=Assignment.Kind.EJECUTOR)
        self.a2 = Assignment.objects.create(ticket=self.ticket, user=self.dev2, kind=Assignment.Kind.EJECUTOR)
        self.ticket.recompute_status()

    def test_same_status_merges_into_one_card(self):
        # a1 y a2 arrancan ambos en TODO (default) — misma columna.
        self.client.force_login(self.dev1)
        r = self.client.get(reverse('tickets:board'))
        content = r.content.decode()
        self.assertEqual(content.count(f'data-ticket-id="{self.ticket.pk}"'), 1)
        i = content.find(f'data-ticket-id="{self.ticket.pk}"')
        block = content[i:i + 200]
        self.assertIn('data-merged="1"', block)
        self.assertIn(f'data-assignment-id="{self.a1.pk}"', block)  # arrastra la propia

    def test_fully_merged_ticket_has_no_link_marker(self):
        # Únicos 2 ejecutores, ambos alineados en el mismo estado: no queda ninguna
        # otra card de este ticket en el tablero, así que la marca de vínculo no aporta.
        self.client.force_login(self.dev1)
        r = self.client.get(reverse('tickets:board'))
        content = r.content.decode()
        i = content.find(f'data-ticket-id="{self.ticket.pk}"')
        block = content[i:i + 400]
        self.assertNotIn('data-link-color', block)

    def test_link_marker_returns_when_a_third_diverges(self):
        # dev3 se suma y queda en otra columna: ahora SÍ hay 2 cards del mismo ticket
        # (la fusionada de dev1+dev2, y la de dev3 solo) — la marca de color en el borde
        # derecho (data-link-color en el root, pintada por CSS) vuelve a tener sentido.
        a3 = Assignment.objects.create(ticket=self.ticket, user=self.dev3, kind=Assignment.Kind.EJECUTOR,
                                       status='IN_PROGRESS')
        self.client.force_login(self.dev1)
        r = self.client.get(reverse('tickets:board'))
        content = r.content.decode()
        merged_i = content.find(f'data-ticket-id="{self.ticket.pk}" data-status="TODO"')
        solo_i = content.find(f'data-assignment-id="{a3.pk}"')
        self.assertIn('data-link-color', content[merged_i:merged_i + 700])
        self.assertIn('data-link-color', content[solo_i:solo_i + 700])

    def test_diverging_status_splits_back_into_two_cards(self):
        self.client.force_login(self.dev1)
        self.client.post(reverse('tickets:assignment_move'),
                         data=json.dumps({'assignment': self.a1.pk, 'status': 'IN_PROGRESS'}),
                         content_type='application/json')
        r = self.client.get(reverse('tickets:board'))
        content = r.content.decode()
        self.assertEqual(content.count(f'data-ticket-id="{self.ticket.pk}"'), 2)
        self.assertNotIn('data-merged="1"', content)

    def test_merged_group_without_my_own_assignment_is_ghost(self):
        # dev1 sigue en TODO; dev2 y dev3 comparten IN_PROGRESS sin dev1 en el medio.
        a3 = Assignment.objects.create(ticket=self.ticket, user=self.dev3, kind=Assignment.Kind.EJECUTOR)
        self.a2.status = 'IN_PROGRESS'; self.a2.save()
        a3.status = 'IN_PROGRESS'; a3.save()
        self.client.force_login(self.dev1)
        r = self.client.get(reverse('tickets:board'))
        content = r.content.decode()
        i = content.find(f'data-ticket-id="{self.ticket.pk}" data-status="IN_PROGRESS"')
        self.assertGreaterEqual(i, 0)
        block = content[i:i + 200]
        self.assertIn('data-merged="1"', block)
        self.assertIn('data-ghost="1"', block)
        self.assertNotIn('data-assignment-id', block)


@override_settings(**OV)
class CollaborativeFlowTests(TestCase):
    """Sin subproductos: el estado es compartido (mover/concluir sincroniza a todos)."""
    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.dev1 = make_user('d1@e.com', Role.EJECUTOR)
        self.dev2 = make_user('d2@e.com', Role.EJECUTOR)
        self.ticket = Ticket.objects.create(title='T', reporter=self.coord, solicitante='X',
                                            has_subproducts=False)
        self.a1 = Assignment.objects.create(ticket=self.ticket, user=self.dev1, kind=Assignment.Kind.EJECUTOR)
        self.a2 = Assignment.objects.create(ticket=self.ticket, user=self.dev2, kind=Assignment.Kind.EJECUTOR)
        self.ticket.recompute_status()

    def test_move_syncs_all_executors(self):
        self.client.force_login(self.dev1)
        r = self.client.post(reverse('tickets:assignment_move'),
                             data=json.dumps({'assignment': self.a1.pk, 'status': 'IN_PROGRESS'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.a1.refresh_from_db(); self.a2.refresh_from_db(); self.ticket.refresh_from_db()
        self.assertEqual(self.a1.status, 'IN_PROGRESS')
        self.assertEqual(self.a2.status, 'IN_PROGRESS')   # el otro también se movió
        self.assertEqual(self.ticket.status, Ticket.Status.IN_PROGRESS)

    def test_conclude_concludes_all(self):
        self.client.force_login(self.dev1)
        self.client.post(reverse('tickets:assignment_conclude', args=[self.a1.pk]), {'conclusion': 'listo'})
        self.a1.refresh_from_db(); self.a2.refresh_from_db()
        self.assertEqual(self.a1.status, 'DONE')
        self.assertEqual(self.a2.status, 'DONE')          # concluye para todos


class TimeTrackingTests(TestCase):
    """advance_to() acumula tiempo por estado y pausa el reloj en Esperando/Suspendido."""

    def setUp(self):
        coord = make_user('coord@e.com', Role.COORDINADOR)
        dev = make_user('dev@e.com', Role.EJECUTOR)
        ticket = Ticket.objects.create(title='T', reporter=coord, has_subproducts=True)
        self.a = Assignment.objects.create(ticket=ticket, user=dev, kind=Assignment.Kind.EJECUTOR)

    def test_accumulates_todo_and_in_progress(self):
        an_hour_ago = timezone.now() - timedelta(hours=1)
        self.a.status = Ticket.Status.TODO
        self.a.status_changed_at = an_hour_ago
        self.a.save()

        t1 = timezone.now()
        self.a.advance_to(Ticket.Status.IN_PROGRESS, t1)
        self.a.save()
        self.assertGreaterEqual(self.a.time_todo.total_seconds(), 3599)
        self.assertEqual(self.a.time_in_progress, timedelta())
        self.assertIsNotNone(self.a.started_at)

        t2 = t1 + timedelta(hours=2)
        self.a.advance_to(Ticket.Status.DONE, t2)
        self.a.save()
        self.assertGreaterEqual(self.a.time_in_progress.total_seconds(), 7199)

    def test_waiting_pauses_the_clock(self):
        t0 = timezone.now()
        self.a.status = Ticket.Status.IN_PROGRESS
        self.a.status_changed_at = t0
        self.a.save()

        t1 = t0 + timedelta(hours=1)
        self.a.advance_to(Ticket.Status.WAITING, t1)
        self.a.save()
        elapsed_in_progress = self.a.time_in_progress

        # 5 horas suspendido: no deben sumarse a ningún bucket.
        t2 = t1 + timedelta(hours=5)
        self.a.advance_to(Ticket.Status.TODO, t2)
        self.a.save()
        self.assertEqual(self.a.time_in_progress, elapsed_in_progress)
        self.assertEqual(self.a.time_todo, timedelta())

    def test_time_in_includes_current_open_span(self):
        t0 = timezone.now() - timedelta(minutes=30)
        self.a.status = Ticket.Status.TODO
        self.a.status_changed_at = t0
        self.a.save()
        # Sin cerrar el tramo, time_in() debe incluir lo transcurrido hasta `now`.
        self.assertGreaterEqual(self.a.time_in(Ticket.Status.TODO, timezone.now()).total_seconds(), 1799)
        self.assertEqual(self.a.time_in(Ticket.Status.WAITING, timezone.now()), timedelta())


class SuspendLockTests(TestCase):
    """Solo el coordinador puede suspender; mientras está suspendido, el ejecutor no puede moverlo."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.dev = make_user('dev@e.com', Role.EJECUTOR)
        self.ticket = Ticket.objects.create(title='T', reporter=self.coord, has_subproducts=True)
        self.a = Assignment.objects.create(ticket=self.ticket, user=self.dev, kind=Assignment.Kind.EJECUTOR)
        self.ticket.recompute_status()

    def _move(self, status):
        self.client.force_login(self.dev)
        return self.client.post(reverse('tickets:assignment_move'),
                                data=json.dumps({'assignment': self.a.pk, 'status': status}),
                                content_type='application/json')

    def test_suspend_sets_flag_and_blocks_executor_move(self):
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:suspend', args=[self.ticket.pk]))
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.suspended_at)
        self.assertEqual(self.ticket.status, Ticket.Status.WAITING)

        r = self._move('IN_PROGRESS')
        self.assertEqual(r.status_code, 400)
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, Ticket.Status.WAITING)

    def test_reactivate_clears_flag_and_unlocks(self):
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:suspend', args=[self.ticket.pk]))   # suspende
        self.client.post(reverse('tickets:suspend', args=[self.ticket.pk]))   # reactiva
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.suspended_at)

        r = self._move('IN_PROGRESS')
        self.assertEqual(r.status_code, 200)

    def test_suspend_ticket_without_assignments_goes_to_waiting_not_backlog(self):
        # Entrada (sin ejecutores): recompute_status() no debía pisar el suspendido
        # con BACKLOG solo porque no hay ejecutores asignados.
        unassigned = Ticket.objects.create(title='Sin ejecutores', reporter=self.coord)
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:suspend', args=[unassigned.pk]))
        unassigned.refresh_from_db()
        self.assertIsNotNone(unassigned.suspended_at)
        self.assertEqual(unassigned.status, Ticket.Status.WAITING)


class ArchiveUnarchiveTests(TestCase):
    """Archivar lo puede hacer cualquier editor; desarchivar exige la capacidad
    tickets.unarchive (por defecto solo Coordinador — y superuser por bypass)."""

    def setUp(self):
        self.reporter = make_user('rep@e.com', Role.EJECUTOR)
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.superuser = User.objects.create_superuser('root@e.com', 'root@e.com', 'x')
        self.ticket = Ticket.objects.create(
            title='T', reporter=self.reporter, status=Ticket.Status.DONE,
            archived_at=timezone.now(),
        )

    def test_ejecutor_cannot_unarchive(self):
        self.client.force_login(self.reporter)
        r = self.client.post(reverse('tickets:unarchive', args=[self.ticket.pk]))
        self.assertEqual(r.status_code, 403)
        self.ticket.refresh_from_db()
        self.assertTrue(self.ticket.is_archived)

    def test_coordinador_can_unarchive(self):
        self.client.force_login(self.coord)
        r = self.client.post(reverse('tickets:unarchive', args=[self.ticket.pk]))
        self.assertEqual(r.status_code, 302)
        self.ticket.refresh_from_db()
        self.assertFalse(self.ticket.is_archived)

    def test_superuser_can_unarchive(self):
        self.client.force_login(self.superuser)
        r = self.client.post(reverse('tickets:unarchive', args=[self.ticket.pk]))
        self.assertEqual(r.status_code, 302)
        self.ticket.refresh_from_db()
        self.assertFalse(self.ticket.is_archived)


@override_settings(**OV)
class TicketDeleteTests(TestCase):
    """Borrado definitivo desde la X de la card: solo superuser."""

    def setUp(self):
        self.coord = make_user('coord-del@e.com', Role.COORDINADOR)
        self.superuser = User.objects.create_superuser('root-del@e.com', 'root-del@e.com', 'x')
        self.ticket = Ticket.objects.create(title='T', reporter=self.coord)

    def test_superuser_can_delete(self):
        self.client.force_login(self.superuser)
        r = self.client.post(reverse('tickets:delete', args=[self.ticket.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Ticket.objects.filter(pk=self.ticket.pk).exists())

    def test_non_superuser_cannot_delete(self):
        self.client.force_login(self.coord)
        r = self.client.post(reverse('tickets:delete', args=[self.ticket.pk]))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Ticket.objects.filter(pk=self.ticket.pk).exists())


class TicketCodeGenerationTests(TestCase):
    """Al crear un hijo (derivar o dividir), el código cuelga del código del padre
    (SKY-000N-1, -2…) en vez de tomar un número nuevo del correlativo global."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.parent = Ticket.objects.create(title='Padre', reporter=self.coord)

    def test_first_child_code(self):
        child = self.parent.create_child(title='Hijo 1', reporter=self.coord)
        self.assertEqual(child.code, f'{self.parent.code}-1')

    def test_sequential_child_codes(self):
        self.parent.create_child(title='Hijo 1', reporter=self.coord)
        child2 = self.parent.create_child(title='Hijo 2', reporter=self.coord)
        self.assertEqual(child2.code, f'{self.parent.code}-2')

    def test_nested_child_chains_off_immediate_parent(self):
        child = self.parent.create_child(title='Hijo', reporter=self.coord)
        grandchild = child.create_child(title='Nieto', reporter=self.coord)
        self.assertEqual(grandchild.code, f'{child.code}-1')

    def test_child_code_robust_to_gaps(self):
        # Si se borra un hijo del medio (no el último), el próximo código no debe
        # colisionar con los que quedaron por encima del hueco.
        child1 = self.parent.create_child(title='Hijo 1', reporter=self.coord)
        self.parent.create_child(title='Hijo 2', reporter=self.coord)
        self.parent.create_child(title='Hijo 3', reporter=self.coord)
        child1.delete()
        child4 = self.parent.create_child(title='Hijo 4', reporter=self.coord)
        self.assertEqual(child4.code, f'{self.parent.code}-4')

    def test_flat_counter_unaffected_by_subdivision(self):
        self.parent.create_child(title='Hijo 1', reporter=self.coord)
        other = Ticket.objects.create(title='Otro ticket normal', reporter=self.coord)
        self.assertRegex(other.code, r'^SKY-\d{4}$')

    def test_derive_view_uses_hierarchical_code(self):
        self.client.force_login(self.coord)
        r = self.client.post(reverse('tickets:derive', args=[self.parent.pk]))
        self.assertEqual(r.status_code, 302)
        child = self.parent.children.get()
        self.assertEqual(child.code, f'{self.parent.code}-1')


@override_settings(**OV)
class TicketCardBadgeTests(TestCase):
    """Marcas en la card del tablero: en el maestro, solo el ícono de tijera (abajo,
    negro/blanco, sin texto); en el hijo, solo el ícono de derivado (arriba, junto al
    código). Distintas de "Subproductos" (has_subproducts) para no repetir la confusión
    entre ambos conceptos."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)

    def test_parent_shows_derivado_icon(self):
        parent = Ticket.objects.create(title='Padre', reporter=self.coord)
        parent.create_child(title='Hijo', reporter=self.coord)
        self.client.force_login(self.coord)
        r = self.client.get(reverse('tickets:board'))
        self.assertContains(r, 'Derivado en 1 subticket')

    def test_child_shows_derivado_icon(self):
        parent = Ticket.objects.create(title='Padre', reporter=self.coord)
        parent.create_child(title='Hijo', reporter=self.coord)
        self.client.force_login(self.coord)
        r = self.client.get(reverse('tickets:board'))
        self.assertContains(r, 'Deriva de otro ticket')

    def test_has_subproducts_shows_distinct_icon(self):
        # Título sin la palabra "subproductos" para no confundir el aserto con el título.
        Ticket.objects.create(title='Tarea grupal', reporter=self.coord, has_subproducts=True)
        self.client.force_login(self.coord)
        r = self.client.get(reverse('tickets:board'))
        self.assertContains(r, 'Cada ejecutor tiene su subticket independiente')
        self.assertNotContains(r, 'Derivado en')


@override_settings(**OV)
class PriorityBarsTests(TestCase):
    """La prioridad se muestra como barras de intensidad (data-priority en .prio-bars),
    no como badge de texto — para no confundirse por color con el estado (mismo token
    info/warning que las columnas Por hacer/En progreso)."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)

    def test_each_priority_renders_prio_bars_not_badge(self):
        for priority in ('LOW', 'MEDIUM', 'HIGH', 'URGENT'):
            Ticket.objects.create(title=f'P {priority}', reporter=self.coord, priority=priority)
        self.client.force_login(self.coord)
        r = self.client.get(reverse('tickets:board'))
        content = r.content.decode()
        for priority in ('LOW', 'MEDIUM', 'HIGH', 'URGENT'):
            self.assertIn(f'prio-bars shrink-0" data-priority="{priority}"', content)
        self.assertNotIn('badge-info', content)
        self.assertNotIn('badge-warning', content)


@override_settings(**OV)
class DeriveInheritanceTests(TestCase):
    """Al derivar, el hijo hereda las etiquetas y las personas asignadas del padre
    (mismos usuarios, mismo kind), arrancando su propio estado desde cero."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.ejecutor = make_user('ej@e.com', Role.EJECUTOR)
        self.experto = make_user('exp@e.com', Role.EXPERTO)
        self.infra = Label.objects.create(name='infra', color=Label.Color.INFO)
        self.bug = Label.objects.create(name='bug', color=Label.Color.ERROR)
        self.parent = Ticket.objects.create(title='Padre', reporter=self.coord)
        self.parent.labels.set([self.infra, self.bug])
        Assignment.objects.create(ticket=self.parent, user=self.ejecutor, kind=Assignment.Kind.EJECUTOR)
        Assignment.objects.create(ticket=self.parent, user=self.experto, kind=Assignment.Kind.EXPERTO)

    def test_child_inherits_labels(self):
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:derive', args=[self.parent.pk]))
        child = self.parent.children.get()
        self.assertCountEqual(child.labels.all(), [self.infra, self.bug])

    def test_child_inherits_assignments(self):
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:derive', args=[self.parent.pk]))
        child = self.parent.children.get()
        self.assertEqual(
            {(a.user_id, a.kind) for a in child.assignments.all()},
            {(self.ejecutor.pk, Assignment.Kind.EJECUTOR), (self.experto.pk, Assignment.Kind.EXPERTO)},
        )

    def test_child_lands_in_parent_status_column(self):
        self.parent.status = Ticket.Status.IN_PROGRESS
        self.parent.save(update_fields=['status'])
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:derive', args=[self.parent.pk]))
        child = self.parent.children.get()
        self.assertEqual(child.status, Ticket.Status.IN_PROGRESS)

    def test_child_assignments_start_fresh(self):
        # El padre puede tener avance (estado, conclusión); el hijo arranca de cero.
        self.parent.assignments.filter(user=self.ejecutor).update(
            status=Ticket.Status.DONE, conclusion='Ya lo hice',
        )
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:derive', args=[self.parent.pk]))
        child = self.parent.children.get()
        child_assignment = child.assignments.get(user=self.ejecutor)
        self.assertEqual(child_assignment.status, Ticket.Status.TODO)
        self.assertEqual(child_assignment.conclusion, '')


@override_settings(**OV)
class DivideContainerTests(TestCase):
    """Al dividir, el original sigue activo tal cual (no se oculta ni se borra) y la parte
    nueva hereda etiquetas/asignados/contenido/estado del padre."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.ejecutor = make_user('ej@e.com', Role.EJECUTOR)
        self.parent = Ticket.objects.create(title='Padre', reporter=self.coord)
        Assignment.objects.create(ticket=self.parent, user=self.coord, kind=Assignment.Kind.EJECUTOR)
        Assignment.objects.create(ticket=self.parent, user=self.ejecutor, kind=Assignment.Kind.EJECUTOR)

    def test_divide_does_not_hide_parent(self):
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:divide', args=[self.parent.pk]))
        self.parent.refresh_from_db()
        self.assertIsNone(self.parent.split_at)
        r = self.client.get(reverse('tickets:board'))
        self.assertContains(r, f'data-ticket-id="{self.parent.pk}"')
        r = self.client.get(reverse('tickets:my_tickets'))
        # Mis tickets es una lista de <a> (sin data-ticket-id): se verifica por el href.
        self.assertContains(r, f'href="/{self.parent.pk}/"')

    def test_parts_are_marked_as_divided(self):
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:divide', args=[self.parent.pk]))
        part = self.parent.children.get()
        self.assertTrue(part.is_divided_part)
        # Un hijo de Derivar no es una "parte" (usa la flecha, no la tijera).
        derived = self.parent.create_child(title='Derivado', reporter=self.coord, status=self.parent.status)
        self.assertFalse(derived.is_divided_part)

    def test_divide_creates_one_part(self):
        self.client.force_login(self.coord)
        r = self.client.post(reverse('tickets:divide', args=[self.parent.pk]))
        self.assertRedirects(r, reverse('tickets:board'))
        part = self.parent.children.get()
        self.assertEqual(part.code, f'{self.parent.code}-1')

    def test_part_inherits_labels_and_assignments(self):
        label = Label.objects.create(name='infra', color=Label.Color.INFO)
        self.parent.labels.set([label])
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:divide', args=[self.parent.pk]))
        part = self.parent.children.get()
        self.assertCountEqual(part.labels.all(), [label])
        self.assertEqual(
            {(a.user_id, a.kind) for a in part.assignments.all()},
            {(self.coord.pk, Assignment.Kind.EJECUTOR), (self.ejecutor.pk, Assignment.Kind.EJECUTOR)},
        )

    def test_dividing_again_adds_one_more_part(self):
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:divide', args=[self.parent.pk]))
        self.client.post(reverse('tickets:divide', args=[self.parent.pk]))
        self.parent.refresh_from_db()
        self.assertEqual(self.parent.children.count(), 2)
        codes = sorted(self.parent.children.values_list('code', flat=True))
        self.assertEqual(codes, [f'{self.parent.code}-1', f'{self.parent.code}-2'])

    def test_part_clones_content_identical_to_parent(self):
        self.parent.description = 'Descripción original'
        self.parent.priority = Ticket.Priority.HIGH
        self.parent.due_date = timezone.localdate()
        self.parent.save()
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:divide', args=[self.parent.pk]))
        part = self.parent.children.get()
        self.assertEqual(part.title, self.parent.title)
        self.assertEqual(part.description, self.parent.description)
        self.assertEqual(part.priority, self.parent.priority)
        self.assertEqual(part.due_date, self.parent.due_date)
        self.assertEqual(part.reporter_id, self.parent.reporter_id)

    def test_part_of_in_progress_parent_stays_in_progress(self):
        self.parent.assignments.filter(user=self.ejecutor).update(
            status=Ticket.Status.IN_PROGRESS, started_at=timezone.now(),
        )
        self.parent.recompute_status()
        self.assertEqual(self.parent.status, Ticket.Status.IN_PROGRESS)
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:divide', args=[self.parent.pk]))
        part = self.parent.children.get()
        self.assertEqual(part.status, Ticket.Status.IN_PROGRESS)
        # Y en el tablero la card cae en la misma columna que ocupaba el padre.
        r = self.client.get(reverse('tickets:board'))
        self.assertContains(r, f'data-ticket-id="{part.pk}" data-status="IN_PROGRESS"')

    def test_part_of_done_and_approved_parent_is_also_done(self):
        now = timezone.now()
        self.parent.assignments.update(status=Ticket.Status.DONE, approved_at=now, closed_date=now)
        self.parent.recompute_status()
        self.assertEqual(self.parent.status, Ticket.Status.DONE)
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:divide', args=[self.parent.pk]))
        part = self.parent.children.get()
        self.assertEqual(part.status, Ticket.Status.DONE)


@override_settings(**OV)
class InheritedThreadTests(TestCase):
    """El detalle de un derivado/parte muestra el seguimiento y el historial de su
    cadena de padres, heredados en vivo (sin copiar filas), mezclados por fecha y
    en solo-lectura."""

    def setUp(self):
        self.coord = make_user('coord-h@e.com', Role.COORDINADOR)
        self.parent = Ticket.objects.create(title='Padre', reporter=self.coord)
        self.parent_comment = Comment.objects.create(
            ticket=self.parent, author=self.coord, body='Contexto del pedido original',
        )
        TicketEvent.objects.create(
            ticket=self.parent, actor=self.coord, kind='status', detail='cambió el estado a Por hacer',
        )
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:derive', args=[self.parent.pk]))
        self.child = self.parent.children.get()

    def test_child_detail_shows_parent_comment_with_origin_chip(self):
        r = self.client.get(reverse('tickets:detail', args=[self.child.pk]))
        self.assertContains(r, 'Contexto del pedido original')
        self.assertContains(r, 'Mensaje heredado del ticket de origen')
        self.assertContains(r, f'incluye {self.parent.key}')

    def test_child_detail_shows_parent_event(self):
        r = self.client.get(reverse('tickets:detail', args=[self.child.pk]))
        self.assertContains(r, 'cambió el estado a Por hacer')
        self.assertContains(r, 'Evento heredado del ticket de origen')

    def test_parent_comment_added_after_derive_appears_in_child(self):
        Comment.objects.create(ticket=self.parent, author=self.coord, body='Mensaje posterior a derivar')
        r = self.client.get(reverse('tickets:detail', args=[self.child.pk]))
        self.assertContains(r, 'Mensaje posterior a derivar')

    def test_inherited_comment_is_read_only_in_child(self):
        # El comment del padre es el último del hilo mezclado y su autor es quien mira,
        # pero al ser heredado no debe ofrecer edición desde el hijo…
        r = self.client.get(reverse('tickets:detail', args=[self.child.pk]))
        self.assertNotContains(r, '>editar<')
        # …mientras que en su propio ticket sí.
        r = self.client.get(reverse('tickets:detail', args=[self.parent.pk]))
        self.assertContains(r, '>editar<')

    def test_parent_detail_does_not_show_child_comments(self):
        Comment.objects.create(ticket=self.child, author=self.coord, body='Solo del derivado')
        r = self.client.get(reverse('tickets:detail', args=[self.parent.pk]))
        self.assertNotContains(r, 'Solo del derivado')

    def test_marker_carries_thread_ids_for_live_refresh(self):
        r = self.client.get(reverse('tickets:detail', args=[self.child.pk]))
        self.assertContains(r, f'data-thread-ids="{self.child.pk},{self.parent.pk}"')


@override_settings(**OV)
class LabelQuickAddTests(TestCase):
    """Alta rápida de tipos de actividad desde el formulario de ticket (AJAX):
    solo quien tiene tickets.edit_any (Coordinador); nombre repetido reutiliza."""

    def setUp(self):
        self.coord = make_user('coord-l@e.com', Role.COORDINADOR)
        self.ej = make_user('ej-l@e.com', Role.EJECUTOR)

    def test_coordinator_can_quick_add(self):
        self.client.force_login(self.coord)
        r = self.client.post(reverse('tickets:label_add'), {'name': 'Relevamiento', 'color': 'info'})
        data = r.json()
        self.assertTrue(data['ok'])
        self.assertTrue(data['created'])
        label = Label.objects.get(pk=data['id'])
        self.assertEqual((label.name, label.color), ('Relevamiento', 'info'))

    def test_duplicate_name_reuses_existing(self):
        existing = Label.objects.create(name='Relevamiento', color=Label.Color.SUCCESS)
        self.client.force_login(self.coord)
        r = self.client.post(reverse('tickets:label_add'), {'name': 'Relevamiento', 'color': 'info'})
        data = r.json()
        self.assertTrue(data['ok'])
        self.assertFalse(data['created'])
        self.assertEqual(data['id'], existing.pk)
        self.assertEqual(data['color'], 'success')  # conserva el color original

    def test_invalid_payload_is_rejected(self):
        self.client.force_login(self.coord)
        r = self.client.post(reverse('tickets:label_add'), {'name': '  ', 'color': 'info'})
        self.assertEqual(r.status_code, 400)
        r = self.client.post(reverse('tickets:label_add'), {'name': 'X', 'color': 'fucsia'})
        self.assertEqual(r.status_code, 400)

    def test_ejecutor_cannot_quick_add(self):
        self.client.force_login(self.ej)
        r = self.client.post(reverse('tickets:label_add'), {'name': 'Hack', 'color': 'info'})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Label.objects.filter(name='Hack').exists())

    def test_create_form_shows_quick_add_ui_and_chip_options(self):
        Label.objects.create(name='Cableado', color=Label.Color.WARNING)
        self.client.force_login(self.coord)
        r = self.client.get(reverse('tickets:create'))
        self.assertContains(r, 'data-label-add')                    # UI de alta rápida
        self.assertContains(r, 'checkbox checkbox-xs')              # checkbox DaisyUI
        self.assertContains(r, 'data-color="warning">Cableado')     # chip con color

    def test_edit_form_preselects_ticket_labels(self):
        label = Label.objects.create(name='Cableado', color=Label.Color.WARNING)
        t = Ticket.objects.create(title='T', reporter=self.coord)
        t.labels.set([label])
        self.client.force_login(self.coord)
        r = self.client.get(reverse('tickets:edit', args=[t.pk]))
        html = r.content.decode()
        i = html.find(f'value="{label.pk}"')
        self.assertNotEqual(i, -1)
        self.assertIn('checked', html[i:i + 200])


@override_settings(**OV)
class TicketModeDragTests(TestCase):
    """El tablero "por ticket" (Coordinador/Experto/Seguimiento) respeta `tickets.move`
    para habilitar drag&drop, igual que ya hacía el tablero "por subticket" (Ejecutor) —
    antes quedaba deshabilitado a fuego para todos los roles de este modo."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.exp = make_user('exp@e.com', Role.EXPERTO)
        self.ticket = Ticket.objects.create(
            title='T', reporter=self.coord, status=Ticket.Status.BACKLOG,
        )

    def test_coordinador_board_is_draggable(self):
        self.client.force_login(self.coord)
        r = self.client.get(reverse('tickets:board'))
        self.assertContains(r, 'data-can-move="1"')

    def test_experto_board_is_not_draggable(self):
        # Experto ve el tablero por ticket (board_by_ticket) pero no tiene tickets.move.
        self.client.force_login(self.exp)
        r = self.client.get(reverse('tickets:board'))
        self.assertContains(r, 'data-can-move="0"')

    def test_coordinador_can_move_ticket_to_any_status(self):
        self.client.force_login(self.coord)
        for status in (Ticket.Status.DONE, Ticket.Status.WAITING, Ticket.Status.TODO):
            r = self.client.post(
                reverse('tickets:move'),
                data=json.dumps({'status': status, 'order': [self.ticket.pk]}),
                content_type='application/json',
            )
            self.assertEqual(r.status_code, 200)
            self.ticket.refresh_from_db()
            self.assertEqual(self.ticket.status, status)

    def test_experto_cannot_move_ticket(self):
        self.client.force_login(self.exp)
        r = self.client.post(
            reverse('tickets:move'),
            data=json.dumps({'status': Ticket.Status.DONE, 'order': [self.ticket.pk]}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 403)


@override_settings(**OV)
class BacklogToTodoNotifyTests(TestCase):
    """Al pasar Entrada -> Por hacer, avisa a los involucrados preexistentes, menos a
    quien hizo el cambio (siempre un coordinador, único rol con tickets.assign)."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.exp = make_user('exp@e.com', Role.EXPERTO)
        self.dev = make_user('dev@e.com', Role.EJECUTOR)
        # Con un experto ya asignado y cero ejecutores, el ticket queda en BACKLOG
        # (recompute_status solo mira executor_assignments).
        self.t = Ticket.objects.create(title='x', reporter=self.coord, status=Ticket.Status.BACKLOG)
        Assignment.objects.create(ticket=self.t, user=self.exp, kind=Assignment.Kind.EXPERTO)

    def test_ticket_edit_assigns_first_executor_notifies_preexisting_participant(self):
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:edit', args=[self.t.pk]), {
            'title': 'x', 'solicitante': 'Gerencia', 'priority': 'MEDIUM',
            'executors': [self.dev.pk], 'experts': [self.exp.pk],
        })
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, Ticket.Status.TODO)
        self.assertTrue(
            Notification.objects.filter(recipient=self.exp, verb='puso en Por hacer').exists()
        )
        self.assertFalse(
            Notification.objects.filter(recipient=self.coord, verb='puso en Por hacer').exists()
        )

    def test_ticket_move_backlog_to_todo_notifies_preexisting_participant(self):
        self.client.force_login(self.coord)
        r = self.client.post(
            reverse('tickets:move'),
            data=json.dumps({'status': Ticket.Status.TODO, 'order': [self.t.pk]}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(
            Notification.objects.filter(recipient=self.exp, verb='puso en Por hacer').exists()
        )
        self.assertFalse(
            Notification.objects.filter(recipient=self.coord, verb='puso en Por hacer').exists()
        )

    def test_ticket_create_with_executor_does_not_fire_backlog_notification(self):
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:create'), {
            'title': 'Nuevo', 'solicitante': 'Gerencia', 'priority': 'MEDIUM',
            'executors': [self.dev.pk],
        })
        self.assertFalse(Notification.objects.filter(verb='puso en Por hacer').exists())


@override_settings(**OV)
class ReopenClearsApprovalTests(TestCase):
    """Reabrir un subticket concluido (drag fuera de Concluido) invalida la aprobación:
    approved_at/closed_date se limpian y la re-conclusión vuelve a exigir aprobación."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.dev = make_user('dev@e.com', Role.EJECUTOR)
        self.ticket = Ticket.objects.create(title='T', reporter=self.coord, has_subproducts=True)
        self.a = Assignment.objects.create(ticket=self.ticket, user=self.dev, kind=Assignment.Kind.EJECUTOR)
        self.ticket.recompute_status()

    def _move(self, status):
        self.client.force_login(self.dev)
        return self.client.post(reverse('tickets:assignment_move'),
                                data=json.dumps({'assignment': self.a.pk, 'status': status}),
                                content_type='application/json')

    def test_reopen_after_approval_requires_reapproval(self):
        self.client.force_login(self.dev)
        self.client.post(reverse('tickets:assignment_conclude', args=[self.a.pk]), {'conclusion': 'v1'})
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:approve', args=[self.ticket.pk]))
        self.a.refresh_from_db()
        self.assertIsNotNone(self.a.approved_at)

        # El ejecutor reabre para rehacer el trabajo…
        self._move('IN_PROGRESS')
        self.a.refresh_from_db()
        self.assertIsNone(self.a.approved_at)
        self.assertIsNone(self.a.closed_date)

        # …y al re-concluir queda pendiente de aprobación otra vez (no auto-aprobado).
        self.client.force_login(self.dev)
        self.client.post(reverse('tickets:assignment_conclude', args=[self.a.pk]), {'conclusion': 'v2'})
        self.a.refresh_from_db()
        self.assertTrue(self.a.needs_approval)
        self.ticket.refresh_from_db()
        self.assertNotEqual(self.ticket.status, Ticket.Status.DONE)


@override_settings(**OV)
class RejectConclusionTests(TestCase):
    """El coordinador puede rechazar una conclusión con feedback obligatorio: vuelve a
    En progreso, genera comentario y notifica al ejecutor."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.dev = make_user('dev@e.com', Role.EJECUTOR)
        self.ticket = Ticket.objects.create(title='T', reporter=self.coord, has_subproducts=True)
        self.a = Assignment.objects.create(ticket=self.ticket, user=self.dev, kind=Assignment.Kind.EJECUTOR)
        self.ticket.recompute_status()
        self.client.force_login(self.dev)
        self.client.post(reverse('tickets:assignment_conclude', args=[self.a.pk]), {'conclusion': 'listo'})

    def test_reject_returns_to_in_progress_with_feedback(self):
        self.client.force_login(self.coord)
        r = self.client.post(reverse('tickets:reject', args=[self.ticket.pk]), {'feedback': 'Falta el anexo B'})
        self.assertEqual(r.status_code, 302)
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, Ticket.Status.IN_PROGRESS)
        self.assertIsNone(self.a.approved_at)
        self.assertIsNone(self.a.closed_date)
        self.assertTrue(Comment.objects.filter(
            ticket=self.ticket, body__contains='Falta el anexo B').exists())
        self.assertTrue(Notification.objects.filter(
            recipient=self.dev, verb__contains='rechazó tu conclusión').exists())

    def test_reject_without_feedback_changes_nothing(self):
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:reject', args=[self.ticket.pk]), {'feedback': '  '})
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, Ticket.Status.DONE)

    def test_executor_cannot_reject(self):
        self.client.force_login(self.dev)
        r = self.client.post(reverse('tickets:reject', args=[self.ticket.pk]), {'feedback': 'x'})
        self.assertEqual(r.status_code, 403)


@override_settings(**OV)
class ApprovePermissionTests(TestCase):
    """Aprobar exige tickets.close: un ejecutor no puede aprobar su propia conclusión."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.dev = make_user('dev@e.com', Role.EJECUTOR)
        self.ticket = Ticket.objects.create(title='T', reporter=self.dev, has_subproducts=True)
        self.a = Assignment.objects.create(ticket=self.ticket, user=self.dev, kind=Assignment.Kind.EJECUTOR)
        self.ticket.recompute_status()
        self.client.force_login(self.dev)
        self.client.post(reverse('tickets:assignment_conclude', args=[self.a.pk]), {'conclusion': 'ok'})

    def test_executor_cannot_self_approve(self):
        r = self.client.post(reverse('tickets:approve', args=[self.ticket.pk]))
        self.assertEqual(r.status_code, 403)
        self.a.refresh_from_db()
        self.assertIsNone(self.a.approved_at)

    def test_conclusion_notifies_coordinators_not_only_reporter(self):
        # El reporter es el propio ejecutor: sin notificar a quienes tienen tickets.close,
        # ningún coordinador se enteraba de que había algo por aprobar.
        self.assertTrue(Notification.objects.filter(
            recipient=self.coord, verb__contains='pendiente de aprobación').exists())


@override_settings(**OV)
class SuspendPreservesDoneTests(TestCase):
    """Suspender no pisa subtickets concluidos; reactivar restaura el estado previo."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.dev1 = make_user('d1@e.com', Role.EJECUTOR)
        self.dev2 = make_user('d2@e.com', Role.EJECUTOR)
        self.ticket = Ticket.objects.create(title='T', reporter=self.coord, has_subproducts=True)
        self.a1 = Assignment.objects.create(ticket=self.ticket, user=self.dev1, kind=Assignment.Kind.EJECUTOR)
        self.a2 = Assignment.objects.create(ticket=self.ticket, user=self.dev2, kind=Assignment.Kind.EJECUTOR)
        self.ticket.recompute_status()
        # dev1 concluye; el coordinador aprueba su parte.
        self.client.force_login(self.dev1)
        self.client.post(reverse('tickets:assignment_conclude', args=[self.a1.pk]), {'conclusion': 'ok'})
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:approve', args=[self.ticket.pk]))
        # dev2 está trabajando.
        self.a2.advance_to(Ticket.Status.IN_PROGRESS)
        self.a2.save()

    def test_suspend_leaves_done_untouched_and_restore_returns_previous_state(self):
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:suspend', args=[self.ticket.pk]))
        self.a1.refresh_from_db(); self.a2.refresh_from_db()
        self.assertEqual(self.a1.status, Ticket.Status.DONE)       # el concluido no se pisa
        self.assertIsNotNone(self.a1.approved_at)                   # ni pierde la aprobación
        self.assertEqual(self.a2.status, Ticket.Status.WAITING)
        self.assertEqual(self.a2.status_before_suspend, Ticket.Status.IN_PROGRESS)

        self.client.post(reverse('tickets:suspend', args=[self.ticket.pk]))  # reactiva
        self.a1.refresh_from_db(); self.a2.refresh_from_db()
        self.assertEqual(self.a1.status, Ticket.Status.DONE)
        self.assertEqual(self.a2.status, Ticket.Status.IN_PROGRESS)  # no TODO
        self.assertEqual(self.a2.status_before_suspend, '')

    def test_suspend_notifies_participants(self):
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:suspend', args=[self.ticket.pk]))
        self.assertTrue(Notification.objects.filter(
            recipient=self.dev2, verb__contains='suspendió/canceló').exists())


@override_settings(**OV)
class UnassignGuardTests(TestCase):
    """Editar el ticket desmarcando a un ejecutor con trabajo NO borra su Assignment;
    si no tiene trabajo, se borra, se lo notifica y el historial sobrevive (SET_NULL)."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.worked = make_user('worked@e.com', Role.EJECUTOR)
        self.idle = make_user('idle@e.com', Role.EJECUTOR)
        self.ticket = Ticket.objects.create(title='T', solicitante='X', reporter=self.coord,
                                            has_subproducts=True)
        self.a_worked = Assignment.objects.create(
            ticket=self.ticket, user=self.worked, kind=Assignment.Kind.EJECUTOR)
        self.a_idle = Assignment.objects.create(
            ticket=self.ticket, user=self.idle, kind=Assignment.Kind.EJECUTOR)
        self.ticket.recompute_status()
        self.a_worked.advance_to(Ticket.Status.IN_PROGRESS)   # trabajo empezado
        self.a_worked.save()

    def _edit(self, executor_pks):
        self.client.force_login(self.coord)
        return self.client.post(reverse('tickets:edit', args=[self.ticket.pk]), {
            'title': self.ticket.title, 'solicitante': 'X', 'description': '',
            'priority': Ticket.Priority.MEDIUM, 'has_subproducts': 'on',
            'executors': [str(pk) for pk in executor_pks],
        })

    def test_unassign_with_work_is_kept(self):
        self._edit([self.idle.pk])   # desmarca a worked
        self.assertTrue(Assignment.objects.filter(pk=self.a_worked.pk).exists())

    def test_unassign_without_work_deletes_and_notifies(self):
        self._edit([self.worked.pk])   # desmarca a idle (sin started_at)
        self.assertFalse(Assignment.objects.filter(pk=self.a_idle.pk).exists())
        self.assertTrue(Notification.objects.filter(
            recipient=self.idle, verb__contains='te desasignó').exists())

    def test_history_survives_assignment_deletion(self):
        from .models import TicketEvent
        ev = TicketEvent.objects.create(
            ticket=self.ticket, actor=self.idle, kind='status',
            detail='movió su subticket', assignment=self.a_idle)
        self._edit([self.worked.pk])
        ev.refresh_from_db()
        self.assertIsNone(ev.assignment)   # SET_NULL, no CASCADE


@override_settings(**OV)
class ExecutorCannotWaitTests(TestCase):
    """assignment_move rechaza WAITING a quien no ve esa columna (tickets.view_waiting):
    aceptarlo mandaba la tarea a una columna invisible e irreversible para el ejecutor."""

    def setUp(self):
        self.dev = make_user('dev@e.com', Role.EJECUTOR)
        self.ticket = Ticket.objects.create(title='T', reporter=self.dev)
        self.a = Assignment.objects.create(ticket=self.ticket, user=self.dev, kind=Assignment.Kind.EJECUTOR)
        self.ticket.recompute_status()

    def test_waiting_rejected_for_executor(self):
        self.client.force_login(self.dev)
        r = self.client.post(reverse('tickets:assignment_move'),
                             data=json.dumps({'assignment': self.a.pk, 'status': 'WAITING'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, Ticket.Status.TODO)


@override_settings(**OV)
class SuspendedParentChildTests(TestCase):
    """Derivar/dividir un ticket suspendido: el hijo hereda el candado (suspended_at)."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.dev = make_user('dev@e.com', Role.EJECUTOR)
        self.ticket = Ticket.objects.create(title='T', solicitante='X', reporter=self.coord)
        self.a = Assignment.objects.create(ticket=self.ticket, user=self.dev, kind=Assignment.Kind.EJECUTOR)
        self.ticket.recompute_status()
        self.client.force_login(self.coord)
        self.client.post(reverse('tickets:suspend', args=[self.ticket.pk]))
        self.ticket.refresh_from_db()

    def test_derived_child_inherits_lock(self):
        self.client.post(reverse('tickets:derive', args=[self.ticket.pk]))
        child = self.ticket.children.get()
        self.assertIsNotNone(child.suspended_at)
        # Y el ejecutor no puede mover el subticket del hijo.
        child_a = child.assignments.get(user=self.dev)
        self.client.force_login(self.dev)
        r = self.client.post(reverse('tickets:assignment_move'),
                             data=json.dumps({'assignment': child_a.pk, 'status': 'IN_PROGRESS'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)


@override_settings(**OV)
class NotifyDueTicketsCommandTests(TestCase):
    """El command de cron notifica vence-mañana/hoy/venció-ayer y es idempotente en el día."""

    def setUp(self):
        from django.core.management import call_command
        self.call_command = call_command
        self.dev = make_user('dev@e.com', Role.EJECUTOR)
        today = timezone.localdate()
        for delta, title in ((1, 'mañana'), (0, 'hoy'), (-1, 'ayer'), (10, 'lejano')):
            t = Ticket.objects.create(title=title, reporter=self.dev,
                                      due_date=today + timedelta(days=delta))
            Assignment.objects.create(ticket=t, user=self.dev, kind=Assignment.Kind.EJECUTOR)

    def test_notifies_and_is_idempotent(self):
        self.call_command('notify_due_tickets')
        qs = Notification.objects.filter(recipient=self.dev, verb__icontains='venc')
        self.assertEqual(qs.count(), 3)   # mañana, hoy, ayer — no el lejano
        self.call_command('notify_due_tickets')
        self.assertEqual(qs.count(), 3)   # segunda corrida en el día: sin duplicados


class RecomputeStatusCombosTests(TestCase):
    """Regresión de recompute_status(): documenta el comportamiento agregado esperado."""

    def setUp(self):
        self.coord = make_user('coord@e.com', Role.COORDINADOR)
        self.exp = make_user('exp@e.com', Role.EXPERTO)
        self.dev1 = make_user('d1@e.com', Role.EJECUTOR)
        self.dev2 = make_user('d2@e.com', Role.EJECUTOR)

    def test_only_experts_is_backlog(self):
        t = Ticket.objects.create(title='T', reporter=self.coord)
        Assignment.objects.create(ticket=t, user=self.exp, kind=Assignment.Kind.EXPERTO)
        self.assertEqual(t.recompute_status(), Ticket.Status.BACKLOG)

    def test_suspended_wins_even_without_executors(self):
        t = Ticket.objects.create(title='T', reporter=self.coord, suspended_at=timezone.now())
        self.assertEqual(t.recompute_status(), Ticket.Status.WAITING)

    def test_approved_done_plus_waiting_is_in_progress(self):
        t = Ticket.objects.create(title='T', reporter=self.coord, has_subproducts=True)
        Assignment.objects.create(ticket=t, user=self.dev1, kind=Assignment.Kind.EJECUTOR,
                                  status=Ticket.Status.DONE, approved_at=timezone.now())
        Assignment.objects.create(ticket=t, user=self.dev2, kind=Assignment.Kind.EJECUTOR,
                                  status=Ticket.Status.WAITING)
        self.assertEqual(t.recompute_status(), Ticket.Status.IN_PROGRESS)

    def test_all_done_approved_is_done(self):
        t = Ticket.objects.create(title='T', reporter=self.coord)
        Assignment.objects.create(ticket=t, user=self.dev1, kind=Assignment.Kind.EJECUTOR,
                                  status=Ticket.Status.DONE, approved_at=timezone.now())
        self.assertEqual(t.recompute_status(), Ticket.Status.DONE)
