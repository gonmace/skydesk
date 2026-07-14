from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm, PasswordResetForm, SetPasswordForm,
)

from .models import (
    AllowedDomain, AllowedEmail, BrandingConfig, EmailConfig, NextcloudOAuthConfig, Role,
)

_INPUT = 'input input-bordered w-full'
_SELECT = 'select select-bordered w-full'
_CHECKBOX = 'checkbox checkbox-primary'


def role_choices_for(viewer):
    """Roles que `viewer` puede ver/asignar en la gestión de cuentas: el rol
    ADMINISTRADOR (espía solo-lectura) solo existe para el superuser — un coordinador
    con accounts.manage no debe verlo ni poder asignarlo."""
    if viewer is not None and viewer.is_superuser:
        return list(Role.choices)
    return [c for c in Role.choices if c[0] != Role.ADMINISTRADOR]


def _restrict_role_field(field, viewer):
    """Filtra ADMINISTRADOR de las choices de `field` (conserva la opción en blanco de
    los ModelForm) cuando el viewer no es superuser — vale también server-side: un POST
    con ese rol no pasa la validación del form."""
    allowed = {v for v, _ in role_choices_for(viewer)}
    field.choices = [c for c in field.choices if c[0] in allowed or not c[0]]


class RequestAccessForm(forms.Form):
    email = forms.EmailField(
        label='Correo electrónico',
        widget=forms.EmailInput(attrs={
            'class': _INPUT, 'autofocus': True, 'placeholder': 'tu.correo@empresa.com',
        }),
    )

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()


