from django.utils.functional import SimpleLazyObject


def notifications(request):
    """Corre en CADA request que renderiza un template (no solo los que muestran el
    dropdown de notificaciones, ej. 404/500) — por eso las 2 queries son lazy: solo se
    ejecutan si el template realmente usa notif_unread/notif_recent (ver
    tickets/base_app.html), no en cada request autenticado sin importar la página."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    return {
        'notif_unread': SimpleLazyObject(lambda: user.notifications.filter(is_read=False).count()),
        'notif_recent': SimpleLazyObject(lambda: list(user.notifications.select_related('actor', 'ticket')[:6])),
    }
