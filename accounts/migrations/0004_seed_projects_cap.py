from django.db import migrations


def seed_missing(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    from accounts.permissions import CAPABILITY_KEYS, DEFAULT_ROLE_CAPS
    for role, enabled_caps in DEFAULT_ROLE_CAPS.items():
        for capability in CAPABILITY_KEYS:
            RolePermission.objects.get_or_create(
                role=role, capability=capability,
                defaults={'enabled': capability in enabled_caps},
            )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_seed_dashboard_cap'),
    ]

    operations = [
        migrations.RunPython(seed_missing, migrations.RunPython.noop),
    ]
