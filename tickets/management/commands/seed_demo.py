"""Carga datos de demo ("datajunk") cubriendo todas las alternativas del modelo de datos:
los 5 estados y las 4 prioridades de ticket, tickets con/sin proyecto (y proyecto en cada
estado: activo/pausado/cerrado), los 7 colores de etiqueta, ambos tipos de asignación
(ejecutor/experto) en configuración solitaria y combinada, los 4 estados de subticket
(incluye pendiente y ya aprobado), tickets con subproductos independientes vs. tarea
colaborativa compartida, vencimientos futuros/vencidos/sin vencer, un ticket derivado
("Deriva de") de otro, un ticket archivado, historial de eventos con los 8 tipos que usa
la vista, adjuntos (imagen y PDF) en ticket y en comentario, y notificaciones con/sin
actor y con/sin ticket. Es idempotente: borra los tickets de demo previos (título que
empieza con "[demo]") y sus adjuntos en disco antes de recrearlos.

    python manage.py seed_demo
    python manage.py seed_demo --clear   # solo limpia los datos de demo
"""
import io
import os
import shutil
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import AllowedDomain, AllowedEmail, Profile, Role
from attachments import services as attachment_services
from notifications.models import Notification
from notifications.services import notify
from tickets.models import Assignment, Comment, Label, Project, Ticket, TicketEvent

User = get_user_model()
PASSWORD = 'Demo1234!'
DOMAIN = 'empresa.com'
ATTACHMENT_BACKEND = 'local'  # disco bajo private_attachments/demo_attachments — no depende de Nextcloud

# Nombres con iniciales únicas entre sí (el avatar muestra 2 letras: 1ra de nombre +
# 1ra de apellido — con "Elena Ejecuta"/"Elías Ejecuta"/etc. todos daban "EE" y no se
# podían distinguir en el tablero). Apellidos variados en vez de uno fijo por rol.
DEMO_USERS = [
    ('coordinador@empresa.com', Role.COORDINADOR, 'Ana', 'Ferreyra'),
    ('coordinador2@empresa.com', Role.COORDINADOR, 'Carlos', 'Medina'),
    ('experto@empresa.com', Role.EXPERTO, 'Julieta', 'Sosa'),
    ('experto2@empresa.com', Role.EXPERTO, 'Martín', 'Aguirre'),
    ('experto3@empresa.com', Role.EXPERTO, 'Valeria', 'Blanco'),
    ('ejecutor@empresa.com', Role.EJECUTOR, 'Diego', 'Torres'),
    ('ejecutor2@empresa.com', Role.EJECUTOR, 'Lucía', 'Ramos'),
    ('ejecutor3@empresa.com', Role.EJECUTOR, 'Nicolás', 'Vega'),
    ('ejecutor4@empresa.com', Role.EJECUTOR, 'Camila', 'Ortiz'),
    ('ejecutor5@empresa.com', Role.EJECUTOR, 'Federico', 'Paz'),
    ('seguimiento@empresa.com', Role.SEGUIMIENTO, 'Rocío', 'Molina'),
    ('seguimiento2@empresa.com', Role.SEGUIMIENTO, 'Tomás', 'Herrera'),
]

S = Ticket.Status
P = Ticket.Priority
AK = Assignment.Kind


