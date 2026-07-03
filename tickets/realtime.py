"""Disparo de eventos en tiempo real (Django Channels) desde código síncrono (vistas).

Diseño de grupos v1 (pragmático): un solo grupo global `'board'` — el evento lleva
solo el id del ticket, sin datos sensibles. El cliente reacciona re-pidiendo
`board_fragment` (ver tickets/views.py, static/js/board-search.js), que YA filtra por
visibilidad server-side (_visible_tickets/roles) — no hay fuga de datos aunque el ping
llegue a alguien sin acceso a ese ticket puntual. Grupos por visibilidad granular quedan
como deuda v2 si la escala lo justifica.

Todo acá es best-effort: si Redis/el channel layer no está disponible (falta en algún
entorno, o los tests no lo configuran), no debe romper la vista que dispara el evento.
"""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def broadcast_board(ticket_id=None):
    """Avisa a todos los clientes conectados que el tablero cambió (y, si se pasa
    ticket_id, a quien tenga abierto el detalle de ese ticket puntual)."""
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)('board', {'type': 'board.changed', 'ticket_id': ticket_id})
        if ticket_id:
            async_to_sync(layer.group_send)(
                f'ticket_{ticket_id}', {'type': 'ticket.changed', 'ticket_id': ticket_id},
            )
    except Exception:
        pass


def broadcast_notification(recipient_id):
    """Avisa al destinatario de una notificación nueva (badge/dropdown en vivo)."""
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(f'notif_{recipient_id}', {'type': 'notif.new'})
    except Exception:
        pass
