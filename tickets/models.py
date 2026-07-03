from datetime import timedelta

from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.db import IntegrityError, models, transaction
from django.utils import timezone


class Project(models.Model):
    """Proyecto al que se pueden vincular tickets."""
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Activo'
        PAUSED = 'PAUSED', 'En pausa'
        CLOSED = 'CLOSED', 'Cerrado'

    name = models.CharField('Nombre', max_length=120)
    code = models.CharField('Código', max_length=20, unique=True)
    city = models.CharField('Ciudad', max_length=120, blank=True)
    status = models.CharField('Estado', max_length=10, choices=Status.choices, default=Status.ACTIVE)
    description = models.TextField('Descripción', blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Proyecto'
        verbose_name_plural = 'Proyectos'

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.code} · {self.name}'

    @property
    def status_color(self):
        return {
            self.Status.ACTIVE: 'success',
            self.Status.PAUSED: 'warning',
            self.Status.CLOSED: 'neutral',
        }.get(self.status, 'neutral')


class Label(models.Model):
    """Actividad de trabajo (con color) para clasificar tickets (M2M)."""
    class Color(models.TextChoices):
        INFO = 'info', 'Azul'
        SUCCESS = 'success', 'Verde'
        WARNING = 'warning', 'Ámbar'
        ERROR = 'error', 'Rojo'
        ACCENT = 'accent', 'Acento'
        NEUTRAL = 'neutral', 'Gris'
        SECONDARY = 'secondary', 'Secundario'

    name = models.CharField('Nombre', max_length=50, unique=True)
    color = models.CharField('Color', max_length=20, choices=Color.choices, default=Color.NEUTRAL)

    class Meta:
        ordering = ['name']
        verbose_name = 'Actividad'
        verbose_name_plural = 'Actividades'

    def __str__(self):
        return self.name


