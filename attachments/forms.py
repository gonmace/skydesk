from django import forms

from .models import NextcloudConfig

_INPUT = 'input input-bordered w-full'
_CHECKBOX = 'checkbox checkbox-primary'


class NextcloudConfigForm(forms.ModelForm):
    """Editada solo por el superuser (accounts:nextcloud_config). El token nunca se
    re-muestra: si se deja vacío al guardar, se conserva el valor existente."""
    token = forms.CharField(
        label='App-password', required=False,
        widget=forms.PasswordInput(attrs={
            'class': _INPUT, 'placeholder': 'Dejar en blanco para no cambiar', 'autocomplete': 'new-password',
        }, render_value=False),
        help_text='Se guarda pero nunca se vuelve a mostrar. Dejar vacío conserva el actual.',
    )

    class Meta:
        model = NextcloudConfig
        fields = ('enabled', 'base_url', 'user', 'token', 'root')
        labels = {
            'enabled': 'Usar esta configuración (en vez de la de .env)',
            'base_url': 'URL base (WebDAV)',
            'user': 'Usuario',
            'root': 'Carpeta raíz',
        }
        widgets = {
            'enabled': forms.CheckboxInput(attrs={'class': _CHECKBOX}),
            'base_url': forms.URLInput(attrs={
                'class': _INPUT, 'placeholder': 'https://nube.dominio/remote.php/dav/files/usuario',
            }),
            'user': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'usuario'}),
            'root': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'SkyDesk-Tickets'}),
        }

    def clean_token(self):
        token = self.cleaned_data.get('token', '').strip()
        return token or (self.instance.token if self.instance else '')
