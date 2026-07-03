from django.db import migrations


def seed_permissions(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    # Importar el catálogo y los defaults desde el código de la app.
    from accounts.permissions import CAPABILITY_KEYS, DEFAULT_ROLE_CAPS

    for role, enabled_caps in DEFAULT_ROLE_CAPS.items():
        for capability in CAPABILITY_KEYS:
            RolePermission.objects.update_or_create(
                role=role,
                capability=capability,
                defaults={'enabled': capability in enabled_caps},
            )


def unseed_permissions(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    RolePermission.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_permissions, unseed_permissions),
    ]