class EmailAuthenticationForm(AuthenticationForm):
    """Login por correo + contraseña, con 'Recordarme'."""
    remember_me = forms.BooleanField(
        label='Recordarme', required=False, initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'checkbox checkbox-primary checkbox-sm'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = 'Correo electrónico'
        self.fields['username'].widget = forms.EmailInput(attrs={
            'class': _INPUT, 'autofocus': True, 'placeholder': 'tu.correo@empresa.com',
        })
        self.fields['password'].widget = forms.PasswordInput(attrs={
            'class': _INPUT, 'placeholder': '••••••••',
        })


class ActivationForm(SetPasswordForm):
    """Nombre, apellido y contraseña al activar la cuenta."""
    first_name = forms.CharField(label='Nombre', max_length=150, widget=forms.TextInput(
        attrs={'class': _INPUT, 'autofocus': True, 'placeholder': 'Nombre'}))
    last_name = forms.CharField(label='Apellido', max_length=150, widget=forms.TextInput(
        attrs={'class': _INPUT, 'placeholder': 'Apellido'}))
    field_order = ['first_name', 'last_name', 'new_password1', 'new_password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('new_password1', 'new_password2'):
            self.fields[name].widget = forms.PasswordInput(attrs={
                'class': _INPUT, 'placeholder': '••••••••',
            })

    def save(self, commit=True):
        self.user.first_name = self.cleaned_data['first_name'].strip()
        self.user.last_name = self.cleaned_data['last_name'].strip()
        return super().save(commit=commit)


class StyledSetPasswordForm(SetPasswordForm):
    """Solo contraseña, para el reseteo (a diferencia de ActivationForm, que además
    pide nombre/apellido para la activación inicial de cuenta)."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('new_password1', 'new_password2'):
            self.fields[name].widget = forms.PasswordInput(attrs={
                'class': _INPUT, 'placeholder': '••••••••',
            })


class ProfileNameForm(forms.ModelForm):
    """Editar nombre y apellido del propio usuario."""
    class Meta:
        model = get_user_model()
        fields = ('first_name', 'last_name')
        labels = {'first_name': 'Nombre', 'last_name': 'Apellido'}
        widgets = {
            'first_name': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Nombre'}),
            'last_name': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Apellido'}),
        }


class AdminUserEditForm(forms.ModelForm):
    """El superuser (o un coordinador con accounts.manage) edita nombre, apellido y
    rol de un usuario — para no-superusers el rol ADMINISTRADOR no se ofrece ni valida."""
    role = forms.ChoiceField(label='Rol', choices=Role.choices,
                             widget=forms.Select(attrs={'class': _SELECT}))

    class Meta:
        model = get_user_model()
        fields = ('first_name', 'last_name')
        labels = {'first_name': 'Nombre', 'last_name': 'Apellido'}
        widgets = {
            'first_name': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Nombre'}),
            'last_name': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Apellido'}),
        }

    def __init__(self, *args, viewer=None, **kwargs):
        super().__init__(*args, **kwargs)
        _restrict_role_field(self.fields['role'], viewer)
        if self.instance and self.instance.pk:
            prof = getattr(self.instance, 'profile', None)
            self.fields['role'].initial = prof.role if prof else Role.EJECUTOR


class StyledPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].widget = forms.EmailInput(attrs={
            'class': _INPUT, 'autofocus': True, 'placeholder': 'tu.correo@empresa.com',
        })


class InviteForm(forms.Form):
    email = forms.EmailField(
        label='Correo a invitar',
        widget=forms.EmailInput(attrs={'class': _INPUT, 'placeholder': 'persona@empresa.com'}),
    )
    role = forms.ChoiceField(
        label='Rol', choices=Role.choices, initial=Role.EJECUTOR,
        widget=forms.Select(attrs={'class': _SELECT}),
    )

    def __init__(self, *args, viewer=None, **kwargs):
        super().__init__(*args, **kwargs)
        _restrict_role_field(self.fields['role'], viewer)

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()


class AllowedDomainForm(forms.ModelForm):
    class Meta:
        model = AllowedDomain
        fields = ('domain', 'default_role', 'note')
        widgets = {
            'domain': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'empresa.com'}),
            'default_role': forms.Select(attrs={'class': _SELECT}),
            'note': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Nota (opcional)'}),
        }

    def __init__(self, *args, viewer=None, **kwargs):
        super().__init__(*args, **kwargs)
        _restrict_role_field(self.fields['default_role'], viewer)


class NextcloudOAuthConfigForm(forms.ModelForm):
    """Editada solo por el superuser (accounts:nextcloud_config). El client_secret nunca
    se re-muestra: si se deja vacío al guardar, se conserva el valor existente."""
    client_secret = forms.CharField(
        label='Client secret', required=False,
        widget=forms.PasswordInput(attrs={
            'class': _INPUT, 'placeholder': 'Dejar en blanco para no cambiar', 'autocomplete': 'new-password',
        }, render_value=False),
        help_text='Se guarda pero nunca se vuelve a mostrar. Dejar vacío conserva el actual.',
    )

    class Meta:
        model = NextcloudOAuthConfig
        fields = (
            'enabled', 'base_url', 'client_id', 'client_secret',
            'authorize_url', 'token_url', 'userinfo_url',
        )
        labels = {
            'enabled': 'Permitir "Iniciar sesión con Nextcloud"',
            'base_url': 'URL base de Nextcloud',
            'client_id': 'Client ID',
        }
        widgets = {
            'enabled': forms.CheckboxInput(attrs={'class': _CHECKBOX}),
            'base_url': forms.URLInput(attrs={'class': _INPUT, 'placeholder': 'https://nube.dominio'}),
            'client_id': forms.TextInput(attrs={'class': _INPUT}),
            'authorize_url': forms.TextInput(attrs={'class': _INPUT, 'placeholder': '(default derivado de la URL base)'}),
            'token_url': forms.TextInput(attrs={'class': _INPUT, 'placeholder': '(default derivado de la URL base)'}),
            'userinfo_url': forms.TextInput(attrs={'class': _INPUT, 'placeholder': '(default derivado de la URL base)'}),
        }

    def clean_client_secret(self):
        secret = self.cleaned_data.get('client_secret', '').strip()
        return secret or (self.instance.client_secret if self.instance else '')


class EmailConfigForm(forms.ModelForm):
    """Editada solo por el superuser (accounts:email_config). La contraseña SMTP nunca
    se re-muestra: si se deja vacía al guardar, se conserva el valor existente."""
    password = forms.CharField(
        label='Contraseña', required=False,
        widget=forms.PasswordInput(attrs={
            'class': _INPUT, 'placeholder': 'Dejar en blanco para no cambiar', 'autocomplete': 'new-password',
        }, render_value=False),
        help_text='Se guarda pero nunca se vuelve a mostrar. Dejar vacía conserva la actual.',
    )

    class Meta:
        model = EmailConfig
        fields = (
            'enabled', 'host', 'port', 'use_tls', 'username', 'password',
            'from_email', 'notify_assignment', 'notify_comment',
        )
        widgets = {
            'enabled': forms.CheckboxInput(attrs={'class': _CHECKBOX}),
            'host': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'smtp.dominio.com'}),
            'port': forms.NumberInput(attrs={'class': _INPUT, 'min': 1, 'max': 65535}),
            'use_tls': forms.CheckboxInput(attrs={'class': _CHECKBOX}),
            'username': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'usuario@dominio.com'}),
            'from_email': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'SkyDesk Tickets <noreply@dominio>'}),
            'notify_assignment': forms.CheckboxInput(attrs={'class': _CHECKBOX}),
            'notify_comment': forms.CheckboxInput(attrs={'class': _CHECKBOX}),
        }

    def clean_password(self):
        password = self.cleaned_data.get('password', '').strip()
        return password or (self.instance.password if self.instance else '')


class BrandingConfigForm(forms.ModelForm):
    """Editada solo por el superuser (accounts:branding_config). Cada campo tiene su
    checkbox nativo de «Clear» (ClearableFileInput) para volver al logo por defecto."""

    class Meta:
        model = BrandingConfig
        fields = ('logo_light', 'logo_dark')
        widgets = {
            'logo_light': forms.ClearableFileInput(attrs={'class': 'file-input file-input-bordered w-full'}),
            'logo_dark': forms.ClearableFileInput(attrs={'class': 'file-input file-input-bordered w-full'}),
        }


class AllowedEmailForm(forms.ModelForm):
    class Meta:
        model = AllowedEmail
        fields = ('email', 'default_role', 'note')
        widgets = {
            'email': forms.EmailInput(attrs={'class': _INPUT, 'placeholder': 'persona@empresa.com'}),
            'default_role': forms.Select(attrs={'class': _SELECT}),
            'note': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Nota (opcional)'}),
        }

    def __init__(self, *args, viewer=None, **kwargs):
        super().__init__(*args, **kwargs)
        _restrict_role_field(self.fields['default_role'], viewer)
