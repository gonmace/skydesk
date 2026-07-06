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
    label = f'{name} · {u.email}' if name else (u.email or u.username)
    # Un usuario dado de baja que sigue asignado debe verse (y verse distinto): si no
    # apareciera en el form, guardar cualquier edición lo desasignaría en silencio.
    return label if u.is_active else f'{label} — dado de baja'


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

    def __init__(self, *args, can_assign=True, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from django.db.models import Q

        from accounts.models import Role
        self.fields['due_date'].input_formats = ['%Y-%m-%d']
        # Los ya asignados entran al queryset aunque estén dados de baja: si el checkbox
        # de un inactivo no se renderizara, guardar cualquier edición lo desasignaría
        # en silencio (el form lo interpretaría como desmarcado).
        assigned_exec_ids, assigned_expert_ids = [], []
        if self.instance and self.instance.pk:
            assigned_exec_ids = [a.user_id for a in self.instance.executor_assignments]
            assigned_expert_ids = [a.user_id for a in self.instance.expert_assignments]
        # Coordinadores también elegibles como ejecutores (su card lleva un punto con
        # ping en el tablero/Mis tickets, ver _parent_columns) — pero nunca uno mismo:
        # `user` (quien edita) queda fuera del queryset, así que elegirse a sí mismo
        # tampoco pasa la validación del POST. Si OTRO coordinador ya lo asignó, entra
        # por assigned_exec_ids y sigue visible/tildado al editar.
        coord_q = Q(is_active=True, profile__role=Role.COORDINADOR)
        if user is not None:
            coord_q &= ~Q(pk=user.pk)
        self.fields['executors'].queryset = User.objects.filter(
            Q(is_active=True, profile__role=Role.EJECUTOR) | coord_q
            | Q(pk__in=assigned_exec_ids)
        ).order_by('first_name', 'email')
        self.fields['experts'].queryset = User.objects.filter(
            Q(is_active=True, profile__role=Role.EXPERTO) | Q(pk__in=assigned_expert_ids)
        ).order_by('first_name', 'email')
        self.fields['executors'].label_from_instance = _user_label
        self.fields['experts'].label_from_instance = _user_label
        self.fields['executors'].initial = assigned_exec_ids
        self.fields['experts'].initial = assigned_expert_ids
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
                # min-h-0: DaisyUI fuerza min-height:5rem en .textarea sin importar
                # `rows` — acá lo anulamos para que 1 fila se vea como 1 fila.
                'class': f'{_TEXTAREA} min-h-0', 'rows': 1,
                'placeholder': 'Escribí un mensaje de seguimiento…',
                # id fijo: chat-submit.js lo enfoca tras el POST (ver #chat-compose
                # en tickets/views.py::comment_add).
                'id': 'chat-compose',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # No requerido: comment_add permite mandar solo adjuntos sin texto
        # (views.py valida que haya body o request.FILES antes de guardar).
        self.fields['body'].required = False
