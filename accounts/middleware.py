"""Middlewares de accounts. Solo se registra en settings dentro del bloque `if DEBUG:`."""
from django.conf import settings
from django.contrib.auth import get_user_model

User = get_user_model()


class DevImpersonationMiddleware:
    """Permite al superuser navegar la app siendo realmente otro usuario (solo DEBUG).

    A diferencia de simular un rol, acá se reemplaza `request.user` por el usuario elegido
    (guardado en la sesión como `impersonate_id` por `accounts.views.dev_impersonate`), así
    que la vista ve exactamente lo que ese usuario vería: sus tickets asignados, sus
    notificaciones, su rol real vía `Profile` — no hace falta ningún atajo especial en
    `accounts.permissions`. La sesión autenticada sigue siendo la del superuser; el
    reemplazo es solo en memoria, por request. `request.real_user` guarda al superuser
    real mientras dura la impersonación, para el banner y el link de "Salir".
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.DEBUG:
            real_user = getattr(request, 'user', None)
            if real_user is not None and real_user.is_authenticated and real_user.is_superuser:
                target_id = request.session.get('impersonate_id')
                if target_id:
                    target = User.objects.filter(pk=target_id, is_active=True).first()
                    if target:
                        request.real_user = real_user
                        request.user = target
        return self.get_response(request)
