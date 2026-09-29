from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm, PasswordResetForm, SetPasswordForm,
)

from .models import (
    AllowedDomain, AllowedEmail, BlockedEmail, Company, EmailConfig, NextcloudOAuthConfig, Role,
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

    def __init__(self, *args, viewer=None, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        _restrict_role_field(self.fields['default_role'], viewer)

    def clean_domain(self):
        # La unicidad es por (company, domain) y `company` no es campo del form, así que
        # validate_unique() de ModelForm no la chequea: se valida acá para no reventar
        # con IntegrityError al guardar.
        domain = self.cleaned_data['domain'].strip().lower().lstrip('@')
        qs = AllowedDomain.objects.filter(company=self.company, domain=domain)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Ese dominio ya está en la lista.')
        return domain

    def save(self, commit=True):
        if self.company is not None:
            self.instance.company = self.company
        return super().save(commit=commit)


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
    """Editada solo por el superuser (companies:email_config). La contraseña SMTP nunca
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
            'from_email': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Kanban Tickets <noreply@dominio>'}),
            'notify_assignment': forms.CheckboxInput(attrs={'class': _CHECKBOX}),
            'notify_comment': forms.CheckboxInput(attrs={'class': _CHECKBOX}),
        }

    def clean_password(self):
        password = self.cleaned_data.get('password', '').strip()
        return password or (self.instance.password if self.instance else '')


_FILE = 'file-input file-input-bordered w-full'
_COLOR = f'{_INPUT} font-mono uppercase'


class CompanyForm(forms.ModelForm):
    """Alta/edición de una empresa (solo superuser, panel /empresas/). Los archivos
    tienen su checkbox nativo de «Clear» (ClearableFileInput) para volver al default.
    La validación de slug reservado / prefijo vive en Company.clean() y los validators
    del modelo — el ModelForm los corre en _post_clean()."""

    class Meta:
        model = Company
        fields = (
            'name', 'slug', 'ticket_prefix', 'is_active',
            'brand_name', 'logo_light', 'logo_dark', 'favicon',
            'primary_color', 'primary_color_dark', 'accent_color', 'accent_color_dark',
            'email_from_name', 'email_from',
        )
        widgets = {
            'name': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Embol S.A.'}),
            'slug': forms.TextInput(attrs={'class': f'{_INPUT} font-mono', 'placeholder': 'embol'}),
            'ticket_prefix': forms.TextInput(attrs={'class': _COLOR, 'placeholder': 'EMBOL', 'maxlength': 6}),
            'is_active': forms.CheckboxInput(attrs={'class': _CHECKBOX}),
            'brand_name': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Embol'}),
            'logo_light': forms.ClearableFileInput(attrs={'class': _FILE}),
            'logo_dark': forms.ClearableFileInput(attrs={'class': _FILE}),
            'favicon': forms.ClearableFileInput(attrs={'class': _FILE}),
            'primary_color': forms.TextInput(attrs={'class': _COLOR, 'placeholder': '#E4002B', 'maxlength': 7}),
            'primary_color_dark': forms.TextInput(attrs={'class': _COLOR, 'placeholder': '#FF2233', 'maxlength': 7}),
            'accent_color': forms.TextInput(attrs={'class': _COLOR, 'placeholder': '#D1A23C', 'maxlength': 7}),
            'accent_color_dark': forms.TextInput(attrs={'class': _COLOR, 'placeholder': '#D1A23C', 'maxlength': 7}),
            'email_from_name': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Embol Tickets'}),
            'email_from': forms.EmailInput(attrs={'class': _INPUT, 'placeholder': 'tickets@embol.com'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            # El prefijo se puede cambiar (el correlativo sigue), pero el slug ya está en
            # links enviados por correo: se avisa en el help_text del modelo, no se bloquea.
            self.fields['slug'].widget.attrs['data-warn-change'] = '1'

    def _clean_color(self, name):
        value = (self.cleaned_data.get(name) or '').strip().upper()
        return value

    def clean_primary_color(self):
        return self._clean_color('primary_color')

    def clean_primary_color_dark(self):
        return self._clean_color('primary_color_dark')

    def clean_accent_color(self):
        return self._clean_color('accent_color')

    def clean_accent_color_dark(self):
        return self._clean_color('accent_color_dark')

    def clean_slug(self):
        return (self.cleaned_data.get('slug') or '').strip().lower()

    def clean_ticket_prefix(self):
        return (self.cleaned_data.get('ticket_prefix') or '').strip().upper()


class BlockedEmailForm(forms.ModelForm):
    """Correo negado en la empresa aunque su dominio esté permitido."""
    class Meta:
        model = BlockedEmail
        fields = ('email', 'note')
        widgets = {
            'email': forms.EmailInput(attrs={'class': _INPUT, 'placeholder': 'persona@empresa.com'}),
            'note': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Motivo (opcional)'}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if BlockedEmail.objects.filter(company=self.company, email=email).exists():
            raise forms.ValidationError('Ese correo ya está bloqueado.')
        return email

    def save(self, commit=True):
        if self.company is not None:
            self.instance.company = self.company
        return super().save(commit=commit)


class AllowedEmailForm(forms.ModelForm):
    class Meta:
        model = AllowedEmail
        fields = ('email', 'default_role', 'note')
        widgets = {
            'email': forms.EmailInput(attrs={'class': _INPUT, 'placeholder': 'persona@empresa.com'}),
            'default_role': forms.Select(attrs={'class': _SELECT}),
            'note': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Nota (opcional)'}),
        }

    def __init__(self, *args, viewer=None, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        _restrict_role_field(self.fields['default_role'], viewer)

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        qs = AllowedEmail.objects.filter(company=self.company, email=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Ese correo ya está en la lista.')
        return email

    def save(self, commit=True):
        if self.company is not None:
            self.instance.company = self.company
        return super().save(commit=commit)
