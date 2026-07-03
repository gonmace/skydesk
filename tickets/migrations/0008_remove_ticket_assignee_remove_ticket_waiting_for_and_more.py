import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def assignee_to_assignment(apps, schema_editor):
    Ticket = apps.get_model('tickets', 'Ticket')
    Assignment = apps.get_model('tickets', 'Assignment')
    for t in Ticket.objects.exclude(assignee__isnull=True):
        Assignment.objects.get_or_create(
            ticket=t, user_id=t.assignee_id,
            defaults={'kind': 'EJECUTOR', 'status': t.status},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0007_ticket_archived_at_ticket_code_ticket_parent_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1) Crear el modelo Assignment.
        migrations.CreateModel(
            name='Assignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('EJECUTOR', 'Ejecutor'), ('EXPERTO', 'Experto')], default='EJECUTOR', max_length=10)),
                ('status', models.CharField(choices=[('BACKLOG', 'Necesidad'), ('TODO', 'Por hacer'), ('IN_PROGRESS', 'En progreso'), ('DONE', 'Concluido'), ('WAITING', 'Suspendido/Cancelado')], default='TODO', max_length=20)),
                ('position', models.PositiveIntegerField(default=0)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('closed_date', models.DateTimeField(blank=True, null=True)),
                ('conclusion', models.TextField(blank=True, verbose_name='Conclusión')),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('ticket', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignments', to='tickets.ticket')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignments', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['position', 'created'],
                'unique_together': {('ticket', 'user')},
            },
        ),
        migrations.AddField(
            model_name='ticketevent',
            name='assignment',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='events', to='tickets.assignment'),
        ),
        # 2) Backfill: cada assignee existente → Assignment (ejecutor).
        migrations.RunPython(assignee_to_assignment, migrations.RunPython.noop),
        # 3) Quitar los campos viejos.
        migrations.RemoveField(model_name='ticket', name='assignee'),
        migrations.RemoveField(model_name='ticket', name='waiting_for'),
    ]
