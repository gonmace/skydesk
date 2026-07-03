from django import forms
from django.contrib.auth import get_user_model

from .models import Comment, Project, Ticket

User = get_user_model()

_INPUT = 'input input-bordered w-full'
_TEXTAREA = 'textarea textarea-bordered w-full'
_SELECT = 'select select-bordered w-full'
_CHECKS = 'checkbox checkbox-sm checkbox-primary'


def _user_label(u):
    name = u.get_full_name().strip()
    return f'{name} · {u.email}' if name else (u.email or u.username)


class TicketForm(forms.ModelForm):
    executors = forms.ModelMultipleChoiceField(
        label='Ejecutores', required=False, queryset=User.objects.none(),
        widget=forms.CheckboxSelectMultiple(attrs={'class': _CHECKS}),
        help_text='Uno o varios. Al asignar, el ticket pasa a «Por hacer».',
    )
    experts = forms.ModelMultipleChoiceField(
        label='Expertos', required=False, queryset=User.objects.none(),
        widget=forms.CheckboxSelectMultiple(attrs={'class': _CHECKS}),
        help_text='Opcional (consultores).',
    )

    class Meta:
        model = Ticket
        fields = ('title', 'solicitante', 'description', 'project', 'priority', 'due_date',
                  'labels', 'has_subproducts')
        widgets = {
            'title': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Título del ticket'}),
            'solicitante': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Quién lo solicita'}),
            'description': forms.Textarea(attrs={'class': _TEXTAREA, 'rows': 5}),
            'project': forms.Select(attrs={'class': _SELECT}),
            'priority': forms.Select(attrs={'class': _SELECT}),
            'due_date': forms.DateInput(attrs={'class': _INPUT, 'type': 'date'}, format='%Y-%m-%d'),
            'labels': forms.CheckboxSelectMultiple(),
            'has_subproducts': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary'}),
        }

    def __init__(self, *args, can_assign=True, **kwargs):
        super().__init__(*args, **kwargs)
        from accounts.models import Role
        self.fields['due_date'].input_formats = ['%Y-%m-%d']
        self.fields['executors'].queryset = User.objects.filter(
            is_active=True, profile__role=Role.EJECUTOR).order_by('first_name', 'email')
        self.fields['experts'].queryset = User.objects.filter(
            is_active=True, profile__role=Role.EXPERTO).order_by('first_name', 'email')
        self.fields['executors'].label_from_instance = _user_label
        self.fields['experts'].label_from_instance = _user_label
        if self.instance and self.instance.pk:
            self.fields['executors'].initial = [a.user_id for a in self.instance.executor_assignments]
            self.fields['experts'].initial = [a.user_id for a in self.instance.expert_assignments]
        if not can_assign:
            self.fields.pop('executors', None)
            self.fields.pop('experts', None)


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ('name', 'code', 'city', 'status', 'description')
        widgets = {
            'name': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Nombre del proyecto'}),
            'code': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Código (ej. SUR)'}),
            'city': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Ciudad'}),
            'status': forms.Select(attrs={'class': _SELECT}),
            'description': forms.Textarea(attrs={'class': _TEXTAREA, 'rows': 2}),
        }


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ('body',)
        widgets = {
            'body': forms.Textarea(attrs={
                'class': _TEXTAREA, 'rows': 2, 'placeholder': 'Escribí un mensaje de seguimiento…',
            }),
        }
