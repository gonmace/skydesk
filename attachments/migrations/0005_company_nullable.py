import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Multi-empresa, paso 1: FKs nullable (la data migration accounts.0021 los rellena)."""

    dependencies = [
        ('attachments', '0004_attachment_version_number_attachment_version_of'),
        ('accounts', '0019_company'),
    ]

    operations = [
        migrations.AddField(
            model_name='attachment',
            name='company',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='accounts.company', verbose_name='Empresa'),
        ),
        migrations.AddField(
            model_name='nextcloudconfig',
            name='company',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='nextcloud_config', to='accounts.company'),
        ),
    ]
