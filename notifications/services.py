from .models import Notification


def notify(recipient, verb, *, actor=None, ticket=None):
    """Crea una notificación in-app. No notifica al propio actor ni a recipients vacíos."""
    if recipient is None:
        return None
    if actor is not None and recipient.pk == getattr(actor, 'pk', None):
        return None
    notification = Notification.objects.create(
        recipient=recipient, actor=actor, verb=verb, ticket=ticket,
    )
    # Chokepoint único de notificaciones: enganchar el push en tiempo real acá cubre
    # todos los llamadores existentes (asignación, comentarios, aprobación, la nueva
    # Necesidad->Por hacer...) sin tocarlos uno por uno. Import diferido para evitar
    # importar el stack de Channels si algún día `notify()` se usa sin Channels instalado.
    from tickets.realtime import broadcast_notification
    broadcast_notification(recipient.pk)
    return notification
