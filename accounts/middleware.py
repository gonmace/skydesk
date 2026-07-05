"""Middlewares de accounts."""
from django.conf import settings
from django.contrib.auth import get_user_model, logout

User = get_user_model()


class NextcloudUidMismatchMiddleware:
    """Desloguea si la sesión de SkyDesk quedó de otro usuario de Nextcloud.

    SkyDesk se embebe en un iframe dentro de Nextcloud (External Sites), cuya URL puede
    incluir el placeholder `{uid}` para pasar el usuario de Nextcloud actualmente logueado
    ahí (?nc_uid={uid}). La sesión de SkyDesk es independiente de la de Nextcloud — si
    alguien cierra sesión en Nextcloud y entra con otra cuenta, sin este chequeo el iframe
    seguiría mostrando la sesión anterior de SkyDesk. Si `nc_uid` no coincide con el UID de
    Nextcloud guardado en el login (`Profile.nextcloud_uid`, ver accounts.views.
    nextcloud_callback), se cierra la sesión — el login vuelve a mostrar el botón SSO."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        nc_uid = request.GET.get('nc_uid')
        if nc_uid and request.user.is_authenticated:
            profile = getattr(request.user, 'profile', None)
            if profile is None or profile.nextcloud_uid != nc_uid:
                logout(request)
        return self.get_response(request)


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
