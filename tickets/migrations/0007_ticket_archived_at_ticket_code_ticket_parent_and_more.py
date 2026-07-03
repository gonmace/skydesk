import django.db.models.deletion
from django.db import migrations, models


def backfill_codes(apps, schema_editor):
    Ticket = apps.get_model('tickets', 'Ticket')
    n = 0
    for t in Ticket.objects.order_by('created', 'pk'):
        n += 1
        t.code = f'SKY-{n:04d}'
        t.save(update_fields=['code'])


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0006_alter_ticket_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Archivado'),
        ),
        migrations.AddField(
            model_name='ticket',
            name='parent',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='children', to='tickets.ticket', verbose_name='Deriva de'),
        ),
        migrations.AddField(
            model_name='ticket',
            name='solicitante',
            field=models.CharField(default='', max_length=150, verbose_name='Solicitante'),
        ),
        # code: agregar sin unique, backfillear correlativo, luego aplicar unique.
        migrations.AddField(
            model_name='ticket',
            name='code',
            field=models.CharField(blank=True, default='', max_length=12, verbose_name='Código'),
        ),
        migrations.RunPython(backfill_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='ticket',
            name='code',
            field=models.CharField(blank=True, default='', max_length=12, unique=True, verbose_name='Código'),
        ),
    ]
