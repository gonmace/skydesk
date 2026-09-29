from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0024_reset_config_sequences'),
    ]

    operations = [
        migrations.AlterField(
            model_name='profile',
            name='company',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=models.deletion.CASCADE,
                related_name='profiles', to='accounts.company', verbose_name='Empresa principal',
            ),
        ),
        migrations.AddField(
            model_name='profile',
            name='extra_companies',
            field=models.ManyToManyField(
                blank=True, related_name='extra_member_profiles', to='accounts.company',
                help_text='Empresas donde el usuario también opera, además de su principal. Mismo rol.',
                verbose_name='Empresas adicionales',
            ),
        ),
    ]
