from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

BOARD_GROUP = 'board'


class LiveConsumer(AsyncJsonWebsocketConsumer):
    """Un socket por pestaña abierta. Se une al grupo global 'board' (todo cambio del
    tablero) y a su grupo personal de notificaciones; opcionalmente se suscribe al
    detalle de un ticket puntual (validando visibilidad antes de unirse)."""

    async def connect(self):
        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            await self.close()
            return
        self.subscribed_tickets = set()
        self.notif_group = f'notif_{user.pk}'
        await self.channel_layer.group_add(BOARD_GROUP, self.channel_name)
        await self.channel_layer.group_add(self.notif_group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(BOARD_GROUP, self.channel_name)
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
            can_see = await database_sync_to_async(self._can_see_ticket)(user, ticket_id)
            if not can_see:
                return
            group = f'ticket_{ticket_id}'
            self.subscribed_tickets.add(group)
            await self.channel_layer.group_add(group, self.channel_name)

    @staticmethod
    def _can_see_ticket(user, ticket_id):
        from .models import Ticket
        from .views import _can_see_ticket
        ticket = Ticket.objects.filter(pk=ticket_id).first()
        return ticket is not None and _can_see_ticket(user, ticket)

    # ── Handlers de grupo (los llama group_send desde tickets/realtime.py) ──────
    async def board_changed(self, event):
        await self.send_json({'type': 'board.changed', 'ticket_id': event.get('ticket_id')})

    async def ticket_changed(self, event):
        await self.send_json({'type': 'ticket.changed', 'ticket_id': event.get('ticket_id')})

    async def notif_new(self, event):
        await self.send_json({'type': 'notif.new'})
