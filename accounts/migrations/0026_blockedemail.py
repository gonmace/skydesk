from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0025_profile_extra_companies'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='BlockedEmail',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254, verbose_name='Correo')),
                ('note', models.CharField(blank=True, max_length=255, verbose_name='Nota')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('company', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name='blocked_emails',
                    to='accounts.company',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+', to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Correo bloqueado',
                'verbose_name_plural': 'Correos bloqueados',
                'ordering': ['email'],
            },
        ),
        migrations.AddConstraint(
            model_name='blockedemail',
            constraint=models.UniqueConstraint(
                fields=('company', 'email'), name='accounts_blockedemail_company_email_uniq',
            ),
        ),
    ]
