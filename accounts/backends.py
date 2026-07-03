"""Backend de autenticación por correo (case-insensitive)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """Autentica con el email como identificador.

    El form de login pasa el correo en el parámetro `username` (compatible con
    django-axes, que registra ese valor para el lockout). Se busca el usuario por
    email de forma case-insensitive y se valida la contraseña + estado activo.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        email = username or kwargs.get('email')
        if email is None or password is None:
            return None
        try:
            user = UserModel.objects.get(email__iexact=email.strip())
        except UserModel.DoesNotExist:
            # Mantener constante el tiempo de respuesta (mitiga enumeración de usuarios).
            UserModel().set_password(password)
            return None
        except UserModel.MultipleObjectsReturned:
            user = UserModel.objects.filter(email__iexact=email.strip()).order_by('id').first()
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