def _fake_image(name, color):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (240, 160), color).save(buf, 'PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


def _fake_pdf(name, text):
    import fitz
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return SimpleUploadedFile(name, data, content_type='application/pdf')


class Command(BaseCommand):
    help = 'Carga datos de demostración cubriendo todas las alternativas del dominio.'

    def add_arguments(self, parser):
        parser.add_argument('--clear', action='store_true', help='Solo borrar los datos de demo.')

    def handle(self, *args, **opts):
        deleted, _ = Ticket.objects.filter(title__startswith='[demo] ').delete()
        if deleted:
            self.stdout.write(f'Borrados {deleted} objeto(s) de demo previos.')
        demo_attach_dir = os.path.join(settings.BASE_DIR, 'private_attachments', 'demo_attachments')
        shutil.rmtree(demo_attach_dir, ignore_errors=True)
        if opts['clear']:
            self.stdout.write(self.style.SUCCESS('Listo (solo limpieza).'))
            return

        AllowedDomain.objects.get_or_create(
            domain=DOMAIN, defaults={'is_active': True, 'note': 'Dominio de demo'},
        )
        # Alternativa a AllowedDomain: un correo puntual habilitado sin pertenecer a un
        # dominio permitido (flujo de invitación por excepción).
        AllowedEmail.objects.get_or_create(
            email='invitado@partner-externo.com',
            defaults={
                'is_active': True, 'default_role': Role.SEGUIMIENTO,
                'note': 'Acceso puntual de demo (alternativa a AllowedDomain)',
            },
        )

        users = {}
        for email, role, first, last in DEMO_USERS:
            user, created = User.objects.get_or_create(
                username=email, defaults={'email': email, 'is_active': True},
            )
            if created:
                user.set_password(PASSWORD)
            user.is_active = True
            user.first_name = first
            user.last_name = last
            user.save()
            Profile.objects.update_or_create(user=user, defaults={'role': role})
            users[email] = user
        coord = users['coordinador@empresa.com']
        coord2 = users['coordinador2@empresa.com']
        experto = users['experto@empresa.com']
        experto2 = users['experto2@empresa.com']
        experto3 = users['experto3@empresa.com']
        ejecutor = users['ejecutor@empresa.com']
        ejecutor2 = users['ejecutor2@empresa.com']
        ejecutor3 = users['ejecutor3@empresa.com']
        ejecutor4 = users['ejecutor4@empresa.com']
        ejecutor5 = users['ejecutor5@empresa.com']
        seguimiento = users['seguimiento@empresa.com']
        seguimiento2 = users['seguimiento2@empresa.com']

        # Notificaciones previas de las cuentas demo (idempotencia).
        Notification.objects.filter(recipient__in=users.values()).delete()

        # Etiquetas: los 7 colores disponibles.
        label_specs = [
            ('infra', Label.Color.INFO), ('bug', Label.Color.ERROR),
            ('docs', Label.Color.NEUTRAL), ('seguridad', Label.Color.WARNING),
            ('destacado', Label.Color.ACCENT), ('legacy', Label.Color.SECONDARY),
            ('validado', Label.Color.SUCCESS),
        ]
        labels = {}
        for name, color in label_specs:
            labels[name], _ = Label.objects.get_or_create(name=name, defaults={'color': color})

        # Proyectos: los 3 estados posibles + tickets sin proyecto (ver más abajo).
        project_specs = [
            ('Red Sur', 'SUR', 'Córdoba', Project.Status.ACTIVE),
            ('Migración Cloud', 'CLOUD', 'Buenos Aires', Project.Status.ACTIVE),
            ('Auditoría 2026', 'AUD', 'Rosario', Project.Status.PAUSED),
            ('Archivo Histórico', 'HIST', 'La Plata', Project.Status.CLOSED),
        ]
        proj = {}
        for name, code, city, status in project_specs:
            p, _ = Project.objects.get_or_create(
                code=code, defaults={'name': name, 'city': city, 'status': status},
            )
            proj[code] = p

        today = timezone.localdate()
        now = timezone.now()

        def mk_ticket(title, *, status, priority, reporter, solicitante, project=None,
                      label_names=(), due_offset=None, has_subproducts=False,
                      parent=None, archived=False, suspended=False):
            kwargs = dict(
                title=f'[demo] {title}', solicitante=solicitante,
                description='Ticket de demostración para explorar el tablero, el chat de '
                            'seguimiento y los permisos por rol.',
                status=status, priority=priority, has_subproducts=has_subproducts,
                reporter=reporter, project=project,
                due_date=today + timedelta(days=due_offset) if due_offset is not None else None,
                closed_date=now if status == S.DONE else None,
                archived_at=now if archived else None,
                suspended_at=now if suspended else None,
            )
            # Con parent, usar create_child para que el código quede jerárquico
            # (<código del padre>-N), igual que producen los botones "Dividir"/"Derivar".
            t = parent.create_child(**kwargs) if parent else Ticket.objects.create(**kwargs)
            if label_names:
                t.labels.set([labels[n] for n in label_names])
            TicketEvent.objects.create(ticket=t, actor=reporter, kind='created', detail='creó el ticket')
            return t

        def assign(ticket, user, *, kind=AK.EJECUTOR, status=S.TODO,
                   started=False, closed=False, approved=False, conclusion=''):
            return Assignment.objects.create(
                ticket=ticket, user=user, kind=kind, status=status,
                started_at=now if started else None,
                closed_date=now if closed else None,
                approved_at=now if approved else None,
                conclusion=conclusion,
            )

        # 1) Entrada sin proyecto ni etiquetas ni asignaciones — el caso mínimo.
        # Solo el Coordinador puede crear tickets (tickets.create): el reporter SIEMPRE
        # es un Coordinador, aunque el pedido venga de otra área (ver `solicitante`).
        mk_ticket(
            'Configurar VPN para el equipo remoto', status=S.BACKLOG, priority=P.LOW,
            reporter=coord, solicitante='Mesa de Ayuda Interna',
        )

        # 2) Entrada con un experto asignado y ningún ejecutor (sigue en Entrada).
        t2 = mk_ticket(
            'Definir política de backups offsite', status=S.BACKLOG, priority=P.MEDIUM,
            reporter=coord, solicitante='Gerencia de Operaciones',
            project=proj['SUR'], label_names=['docs'],
        )
        assign(t2, experto, kind=AK.EXPERTO, status=S.TODO)

        # 3) Por hacer, próximo a vencer.
        t3 = mk_ticket(
            'Migrar la base de datos a PostgreSQL 16', status=S.TODO, priority=P.HIGH,
            reporter=coord, solicitante='Dirección de Sistemas',
            project=proj['CLOUD'], label_names=['infra', 'bug'], due_offset=3,
        )
        assign(t3, ejecutor, status=S.TODO)
        assign(t3, experto2, kind=AK.EXPERTO, status=S.TODO)
        Comment.objects.create(
            ticket=t3, author=ejecutor, body='Hago el ensayo en staging este viernes a la noche.',
        )
        TicketEvent.objects.create(ticket=t3, actor=coord, kind='due', detail='cambió el vencimiento a %s' % (today + timedelta(days=3)))

        # 4) Por hacer, sin proyecto, pedido derivado de un aviso de Seguimiento.
        t4 = mk_ticket(
            'Documentar el proceso de despliegue', status=S.TODO, priority=P.LOW,
            reporter=coord2, solicitante='Gerencia de Operaciones', label_names=['docs'],
        )
        assign(t4, coord, status=S.TODO)

        # 5) En progreso, con subproductos (subtickets independientes): un ejecutor
        # concluyó y espera aprobación, el otro sigue trabajando, más un experto consultado.
        t5 = mk_ticket(
            'Caída intermitente del servidor de correo', status=S.IN_PROGRESS, priority=P.URGENT,
            reporter=coord, solicitante='Cliente Externo - ACME', has_subproducts=True,
            project=proj['SUR'], label_names=['bug', 'seguridad'], due_offset=-2,
        )
        assign(t5, ejecutor, status=S.DONE, started=True, closed=True,
               conclusion='Corregí el registro MX que apuntaba mal. Monitoreando.')
        assign(t5, ejecutor2, status=S.IN_PROGRESS, started=True)
        assign(t5, experto, kind=AK.EXPERTO, status=S.TODO)
        for author_email, body in [
            ('coordinador@empresa.com', '¿Pudiste revisar los logs del MTA? Parece un problema de DNS.'),
            ('ejecutor@empresa.com', 'Sí, el registro MX apuntaba mal. Ya lo corregí y estoy monitoreando.'),
            ('experto@empresa.com', 'Perfecto, avisá si vuelve a fallar en las próximas horas.'),
        ]:
            Comment.objects.create(ticket=t5, author=users[author_email], body=body)
        attachment_services.store(
            _fake_image('captura-logs.png', 'steelblue'),
            owner=ejecutor, content_object=t5, backend_name=ATTACHMENT_BACKEND,
        )
        TicketEvent.objects.create(ticket=t5, actor=coord, kind='assignee', detail='actualizó las asignaciones')
        TicketEvent.objects.create(ticket=t5, actor=coord, kind='priority', detail='cambió la prioridad a «Urgente»')
        TicketEvent.objects.create(ticket=t5, actor=ejecutor, kind='status', detail='movió a «En progreso»')
        TicketEvent.objects.create(ticket=t5, actor=ejecutor, kind='conclude', detail='concluyó su subticket')

        # 6) En progreso, tarea colaborativa (sin subproductos): dos ejecutores comparten
        # un único estado. Comentario con adjunto PDF.
        t6 = mk_ticket(
            'Optimizar consultas lentas del dashboard', status=S.IN_PROGRESS, priority=P.HIGH,
            reporter=coord, solicitante='Gerencia de Operaciones', has_subproducts=False,
            project=proj['CLOUD'], label_names=['infra'], due_offset=10,
        )
        assign(t6, ejecutor, status=S.IN_PROGRESS, started=True)
        assign(t6, ejecutor2, status=S.IN_PROGRESS, started=True)
        assign(t6, ejecutor3, status=S.IN_PROGRESS, started=True)
        assign(t6, experto3, kind=AK.EXPERTO, status=S.TODO)
        c6 = Comment.objects.create(
            ticket=t6, author=experto, body='Adjunto el reporte de queries lentas detectadas.',
        )
        attachment_services.store(
            _fake_pdf('reporte-queries.pdf', 'Reporte de queries lentas — SkyDesk demo'),
            owner=experto, content_object=c6, backend_name=ATTACHMENT_BACKEND,
        )

        # 7) Suspendido/Cancelado por el Coordinador (`Ticket.suspended_at`, distinto del
        # "Esperando" individual del ejecutor): estaba en curso y se pausó a la espera del
        # presupuesto — el subticket queda bloqueado (candado) hasta que el Coordinador lo
        # reactive, sin importar en qué estado esté el ejecutor.
        t7 = mk_ticket(
            'Esperando aprobación de presupuesto cloud', status=S.WAITING, priority=P.MEDIUM,
            reporter=coord, solicitante='Dirección de Sistemas', project=proj['CLOUD'],
            suspended=True,
        )
        assign(t7, ejecutor, status=S.IN_PROGRESS, started=True)
        TicketEvent.objects.create(ticket=t7, actor=coord, kind='status', detail='suspendió/canceló el ticket')

        # 8) Concluido y ya aprobado.
        t8 = mk_ticket(
            'Actualizar certificados SSL de producción', status=S.DONE, priority=P.MEDIUM,
            reporter=coord, solicitante='Gerencia de Operaciones', project=proj['SUR'],
        )
        assign(t8, ejecutor, status=S.DONE, started=True, closed=True, approved=True,
               conclusion='Trabajo finalizado y verificado.')
        TicketEvent.objects.create(ticket=t8, actor=ejecutor, kind='status', detail='movió a «Concluido»')
        TicketEvent.objects.create(ticket=t8, actor=coord, kind='approve', detail='aprobó la conclusión')

        # 9) Concluido, aprobado y archivado.
        t9 = mk_ticket(
            'Auditoría de accesos del trimestre', status=S.DONE, priority=P.LOW,
            reporter=coord, solicitante='Gerencia de Operaciones', project=proj['AUD'],
            archived=True,
        )
        assign(t9, experto, status=S.DONE, started=True, closed=True, approved=True,
               conclusion='Auditoría completa, sin hallazgos críticos.')
        TicketEvent.objects.create(ticket=t9, actor=experto, kind='status', detail='movió a «Concluido»')
        TicketEvent.objects.create(ticket=t9, actor=coord, kind='approve', detail='aprobó la conclusión')
        TicketEvent.objects.create(ticket=t9, actor=coord, kind='archived', detail='archivó el ticket')

        # 10) Derivado de #9 ("Deriva de" — self-FK parent). Sin ejecutor asignado no
        # podría quedar en "Por hacer" (recompute_status() lo mandaría a Entrada).
        t10 = mk_ticket(
            'Revisar hallazgos de la auditoría (derivado)', status=S.TODO, priority=P.MEDIUM,
            reporter=coord, solicitante=t9.solicitante, project=proj['AUD'], parent=t9,
        )
        assign(t10, ejecutor5, status=S.TODO)
        TicketEvent.objects.create(ticket=t10, actor=coord, kind='created', detail=f'derivado de {t9.key}')

        # 11) Ligado a un proyecto cerrado.
        t11 = mk_ticket(
            'Depurar logs históricos', status=S.TODO, priority=P.LOW,
            reporter=coord, solicitante='Gerencia de Operaciones',
            project=proj['HIST'], label_names=['legacy'],
        )
        assign(t11, ejecutor3, status=S.TODO)

        # 12) Urgente, vencido, sin proyecto, con subproductos; adjunto PDF directo en el ticket.
        t12 = mk_ticket(
            'Incidente de seguridad en API pública', status=S.IN_PROGRESS, priority=P.URGENT,
            reporter=coord, solicitante='Cliente Externo - ACME', has_subproducts=True,
            label_names=['seguridad', 'destacado'], due_offset=-1,
        )
        assign(t12, ejecutor2, status=S.IN_PROGRESS, started=True)
        assign(t12, ejecutor4, status=S.TODO)
        assign(t12, experto, kind=AK.EXPERTO, status=S.TODO)
        attachment_services.store(
            _fake_pdf('informe-incidente.pdf', 'Informe preliminar del incidente — SkyDesk demo'),
            owner=coord, content_object=t12, backend_name=ATTACHMENT_BACKEND,
        )
        TicketEvent.objects.create(ticket=t12, actor=coord, kind='assignee', detail='actualizó las asignaciones')

        # 13) Entrada con etiqueta pero sin ninguna asignación todavía.
        mk_ticket(
            'Revisión de checklist de onboarding', status=S.BACKLOG, priority=P.MEDIUM,
            reporter=coord2, solicitante='Gerencia de Operaciones', label_names=['validado'],
        )

        # 14) En progreso, colaborativa, con el segundo equipo de ejecutores.
        t14 = mk_ticket(
            'Renovar el parque de notebooks del área comercial', status=S.IN_PROGRESS,
            priority=P.MEDIUM, reporter=coord2, solicitante='Gerencia Comercial',
            project=proj['SUR'], has_subproducts=False, label_names=['infra'],
        )
        assign(t14, ejecutor3, status=S.IN_PROGRESS, started=True)
        assign(t14, ejecutor4, status=S.IN_PROGRESS, started=True)
        Comment.objects.create(
            ticket=t14, author=ejecutor3, body='Ya cotizamos con dos proveedores, definimos esta semana.',
        )
        c14 = Comment.objects.create(
            ticket=t14, author=ejecutor4, body='Sumo la lista de equipos a dar de baja.',
        )
        attachment_services.store(
            _fake_image('equipos-a-dar-de-baja.png', 'darkslategray'),
            owner=ejecutor4, content_object=c14, backend_name=ATTACHMENT_BACKEND,
        )

        # 15) Por hacer, con un quinto ejecutor y un tercer experto consultado.
        t15 = mk_ticket(
            'Capacitación en la nueva herramienta de tickets', status=S.TODO, priority=P.LOW,
            reporter=coord2, solicitante='Gerencia de Operaciones', project=proj['CLOUD'],
        )
        assign(t15, ejecutor5, status=S.TODO)
        assign(t15, experto2, kind=AK.EXPERTO, status=S.TODO)

        # 16) Entrada, pedido derivado de un aviso del segundo perfil de Seguimiento.
        mk_ticket(
            'Relevar quejas recurrentes de la mesa de ayuda', status=S.BACKLOG, priority=P.MEDIUM,
            reporter=coord, solicitante='Mesa de Ayuda Interna',
        )

        # 17) Derivado de #14 ("Derivar"): NO es lo mismo que has_subproducts — acá se
        # crea un ticket nuevo y separado (parent=t14, t14 sigue activo), no un subticket
        # dentro de t14. Distinto de "Dividir", donde el padre pasaría a ser contenedor.
        t17 = mk_ticket(
            'Dar de baja las notebooks reemplazadas (derivado)', status=S.TODO, priority=P.LOW,
            reporter=coord2, solicitante=t14.solicitante, project=t14.project, parent=t14,
        )
        assign(t17, ejecutor4, status=S.TODO)
        TicketEvent.objects.create(ticket=t17, actor=coord2, kind='created', detail=f'derivado de {t14.key}')

        # Notificaciones: con/sin actor, con/sin ticket, leídas/no leídas.
        notify(coord, 'comentó en tu ticket', actor=ejecutor, ticket=t5)
        assigned_notif = notify(ejecutor, 'te asignó el ticket', actor=coord, ticket=t3)
        if assigned_notif:
            Notification.objects.filter(pk=assigned_notif.pk).update(is_read=True)
        notify(ejecutor, 'comentó en tu ticket', actor=experto, ticket=t5)
        notify(experto, 'tenés una tarea pendiente de aprobación', ticket=t5)
        notify(ejecutor2, 'te asignó el ticket', actor=coord, ticket=t12)
        seg_notif = notify(seguimiento, 'se concluyó el ticket que seguías', actor=experto, ticket=t9)
        if seg_notif:
            Notification.objects.filter(pk=seg_notif.pk).update(is_read=True)
        notify(coord, 'Bienvenido a SkyDesk')
        notify(coord2, 'te mencionó en un comentario', actor=ejecutor)
        notify(ejecutor3, 'te asignó el ticket', actor=coord2, ticket=t14)
        notify(ejecutor4, 'comentó en tu ticket', actor=ejecutor3, ticket=t14)
        notify(ejecutor5, 'te asignó el ticket', actor=coord2, ticket=t15)
        notify(experto2, 'te consultó en el ticket', actor=coord2, ticket=t15)
        exp3_notif = notify(experto3, 'te consultó en el ticket', actor=coord, ticket=t6)
        if exp3_notif:
            Notification.objects.filter(pk=exp3_notif.pk).update(is_read=True)
        notify(seguimiento2, 'Bienvenido a SkyDesk')

        self.stdout.write(self.style.SUCCESS('Datos de demo cargados.'))
        self.stdout.write('')
        self.stdout.write(f'  Dominio permitido: {DOMAIN}')
        self.stdout.write('  Tickets creados:   17 (uno por estado × combinación relevante)')
        self.stdout.write('  Usuarios (contraseña para todos: %s):' % PASSWORD)
        for email, role, first, last in DEMO_USERS:
            self.stdout.write(f'    - {email:28s} → {role.label}')
        self.stdout.write('')
        self.stdout.write('  Entrá en /acceso/login/ con cualquiera de esos correos.')
        self.stdout.write('  (Para administrar acceso/roles usá tu superuser.)')