class Ticket(models.Model):
    class Status(models.TextChoices):
        # El orden define el orden de las columnas del tablero.
        BACKLOG = 'BACKLOG', 'Necesidad'
        TODO = 'TODO', 'Por hacer'
        IN_PROGRESS = 'IN_PROGRESS', 'En progreso'
        DONE = 'DONE', 'Concluido'
        WAITING = 'WAITING', 'Suspendido/Cancelado'

    class Priority(models.TextChoices):
        LOW = 'LOW', 'Baja'
        MEDIUM = 'MEDIUM', 'Media'
        HIGH = 'HIGH', 'Alta'
        URGENT = 'URGENT', 'Urgente'

    code = models.CharField('Código', max_length=20, unique=True, blank=True, default='')
    title = models.CharField('Título', max_length=255)
    solicitante = models.CharField('Solicitante', max_length=150, blank=False, default='')
    description = models.TextField('Descripción', blank=True)
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='children', verbose_name='Deriva de',
    )
    status = models.CharField('Estado', max_length=20, choices=Status.choices, default=Status.BACKLOG)
    priority = models.CharField('Prioridad', max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    has_subproducts = models.BooleanField(
        'Tiene subproductos', default=False,
        help_text='Si se marca, cada ejecutor tiene su subticket independiente (avanza por separado). '
                  'Si no, la tarea es colaborativa: un estado compartido que mueve cualquiera.',
    )

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name='reported_tickets', verbose_name='Creado por',
    )

    project = models.ForeignKey(
        Project, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='tickets', verbose_name='Proyecto',
    )
    due_date = models.DateField('Vence', null=True, blank=True)
    labels = models.ManyToManyField(Label, blank=True, related_name='tickets', verbose_name='Actividades')

    position = models.PositiveIntegerField(default=0)
    closed_date = models.DateTimeField('Cerrado', null=True, blank=True)
    archived_at = models.DateTimeField('Archivado', null=True, blank=True)
    suspended_at = models.DateTimeField(
        'Suspendido por coordinador', null=True, blank=True,
        help_text='Distinto de WAITING por el ejecutor: solo el coordinador lo fija/quita, '
                  'y mientras está seteado el ticket queda bloqueado (no se puede mover).',
    )
    split_at = models.DateTimeField(
        'Dividido en partes', null=True, blank=True,
        help_text='Si se marca, el ticket es un contenedor: se descompuso en partes '
                  '(-1, -2…) y ya no aparece como card en el tablero; solo se ven sus partes.',
    )
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    attachments = GenericRelation('attachments.Attachment')

    class Meta:
        ordering = ['position', '-created']

    def __str__(self):
        return f'{self.key} · {self.title}'

    @staticmethod
    def _next_code():
        """Correlativo global SKY-0001 (4 dígitos, sigue creciendo)."""
        nums = [
            int(c.split('-', 1)[1])
            for c in Ticket.objects.exclude(code='').values_list('code', flat=True)
            if c.startswith('SKY-') and c.split('-', 1)[1].isdigit()
        ]
        return f'SKY-{(max(nums) + 1) if nums else 1:04d}'

    def _next_child_code(self):
        """Correlativo jerárquico colgado del código del padre: SKY-0014-1, SKY-0014-2…
        Si un hijo se vuelve a subdividir, encadena sobre SU código: SKY-0014-1-1.
        Robusto ante huecos (children borrados/orfanados por SET_NULL): toma el
        mayor sufijo numérico existente entre los hijos + 1, no el conteo."""
        base = self.code or self.key
        prefix = f'{base}-'
        nums = [
            int(c[len(prefix):])
            for c in self.children.exclude(code='').values_list('code', flat=True)
            if c.startswith(prefix) and c[len(prefix):].isdigit()
        ]
        return f'{base}-{(max(nums) + 1) if nums else 1}'

    def create_child(self, **kwargs):
        """Crea un hijo con código jerárquico (SKY-0014-N), reintentando ante colisión.
        Fija child.code ANTES de save(), así save() no dispara el correlativo global
        (solo lo hace cuando code está vacío — ver save())."""
        kwargs.setdefault('parent', self)
        for _ in range(5):
            child = Ticket(code=self._next_child_code(), **kwargs)
            try:
                with transaction.atomic():
                    child.save()
                return child
            except IntegrityError:
                continue
        child = Ticket(code=self._next_child_code(), **kwargs)
        child.save()
        return child

    def save(self, *args, **kwargs):
        if not self.code:
            for _ in range(5):
                self.code = self._next_code()
                try:
                    with transaction.atomic():
                        return super().save(*args, **kwargs)
                except IntegrityError:
                    self.code = ''
            self.code = self._next_code()
        return super().save(*args, **kwargs)

    @property
    def is_archived(self):
        return self.archived_at is not None

    @property
    def is_suspended(self):
        return self.suspended_at is not None

    @property
    def is_split(self):
        return self.split_at is not None

    @property
    def is_overdue(self):
        return bool(
            self.due_date and self.status != self.Status.DONE
            and self.due_date < timezone.localdate()
        )

    @property
    def key(self):
        return self.code or f'SKY-{self.pk}'

    @property
    def executor_assignments(self):
        return self.assignments.filter(kind='EJECUTOR')

    @property
    def expert_assignments(self):
        return self.assignments.filter(kind='EXPERTO')

    def is_participant(self, user):
        return self.assignments.filter(user=user).exists()

    def recompute_status(self):
        """Estado del padre = agregado de los subtickets de los ejecutores."""
        ejec = list(self.executor_assignments)
        S = self.Status
        if self.suspended_at:
            new = S.WAITING                              # Suspendido/Cancelado por el coordinador,
                                                           # incluso sin ejecutores asignados (Necesidad)
        elif not ejec:
            new = S.BACKLOG                              # Necesidad (sin ejecutores)
        elif all(a.status == S.WAITING for a in ejec):
            new = S.WAITING                              # Suspendido/Cancelado
        elif all(a.status == S.DONE and a.approved_at for a in ejec):
            new = S.DONE                                 # Concluido (todos + aprobados)
        elif any(a.status in (S.IN_PROGRESS, S.DONE) for a in ejec):
            new = S.IN_PROGRESS                          # alguien trabajando o concluido parcial
        else:
            new = S.TODO                                 # Por hacer (asignados, sin empezar)
        if new != self.status:
            self.status = new
            if new == S.DONE and not self.closed_date:
                self.closed_date = timezone.now()
            elif new != S.DONE:
                self.closed_date = None
            self.save(update_fields=['status', 'closed_date', 'updated'])
        return new

    @property
    def status_color(self):
        return {
            self.Status.BACKLOG: 'neutral',
            self.Status.TODO: 'info',
            self.Status.IN_PROGRESS: 'warning',
            self.Status.DONE: 'success',
            self.Status.WAITING: 'error',
        }.get(self.status, 'neutral')

    @property
    def priority_color(self):
        return {
            self.Priority.LOW: 'ghost',
            self.Priority.MEDIUM: 'info',
            self.Priority.HIGH: 'warning',
            self.Priority.URGENT: 'error',
        }.get(self.priority, 'ghost')


