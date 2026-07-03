from django import template

register = template.Library()

AVATAR_COLOR_COUNT = 8


@register.filter
def avatar_color(user):
    """Índice (0-7) de color pastel estable para el avatar de un usuario.

    Se deriva del pk, así que queda fijo desde que el usuario se crea (nunca cambia).
    """
    pk = getattr(user, 'pk', None) or 0
    return pk % AVATAR_COLOR_COUNT
