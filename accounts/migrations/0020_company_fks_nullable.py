import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Paso 1 de 3 del multi-empresa en accounts: los FKs entran nullable para que la
    data migration 0021 pueda asignar la empresa inicial a las filas existentes."""

    dependencies = [
        ('accounts', '0019_company'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='company',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='profiles', to='accounts.company', verbose_name='Empresa'),
        ),
        migrations.AddField(
            model_name='alloweddomain',
            name='company',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='allowed_domains', to='accounts.company'),
        ),
        migrations.AddField(
            model_name='allowedemail',
            name='company',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='allowed_emails', to='accounts.company'),
        ),
        migrations.AddField(
            model_name='rolepermission',
            name='company',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='role_permissions', to='accounts.company'),
        ),
        migrations.AddField(
            model_name='nextcloudoauthconfig',
            name='company',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='nextcloud_oauth', to='accounts.company'),
        ),
    ]
