import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Multi-empresa, paso 1: FKs nullable (la data migration accounts.0021 los rellena)."""

    dependencies = [
        ('tickets', '0018_alter_project_code'),
        ('accounts', '0019_company'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='company',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='projects', to='accounts.company'),
        ),
        migrations.AddField(
            model_name='label',
            name='company',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='labels', to='accounts.company'),
        ),
        migrations.AddField(
            model_name='ticket',
            name='company',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='tickets', to='accounts.company', verbose_name='Empresa'),
        ),
    ]