class Comment(models.Model):
    """Mensaje del chat de seguimiento de un ticket."""
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+',
    )
    body = models.TextField('Mensaje')
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    attachments = GenericRelation('attachments.Attachment')

    class Meta:
        ordering = ['created']

    def __str__(self):
        return f'Comentario #{self.pk} en {self.ticket.key}'


class TicketEvent(models.Model):
    """Entrada del historial de actividad de un ticket (cambios de estado, asignación, etc.)."""
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='events')
    # SET_NULL, no CASCADE: si se desasigna a alguien (se borra su Assignment), el
    # historial del ticket debe sobrevivir — `detail` ya guarda el texto del evento.
    assignment = models.ForeignKey(
        'Assignment', null=True, blank=True, on_delete=models.SET_NULL, related_name='events',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+',
    )
    kind = models.CharField(max_length=30)   # created | status | assignee | priority | due | conclude | approve | reject | archived | split
    detail = models.CharField(max_length=255, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created']

    def __str__(self):
        return f'{self.kind} en {self.ticket.key}'


class Assignment(models.Model):
    """Subticket por persona asignada. El ejecutor avanza su propio estado; el padre agrega."""
    class Kind(models.TextChoices):
        EJECUTOR = 'EJECUTOR', 'Ejecutor'
        EXPERTO = 'EXPERTO', 'Experto'

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='assignments')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assignments')
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.EJECUTOR)
    status = models.CharField(max_length=20, choices=Ticket.Status.choices, default=Ticket.Status.TODO)
    position = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    closed_date = models.DateTimeField(null=True, blank=True)
    conclusion = models.TextField('Conclusión', blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    # Tiempo acumulado por estado (se pausa mientras el subticket está en Suspendido/Cancelado).
    time_todo = models.DurationField('Tiempo en Por hacer', default=timedelta)
    time_in_progress = models.DurationField('Tiempo en En progreso', default=timedelta)
    status_changed_at = models.DateTimeField(default=timezone.now)

    # Estado que tenía el subticket cuando el coordinador suspendió el ticket — al
    # reactivar se restaura (antes todo volvía a TODO, "renaciendo" trabajo en progreso).
    status_before_suspend = models.CharField(max_length=20, blank=True, default='')

    class Meta:
        unique_together = ('ticket', 'user')
        ordering = ['position', 'created']

    def __str__(self):
        return f'{self.get_kind_display()} {self.user} · {self.ticket.key}'

    @property
    def is_executor(self):
        return self.kind == self.Kind.EJECUTOR

    @property
    def needs_approval(self):
        return self.status == Ticket.Status.DONE and self.approved_at is None

    _TIME_BUCKETS = {
        Ticket.Status.TODO: 'time_todo',
        Ticket.Status.IN_PROGRESS: 'time_in_progress',
    }

    def advance_to(self, new_status, now=None):
        """Cambia de estado acumulando el tiempo del tramo anterior.

        Solo TODO/IN_PROGRESS acumulan tiempo; WAITING (Esperando/Suspendido), DONE y
        BACKLOG pausan el reloj. No guarda — el caller decide cuándo hacer save().

        Salir de DONE (reabrir) invalida la conclusión anterior: se limpian
        `approved_at`/`closed_date`, así el trabajo rehecho vuelve a pasar por la
        aprobación del coordinador (needs_approval) y el tiempo mostrado en el
        detalle no queda congelado en el closed_date viejo.
        """
        now = now or timezone.now()
        bucket = self._TIME_BUCKETS.get(self.status)
        if bucket:
            setattr(self, bucket, getattr(self, bucket) + (now - self.status_changed_at))
        if new_status == Ticket.Status.IN_PROGRESS and not self.started_at:
            self.started_at = now
        if self.status == Ticket.Status.DONE and new_status != Ticket.Status.DONE:
            self.approved_at = None
            self.closed_date = None
        self.status = new_status
        self.status_changed_at = now

    def time_in(self, status, now=None):
        """Tiempo acumulado en `status`, incluyendo el tramo en curso si es el estado actual."""
        bucket = self._TIME_BUCKETS.get(status)
        if not bucket:
            return timedelta()
        total = getattr(self, bucket)
        if self.status == status:
            total += (now or timezone.now()) - self.status_changed_at
        return total
