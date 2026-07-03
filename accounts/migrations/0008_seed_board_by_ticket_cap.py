from django.db import migrations


def seed_and_reset(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    from accounts.permissions import CAPABILITY_KEYS, DEFAULT_ROLE_CAPS

    # get_or_create: solo agrega la capacidad nueva (tickets.board_by_ticket) sin pisar
    # los toggles que el superuser ya ajustó para las capacidades existentes.
    for role, enabled_caps in DEFAULT_ROLE_CAPS.items():
        for capability in CAPABILITY_KEYS:
            RolePermission.objects.get_or_create(
                role=role, capability=capability,
                defaults={'enabled': capability in enabled_caps},
            )

    # Cambio de política explícito (no un "agregar si falta"): Experto deja de "ver todos
    # los tickets" y de "ver el chat de cualquier tarea" — ahora solo ve los tickets en los
    # que participa. Estas dos filas ya existían con enabled=True desde 0002/0003, así que
    # hace falta forzarlas a False (get_or_create no las tocaría).
    RolePermission.objects.update_or_create(
        role='EXPERTO', capability='tickets.view_all', defaults={'enabled': False},
    )
    RolePermission.objects.update_or_create(
        role='EXPERTO', capability='chat.view_all', defaults={'enabled': False},
    )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_seed_view_waiting_cap'),
    ]

    operations = [
        migrations.RunPython(seed_and_reset, migrations.RunPython.noop),
    ]
