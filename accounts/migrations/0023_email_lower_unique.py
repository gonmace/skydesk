"""Un correo = una cuenta = una empresa (multi-tenant): índice único funcional sobre
LOWER(email) en auth_user. Antes el backend de login toleraba duplicados por mayúsculas
(`EmailBackend.MultipleObjectsReturned`); con empresas separadas eso permitiría que un
mismo correo tuviera cuenta en dos empresas. Si ya hay duplicados, la migración aborta
listándolos para resolverlos a mano (fusionar o borrar) antes de reintentar.
"""
from django.conf import settings
from django.db import migrations
from django.db.models import Count
from django.db.models.functions import Lower


def check_duplicates(apps, schema_editor):
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    dups = list(
        User.objects.exclude(email='').annotate(e=Lower('email'))
        .values('e').annotate(n=Count('id')).filter(n__gt=1).values_list('e', flat=True)
    )
    if dups:
        raise RuntimeError(
            'Hay cuentas con el mismo correo (ignorando mayúsculas): '
            + ', '.join(sorted(dups))
            + '. Fusioná o eliminá las duplicadas y volvé a correr migrate.'
        )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0022_company_constraints'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(check_duplicates, migrations.RunPython.noop),
        migrations.RunSQL(
            sql="CREATE UNIQUE INDEX accounts_user_email_lower_uniq ON auth_user (LOWER(email)) WHERE email <> ''",
            reverse_sql='DROP INDEX IF EXISTS accounts_user_email_lower_uniq',
        ),
    ]
