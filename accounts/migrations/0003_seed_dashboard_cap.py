from django.db import migrations


def seed_missing(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    from accounts.permissions import CAPABILITY_KEYS, DEFAULT_ROLE_CAPS
    # get_or_create: solo agrega capacidades nuevas (ej. dashboard.view) sin pisar
    # los toggles que el superuser ya ajustó para las capacidades existentes.
    for role, enabled_caps in DEFAULT_ROLE_CAPS.items():
        for capability in CAPABILITY_KEYS:
            RolePermission.objects.get_or_create(
                role=role, capability=capability,
                defaults={'enabled': capability in enabled_caps},
            )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_seed_permissions'),
    ]

    operations = [
        migrations.RunPython(seed_missing, migrations.RunPython.noop),
    ]
