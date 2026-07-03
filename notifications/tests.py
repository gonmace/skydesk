from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from tickets.models import Ticket

from .models import Notification

User = get_user_model()


class NotificationsContextProcessorTests(TestCase):
    """El badge de notificaciones (context_processors.notifications) es lazy: no debe
    pegarle a la base si el template no lo usa (ej. 404/500, que no incluyen el dropdown
    de notificaciones, solo tickets/base_app.html lo hace)."""

    def setUp(self):
        self.user = User.objects.create_user('u@e.com', 'u@e.com', 'x', is_active=True)
        self.other = User.objects.create_user('o@e.com', 'o@e.com', 'x', is_active=True)
        self.ticket = Ticket.objects.create(title='t', reporter=self.user)
        Notification.objects.create(recipient=self.user, verb='te asignó', actor=self.other,
                                    ticket=self.ticket)

    def test_anonymous_gets_empty_context(self):
        r = self.client.get(reverse('accounts:login'))
        self.assertEqual(r.status_code, 200)

    def test_board_shows_unread_badge(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse('tickets:board'))
        self.assertContains(r, 'badge-primary')

    def test_404_page_does_not_query_notifications(self):
        """base.html (sin el dropdown de notificaciones) no debe evaluar los lazy objects:
        ninguna query a Notification al pedir una URL inexistente."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        self.client.force_login(self.user)
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get('/esta-url-no-existe/')
        self.assertEqual(r.status_code, 404)
        self.assertFalse(any('notifications_notification' in q['sql'] for q in ctx.captured_queries))
