from django.db import migrations


def seed_missing(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    from accounts.permissions import CAPABILITY_KEYS, DEFAULT_ROLE_CAPS
    # get_or_create: agrega las filas del rol nuevo (ADMINISTRADOR) y la capacidad
    # nueva (tickets.view_backlog) sin pisar los toggles que el superuser ya ajustó.
    # view_backlog reemplaza al gate implícito de tickets.assign sobre la columna
    # Entrada: se siembra habilitada para quien tenga assign habilitado HOY (política
    # vigente en esta DB, no el default de código), para no cambiar lo que ve nadie.
    for role, enabled_caps in DEFAULT_ROLE_CAPS.items():
        for capability in CAPABILITY_KEYS:
            if capability == 'tickets.view_backlog' and role != 'ADMINISTRADOR':
                assign = RolePermission.objects.filter(
                    role=role, capability='tickets.assign').first()
                enabled = bool(assign and assign.enabled)
            else:
                enabled = capability in enabled_caps
            RolePermission.objects.get_or_create(
                role=role, capability=capability,
                defaults={'enabled': enabled},
            )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0014_administrador_role'),
    ]

    operations = [
        migrations.RunPython(seed_missing, migrations.RunPython.noop),
    ]
