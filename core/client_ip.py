"""IP real del cliente detrás del proxy.

nginx escribe SIEMPRE `X-Real-IP: $remote_addr` (ver nginx.conf) — el cliente no puede
falsificarla porque nginx la pisa en cada request. `X-Forwarded-For` en cambio se
APPENDEA (`$proxy_add_x_forwarded_for`): su primer elemento es controlado por el
cliente y no sirve para throttling ni lockouts.

Sin esto, django-axes veía siempre 127.0.0.1 detrás de nginx: el lockout quedaba
efectivamente solo-por-username (cualquiera podía bloquear la cuenta de una víctima
con 5 intentos fallidos) y atacantes distintos eran indistinguibles.
"""


def client_ip(request):
    return request.META.get('HTTP_X_REAL_IP', '').strip() or request.META.get('REMOTE_ADDR', '')
