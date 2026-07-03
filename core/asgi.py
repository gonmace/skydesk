import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

# get_asgi_application() dispara django.setup() — tiene que correr ANTES de importar
# cualquier cosa que toque modelos/apps (routing, consumers), o revienta con
# AppRegistryNotReady.
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from tickets.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    # AllowedHostsOriginValidator reemplaza la protección CSRF (no aplica a WS).
    # AuthMiddlewareStack resuelve scope['user'] desde la sesión (misma cookie que HTTP).
    'websocket': AllowedHostsOriginValidator(
        AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
    ),
})
