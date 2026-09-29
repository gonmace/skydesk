from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .realtime import board_group


class LiveConsumer(AsyncJsonWebsocketConsumer):
    """Un socket por pestaña abierta. Se une al grupo de tablero DE SU EMPRESA (todo
    cambio del tablero) y a su grupo personal de notificaciones; opcionalmente se
    suscribe al detalle de un ticket puntual (validando visibilidad antes de unirse).

    El WS vive en /ws/live/ sin prefijo de empresa: la página manda `?company=<slug>`
    (data-company en <html>, ver static/js/live.js). Se acepta si el usuario es miembro
    de esa empresa (principal o adicional) o superuser; si no viene o no es miembro, se
    cae a la empresa principal del Profile."""

    async def connect(self):
        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            await self.close()
            return
        self.subscribed_tickets = set()
        self.notif_group = f'notif_{user.pk}'
        self.company_id = await database_sync_to_async(self._resolve_company_id)(user)
        self.board_group = board_group(self.company_id) if self.company_id else None
        if self.board_group:
            await self.channel_layer.group_add(self.board_group, self.channel_name)
        await self.channel_layer.group_add(self.notif_group, self.channel_name)
        await self.accept()

    def _resolve_company_id(self, user):
        from accounts.models import Company
        from accounts.tenancy import is_member

        slug = parse_qs(self.scope.get('query_string', b'').decode()).get('company', [''])[0]
        requested = None
        if slug:
            requested = Company.objects.filter(slug=slug, is_active=True).values_list('pk', flat=True).first()
        if requested is not None and (user.is_superuser or is_member(user, requested)):
            company_id = requested
        else:
            profile = getattr(user, 'profile', None)
            company_id = profile.company_id if profile is not None else None
        if company_id and not user.is_superuser:
            # Misma empresa activa que en el request HTTP: las capacidades que consulta
            # _can_see_ticket se resuelven con la matriz de ESTA empresa.
            user.__dict__['_active_company_id'] = company_id
        return company_id

    async def disconnect(self, code):
        if getattr(self, 'board_group', None):
            await self.channel_layer.group_discard(self.board_group, self.channel_name)
        if getattr(self, 'notif_group', None):
            await self.channel_layer.group_discard(self.notif_group, self.channel_name)
        for group in getattr(self, 'subscribed_tickets', ()):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if content.get('action') == 'subscribe_ticket':
            ticket_id = content.get('id')
            if not isinstance(ticket_id, int):
                return
            user = self.scope['user']
            can_see = await database_sync_to_async(self._can_see_ticket)(user, ticket_id, self.company_id)
            if not can_see:
                return
            group = f'ticket_{ticket_id}'
            self.subscribed_tickets.add(group)
            await self.channel_layer.group_add(group, self.channel_name)

    @staticmethod
    def _can_see_ticket(user, ticket_id, company_id):
        from .models import Ticket
        from .views import _can_see_ticket
        ticket = Ticket.objects.filter(pk=ticket_id, company_id=company_id).first()
        return ticket is not None and _can_see_ticket(user, ticket)

    # ── Handlers de grupo (los llama group_send desde tickets/realtime.py) ──────
    async def board_changed(self, event):
        await self.send_json({'type': 'board.changed', 'ticket_id': event.get('ticket_id')})

    async def ticket_changed(self, event):
        await self.send_json({'type': 'ticket.changed', 'ticket_id': event.get('ticket_id')})

    async def comment_new(self, event):
        await self.send_json({'type': 'comment.new', 'ticket_id': event.get('ticket_id')})

    async def notif_new(self, event):
        await self.send_json({'type': 'notif.new'})
