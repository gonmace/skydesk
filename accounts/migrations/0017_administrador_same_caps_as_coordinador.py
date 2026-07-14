from django.db import migrations


def sync_administrador_with_coordinador(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    # Copia el valor ACTUAL de cada capacidad de Coordinador (no el default de código:
    # el superuser pudo haber tocado el tablero de toggles) para que Administrador quede
    # con exactamente los mismos privilegios. Lo que lo distingue de Coordinador sigue
    # siendo el código (nunca asignable/participante en tickets, no listado en
    # /acceso/admin/), no esta matriz de capacidades.
    coordinador_caps = dict(
        RolePermission.objects.filter(role='COORDINADOR').values_list('capability', 'enabled')
    )
    for capability, enabled in coordinador_caps.items():
        RolePermission.objects.update_or_create(
            role='ADMINISTRADOR', capability=capability,
            defaults={'enabled': enabled},
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0016_seed_accounts_manage_cap'),
    ]

    operations = [
        migrations.RunPython(sync_administrador_with_coordinador, noop),
    ]
