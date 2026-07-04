from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

# URLs con esquema http(s) o que arrancan con www. Acepta cualquier carácter no
# blanco/ón-flecha; el resto se escapa así no hay riesgo de HTML arbitrario.
_URL_RE = __import__('re').compile(
    r'(?P<url>(?:https?://|www\.)[^\s<>"\']+)',
)

_DISPLAY_LIMIT = 60


def _shorten(url):
    if len(url) <= _DISPLAY_LIMIT:
        return url
    half = (_DISPLAY_LIMIT - 1) // 2
    return url[:half] + '…' + url[-half:]


@register.filter(name='urlize_chat')
def urlize_chat(value):
    """Convierte URLs del texto en <a> clickeables (target=_blank, noopener).

    Escapa el resto del texto (Django's escape) y marca el resultado como seguro.
    Compatible con whitespace-pre-wrap: preserva \\n y espacios."""
    if not value:
        return value
    safe = []
    last = 0
    for m in _URL_RE.finditer(value):
        # Texto entre la URL anterior y esta: escapar tal cual.
        safe.append(escape(value[last:m.start()]))
        url = m.group('url')
        href = url if url.startswith(('http://', 'https://')) else 'https://' + url
        display = _shorten(url)
        safe.append(
            f'<a href="{escape(href)}" '
            'class="link link-primary break-all" '
            'target="_blank" rel="noopener noreferrer">'
            f'{escape(display)}</a>'
        )
        last = m.end()
    safe.append(escape(value[last:]))
    return mark_safe(''.join(safe))