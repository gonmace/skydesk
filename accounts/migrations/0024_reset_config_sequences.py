"""Las configs de Nextcloud eran singletons creados con `pk=1` explícito
(`get_or_create(pk=1)`), así que en PostgreSQL sus secuencias `id` nunca avanzaron: al
crear la segunda empresa, `NextcloudConfig.objects.create(company=...)` pedía otra vez
id=1 y chocaba. Se resincronizan las secuencias con el máximo id actual. En SQLite no
hace falta (AUTOINCREMENT ya considera los ids insertados a mano)."""
from django.db import migrations

TABLES = ('accounts_nextcloudoauthconfig', 'attachments_nextcloudconfig', 'accounts_emailconfig')


def reset_sequences(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)"
            )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0023_email_lower_unique'),
        ('attachments', '0006_company_constraints'),
    ]

    operations = [
        migrations.RunPython(reset_sequences, migrations.RunPython.noop),
    ]
