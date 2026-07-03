from django.db import migrations


def supervisor_to_experto(apps, schema_editor):
    Profile = apps.get_model('accounts', 'Profile')
    RolePermission = apps.get_model('accounts', 'RolePermission')
    AllowedDomain = apps.get_model('accounts', 'AllowedDomain')
    AllowedEmail = apps.get_model('accounts', 'AllowedEmail')

    Profile.objects.filter(role='SUPERVISOR').update(role='EXPERTO')
    AllowedDomain.objects.filter(default_role='SUPERVISOR').update(default_role='EXPERTO')
    AllowedEmail.objects.filter(default_role='SUPERVISOR').update(default_role='EXPERTO')

    # Reemplazar los permisos de SUPERVISOR por los de EXPERTO (nuevos defaults RACI).
    RolePermission.objects.filter(role='SUPERVISOR').delete()
    from accounts.models import Role
    from accounts.permissions import CAPABILITY_KEYS, DEFAULT_ROLE_CAPS
    enabled = DEFAULT_ROLE_CAPS[Role.EXPERTO]
    for capability in CAPABILITY_KEYS:
        RolePermission.objects.get_or_create(
            role='EXPERTO', capability=capability,
            defaults={'enabled': capability in enabled},
        )


def experto_to_supervisor(apps, schema_editor):
    Profile = apps.get_model('accounts', 'Profile')
    AllowedDomain = apps.get_model('accounts', 'AllowedDomain')
    AllowedEmail = apps.get_model('accounts', 'AllowedEmail')
    Profile.objects.filter(role='EXPERTO').update(role='SUPERVISOR')
    AllowedDomain.objects.filter(default_role='EXPERTO').update(default_role='SUPERVISOR')
    AllowedEmail.objects.filter(default_role='EXPERTO').update(default_role='SUPERVISOR')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_seed_projects_cap'),
    ]

    operations = [
        migrations.RunPython(supervisor_to_experto, experto_to_supervisor),
    ]
