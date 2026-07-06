"""Tests del WebSocket de tiempo real (Django Channels). Usa InMemoryChannelLayer para
no depender de un Redis real durante los tests."""
import asyncio

from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TransactionTestCase, override_settings

from accounts.models import Profile, Role
from tickets.consumers import LiveConsumer
from tickets.models import Ticket

User = get_user_model()

_IN_MEMORY_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


def make_user(email, role=Role.EJECUTOR):
    u = User.objects.create_user(email, email, 'x', is_active=True)
    Profile.objects.update_or_create(user=u, defaults={'role': role})
    return u


@override_settings(CHANNEL_LAYERS=_IN_MEMORY_LAYERS)
class LiveConsumerTests(TransactionTestCase):
    async def test_anonymous_connection_rejected(self):
        communicator = WebsocketCommunicator(LiveConsumer.as_asgi(), '/ws/live/')
        communicator.scope['user'] = AnonymousUser()
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

    async def test_authenticated_user_receives_board_broadcast(self):
        user = await self._make_user('ej@e.com')
        communicator = WebsocketCommunicator(LiveConsumer.as_asgi(), '/ws/live/')
        communicator.scope['user'] = user
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        layer = get_channel_layer()
        await layer.group_send('board', {'type': 'board.changed', 'ticket_id': 42})
        event = await communicator.receive_json_from()
        self.assertEqual(event, {'type': 'board.changed', 'ticket_id': 42})
        await communicator.disconnect()

    async def test_authenticated_user_receives_own_notification(self):
        user = await self._make_user('ej2@e.com')
        communicator = WebsocketCommunicator(LiveConsumer.as_asgi(), '/ws/live/')
        communicator.scope['user'] = user
        await communicator.connect()

        layer = get_channel_layer()
        await layer.group_send(f'notif_{user.pk}', {'type': 'notif.new'})
        event = await communicator.receive_json_from()
        self.assertEqual(event, {'type': 'notif.new'})
        await communicator.disconnect()

    async def test_subscribe_ticket_requires_visibility(self):
        owner = await self._make_user('owner@e.com')
        outsider = await self._make_user('outsider@e.com')
        ticket = await self._make_ticket('Solo del owner', owner)

        communicator = WebsocketCommunicator(LiveConsumer.as_asgi(), '/ws/live/')
        communicator.scope['user'] = outsider
        await communicator.connect()
        await communicator.send_json_to({'action': 'subscribe_ticket', 'id': ticket.pk})
        await asyncio.sleep(0.2)   # darle tiempo al chequeo de visibilidad (DB) antes de emitir

        layer = get_channel_layer()
        await layer.group_send(f'ticket_{ticket.pk}', {'type': 'ticket.changed', 'ticket_id': ticket.pk})
        # El outsider no pudo suscribirse (no ve el ticket) -> no debe recibir nada.
        self.assertTrue(await communicator.receive_nothing(timeout=0.3))
        await communicator.disconnect()

    async def test_subscribe_ticket_succeeds_for_participant(self):
        owner = await self._make_user('owner2@e.com')
        ticket = await self._make_ticket('Del owner', owner)

        communicator = WebsocketCommunicator(LiveConsumer.as_asgi(), '/ws/live/')
        communicator.scope['user'] = owner
        await communicator.connect()
        await communicator.send_json_to({'action': 'subscribe_ticket', 'id': ticket.pk})
        await asyncio.sleep(0.2)   # darle tiempo al chequeo de visibilidad (DB) antes de emitir

        layer = get_channel_layer()
        await layer.group_send(f'ticket_{ticket.pk}', {'type': 'ticket.changed', 'ticket_id': ticket.pk})
        event = await communicator.receive_json_from()
        self.assertEqual(event, {'type': 'ticket.changed', 'ticket_id': ticket.pk})
        await communicator.disconnect()

    async def test_subscriber_receives_comment_new(self):
        owner = await self._make_user('owner3@e.com')
        ticket = await self._make_ticket('Con chat', owner)

        communicator = WebsocketCommunicator(LiveConsumer.as_asgi(), '/ws/live/')
        communicator.scope['user'] = owner
        await communicator.connect()
        await communicator.send_json_to({'action': 'subscribe_ticket', 'id': ticket.pk})
        await asyncio.sleep(0.2)   # darle tiempo al chequeo de visibilidad (DB) antes de emitir

        layer = get_channel_layer()
        await layer.group_send(f'ticket_{ticket.pk}', {'type': 'comment.new', 'ticket_id': ticket.pk})
        event = await communicator.receive_json_from()
        self.assertEqual(event, {'type': 'comment.new', 'ticket_id': ticket.pk})
        await communicator.disconnect()

    @staticmethod
    async def _make_user(email):
        from asgiref.sync import sync_to_async
        return await sync_to_async(make_user)(email)

    @staticmethod
    async def _make_ticket(title, reporter):
        from asgiref.sync import sync_to_async

        def _create():
            return Ticket.objects.create(title=title, reporter=reporter)
        return await sync_to_async(_create)()
