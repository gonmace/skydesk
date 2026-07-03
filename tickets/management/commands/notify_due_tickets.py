"""Notifica vencimientos de tickets. Pensado para un cron diario del host:

    0 8 * * *  cd /ruta/al/proyecto && python manage.py notify_due_tickets

(en producción con Docker: `docker exec <container> python manage.py notify_due_tickets`).

Sin esto, `due_date` era 100% visual (badge "vencido" + KPI del dashboard): nadie se
enteraba de un vencimiento sin entrar a mirar. Es idempotente dentro del mismo día —
si el cron corre dos veces, no duplica notificaciones.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from notifications.models import Notification
from notifications.services import notify
from tickets.models import Ticket


class Command(BaseCommand):
    help = 'Notifica tickets que vencen mañana/hoy o vencieron ayer (cron diario).'

    def handle(self, *args, **options):
        today = timezone.localdate()
        targets = [
            (today + timedelta(days=1), 'Vence mañana el ticket'),
            (today, 'Vence hoy el ticket'),
            (today - timedelta(days=1), 'Venció ayer el ticket'),
        ]
        base = Ticket.objects.filter(
            archived_at__isnull=True, split_at__isnull=True,
        ).exclude(status=Ticket.Status.DONE).select_related('reporter').prefetch_related('assignments__user')
        sent = 0
        for due, verb in targets:
            for t in base.filter(due_date=due):
                people = {a.user for a in t.assignments.all() if a.user and a.user.is_active}
                if t.reporter and t.reporter.is_active:
                    people.add(t.reporter)
                for u in people:
                    if Notification.objects.filter(
                        recipient=u, ticket=t, verb=verb, created__date=today,
                    ).exists():
                        continue
                    notify(u, verb, ticket=t)
                    sent += 1
        self.stdout.write(self.style.SUCCESS(f'{sent} notificaciones de vencimiento enviadas.'))
