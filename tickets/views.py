import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import (
    Avg, Case, Count, DurationField, ExpressionWrapper, F, IntegerField, OuterRef, Q,
    Subquery, Value, When,
)
from django.db.models.functions import TruncWeek
from django.http import (
    Http404, HttpResponse, HttpResponseBadRequest, JsonResponse, StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import has_capability, require_capability
from attachments import services as attachment_services

from django.contrib.auth import get_user_model

from notifications.services import notify

from .forms import CommentForm, ProjectForm, TicketForm
from .models import Assignment, Comment, Label, Project, Ticket, TicketEvent
from .realtime import broadcast_board

User = get_user_model()


def _log(ticket, actor, kind, detail='', assignment=None):
    TicketEvent.objects.create(ticket=ticket, actor=actor, kind=kind, detail=detail, assignment=assignment)
    # _log se llama en casi toda mutación relevante del tablero (mover, asignar, concluir,
    # aprobar, suspender, editar...) — engancharse acá cubre el broadcast de una sola vez
    # en vez de repetirlo vista por vista.
    broadcast_board(ticket.pk)


def _notify_assignment(request, ticket, users):
    """Notifica (in-app + email) a cada persona recién asignada, salvo a quien la asigna."""
    link = request.build_absolute_uri(reverse('tickets:detail', args=[ticket.pk]))
    actor = request.user.email or request.user.username
    for u in users:
        if not u or u.pk == request.user.pk:
            continue
        notify(u, 'te asignó un ticket', actor=request.user, ticket=ticket)
        if u.email:
            send_mail(
                f'[{ticket.key}] Te asignaron un ticket',
                f'{actor} te asignó el ticket {ticket.key}: {ticket.title}\n\n{link}',
                None, [u.email], fail_silently=True,
            )


# ── Helpers de permisos ───────────────────────────────────────────────────────

def _can_see_ticket(user, ticket):
    if has_capability(user, 'tickets.view_all') or has_capability(user, 'chat.view_all'):
        return True
    return ticket.reporter_id == user.id or ticket.is_participant(user)


def _can_write_chat(user, ticket):
    return has_capability(user, 'chat.write') and _can_see_ticket(user, ticket)


def _visible_tickets(user, include_archived=False, include_split=False):
    qs = Ticket.objects.select_related('reporter', 'project', 'parent').prefetch_related(
        'assignments', 'assignments__user', 'assignments__user__profile')
    if not include_archived:
        qs = qs.filter(archived_at__isnull=True)
    if not include_split:
        # Un ticket dividido en partes es un contenedor: ya no es actionable, no
        # aparece como card propia (solo sus partes -1, -2… lo hacen).
        qs = qs.filter(split_at__isnull=True)
    if has_capability(user, 'tickets.view_all'):
        return qs
    return qs.filter(Q(reporter=user) | Q(assignments__user=user)).distinct()


def _apply_filters(qs, request):
    """Filtros de querystring: solo búsqueda (q), asignación y proyecto."""
    g = request.GET
    if g.get('q'):
        qs = qs.filter(
            Q(title__icontains=g['q']) | Q(description__icontains=g['q'])
            | Q(code__icontains=g['q']) | Q(solicitante__icontains=g['q'])
        )
    if g.get('assignee', '').isdigit():
        qs = qs.filter(assignments__user_id=g['assignee']).distinct()
    if g.get('project', '').isdigit():
        qs = qs.filter(project_id=g['project'])
    return qs


def _filter_context(request):
    return {
        'users': User.objects.filter(is_active=True).order_by('email'),
        'projects': Project.objects.all(),
        'q': request.GET.get('q', ''),
        'assignee': request.GET.get('assignee', ''),
        'project': request.GET.get('project', ''),
    }


def _owning_ticket(attachment):
    obj = attachment.content_object
    if isinstance(obj, Ticket):
        return obj
    return getattr(obj, 'ticket', None)


def _ticket_people(ticket):
    """reporter + todos los asignados (ejecutores y expertos)."""
    people = [ticket.reporter] + [a.user for a in ticket.assignments.all()]
    return [u for u in people if u]


def _notify_backlog_to_todo(actor, ticket):
    """Avisa a todos los involucrados —menos quien hizo el cambio— que el ticket salió
    de "Necesidad" (BACKLOG, bandeja exclusiva del coordinador) hacia "Por hacer"."""
    for u in _ticket_people(ticket):
        if u.pk != actor.pk:
            notify(u, 'puso en Por hacer', actor=actor, ticket=ticket)


def _notify_new_comment(request, ticket, comment):
    author_pk = getattr(comment.author, 'pk', None)
    recipients = {
        u.email for u in _ticket_people(ticket)
        if u.email and u.pk != author_pk
    }
    if not recipients:
        return
    link = request.build_absolute_uri(reverse('tickets:detail', args=[ticket.pk]))
    body = (
        f'Nuevo mensaje de seguimiento en {ticket.key} — {ticket.title}\n\n'
        f'{comment.body}\n\n{link}'
    )
    send_mail(f'[{ticket.key}] Nuevo seguimiento', body, None, list(recipients), fail_silently=True)


# ── Board (kanban) ────────────────────────────────────────────────────────────

def _visible_statuses(user):
    """Columnas del tablero para `user`.

    - "Necesidad" (BACKLOG): solo quien puede asignar (Coordinador) — es la bandeja de
      tickets sin ejecutor, no aporta a Ejecutor/Experto/Seguimiento.
    - "Suspendido/Cancelado" (WAITING): solo Coordinador y Seguimiento
      (`tickets.view_waiting`) — a Experto y Ejecutor no les aporta y para el Ejecutor
      además nunca fue la forma de suspender un ticket completo (eso es solo del
      Coordinador vía `ticket_suspend`).
    """
    hidden = set()
    if not has_capability(user, 'tickets.assign'):
        hidden.add(Ticket.Status.BACKLOG)
    if not has_capability(user, 'tickets.view_waiting'):
        hidden.add(Ticket.Status.WAITING)
    return [(v, l) for v, l in Ticket.Status.choices if v not in hidden]


def _subticket_cards(visible, statuses, *, viewer):
    """Agrupa Assignments (`visible`) en columnas por `status`, fusionando 2+ subtickets
    del mismo ticket que caen en la misma columna en una sola card — evita mostrar "mi
    card" + fantasma casi idénticas una al lado de la otra cuando ya están alineadas; se
    separan de nuevo apenas alguno cambie de estado.

    `viewer` = el ejecutor logueado (tablero del ejecutor): marca `is_ghost` en los
    subtickets ajenos y `my_assignment` es el propio dentro del grupo fusionado.
    `viewer=None` = vista de solo lectura (tablero del coordinador, ve TODOS los
    subtickets sin atenuar): `is_readonly=True`, sin fantasmas ni "mi" asignación.

    Devuelve {status_value: [entries]}; cada entry es {'type': 'subticket', 'a': a} o
    {'type': 'merged', 'ticket', 'group', 'link_color', 'is_locked', 'my_assignment',
    'is_readonly'}."""
    for a in visible:
        a.is_ghost = viewer is not None and a.user_id != viewer.id
    # Mismo color (punto con ping) para todas las cards del mismo ticket, pero solo
    # cuando de verdad queda más de una card repartida en columnas distintas — si todos
    # los ejecutores están alineados en el mismo estado (se fusionan en una sola card),
    # el punto no aporta nada porque ya no hay nada que vincular.
    statuses_by_ticket = {}
    for a in visible:
        statuses_by_ticket.setdefault(a.ticket_id, set()).add(a.status)
    for a in visible:
        a.link_color = a.ticket_id % 8 if len(statuses_by_ticket[a.ticket_id]) > 1 else None
    by_status = {}
    for value, _label in statuses:
        items = [a for a in visible if a.status == value]
        items.sort(key=lambda a: (a.is_ghost, a.position, -a.pk))
        by_ticket = {}
        for a in items:
            by_ticket.setdefault(a.ticket_id, []).append(a)
        entries = []
        merged_tickets = set()
        for a in items:
            group = by_ticket[a.ticket_id]
            if len(group) > 1:
                if a.ticket_id in merged_tickets:
                    continue
                merged_tickets.add(a.ticket_id)
                mine = next((x for x in group if viewer is not None and x.user_id == viewer.id), None)
                entries.append({
                    'type': 'merged', 'ticket': a.ticket, 'group': group,
                    'link_color': a.link_color, 'is_locked': a.is_locked,
                    'my_assignment': mine, 'is_readonly': viewer is None,
                    'pending_approval': any(
                        x.status == Ticket.Status.DONE and not x.approved_at for x in group),
                })
            else:
                a.is_readonly = viewer is None
                entries.append({'type': 'subticket', 'a': a})
        by_status[value] = entries
    return by_status


def _parent_columns(request):
    """Vista del coordinador/experto/seguimiento: cards = tickets (estado agregado),
    salvo los que tienen subproductos —esos se muestran como cards por subticket, igual
    que ve el propio ejecutor (ver _subticket_cards), porque recompute_status() no puede
    reflejar "alguien concluyó pero no todos" en una sola card agregada sin ocultar ese
    progreso (ver models.py:212-236)."""
    user = request.user
    tickets = list(_apply_filters(_visible_tickets(user), request).annotate(
        num_comments=Count('comments', distinct=True),
        num_attachments=Count('attachments', distinct=True),
        num_children=Count('children', distinct=True),
    ).prefetch_related('labels', 'assignments__user__profile', 'children'))
    # Coordinador (tickets.assign): ve todos, pero primero los propios (reporter o
    # participante) y el resto con la card apagada. Experto ya solo ve los suyos (no
    # tiene view_all) y Seguimiento ve todo por igual — a ninguno de los dos se le
    # aplica este resaltado.
    highlight_own = has_capability(user, 'tickets.assign')
    can_edit_any = has_capability(user, 'tickets.edit_any')
    ticket_entries = []
    subproduct_assignments = []
    for t in tickets:
        ejec = [a for a in t.assignments.all() if a.kind == Assignment.Kind.EJECUTOR]
        if t.has_subproducts and ejec:
            for a in ejec:
                a.ticket = t   # evita relanzar la query (t.assignments ya viene prefetched)
                a.is_locked = bool(t.suspended_at)
                subproduct_assignments.append(a)
            continue
        # Todos los ejecutores concluyeron pero falta la aprobación del coordinador:
        # recompute_status() todavía marca el ticket IN_PROGRESS (models.py:223-226), pero
        # visualmente ya está "Concluido" — la card debe caer en esa columna.
        t.pending_approval = bool(ejec) and all(a.status == Ticket.Status.DONE for a in ejec) \
            and t.status != Ticket.Status.DONE
        t.display_status = Ticket.Status.DONE if t.pending_approval else t.status
        # t.assignments ya viene prefetched — usar .all() (no t.is_participant(user), que
        # re-consulta la DB y rompería el prefetch con un N+1) para reproducir el mismo
        # criterio de _can_archive_ticket sin la query extra.
        is_participant = any(a.user_id == user.id for a in t.assignments.all())
        t.can_archive = (
            (can_edit_any or t.reporter_id == user.id or is_participant)
            and t.status in (Ticket.Status.DONE, Ticket.Status.WAITING)
            and not t.is_archived
        )
        if highlight_own:
            t.is_muted = not (t.reporter_id == user.id or is_participant)
        ticket_entries.append(t)
    statuses = _visible_statuses(user)
    subticket_by_status = _subticket_cards(subproduct_assignments, statuses, viewer=None)
    columns = []
    for value, label in statuses:
        col = [t for t in ticket_entries if t.display_status == value]
        if highlight_own:
            col.sort(key=lambda t: (t.is_muted, t.position, -t.pk))
        else:
            col.sort(key=lambda t: (t.position, -t.pk))
        items = [{'type': 'ticket', 't': t} for t in col] + subticket_by_status[value]
        columns.append({'value': value, 'label': label, 'items': items, 'count': len(items)})
    return columns


def _executor_columns(request):
    """Vista del ejecutor: cards = sus subtickets (sólidos) + los de co-ejecutores (fantasma)."""
    user = request.user
    my_ids = list(Assignment.objects.filter(
        user=user, kind=Assignment.Kind.EJECUTOR,
        ticket__archived_at__isnull=True, ticket__split_at__isnull=True,
    ).values_list('ticket_id', flat=True))
    tickets = _apply_filters(Ticket.objects.filter(id__in=my_ids), request).annotate(
        num_comments=Count('comments', distinct=True),
        num_attachments=Count('attachments', distinct=True),
    )
    tids = set(tickets.values_list('id', flat=True))
    counts = {t.id: (t.num_comments, t.num_attachments) for t in tickets}
    assignments = Assignment.objects.filter(
        ticket_id__in=tids, kind=Assignment.Kind.EJECUTOR,
    ).select_related('ticket', 'ticket__project', 'ticket__parent', 'user', 'user__profile').prefetch_related(
        'ticket__labels', 'ticket__assignments__user__profile', 'ticket__children',
    )
    # Colaborativa (sin subproductos): solo se ve el subticket propio (estado compartido).
    # Con subproductos: se ve el propio (sólido) + los de co-ejecutores (fantasma).
    visible = []
    for a in assignments:
        a.is_locked = bool(a.ticket.suspended_at)
        # Los íconos de dividido/derivado/subproductos deben verse igual en cualquier
        # card, sin importar el rol (ticket__children ya viene prefetched: sin query extra).
        a.ticket.num_children = len(a.ticket.children.all())
        a.ticket.num_comments, a.ticket.num_attachments = counts.get(a.ticket_id, (0, 0))
        if a.ticket.has_subproducts or a.user_id == user.id:
            visible.append(a)
    statuses = _visible_statuses(user)
    by_status = _subticket_cards(visible, statuses, viewer=user)
    columns = []
    for value, label in statuses:
        items = by_status[value]
        columns.append({'value': value, 'label': label, 'items': items, 'count': len(items)})
    return columns


def _board_context(request):
    if has_capability(request.user, 'tickets.board_by_ticket'):
        return {'columns': _parent_columns(request), 'board_mode': 'ticket',
                'can_move': has_capability(request.user, 'tickets.move')}
    return {'columns': _executor_columns(request), 'board_mode': 'subticket',
            'can_move': has_capability(request.user, 'tickets.move')}


@login_required
def board(request):
    ctx = _board_context(request)
    ctx.update({
        'filters': _filter_context(request),
        'can_create': has_capability(request.user, 'tickets.create'),
    })
    return render(request, 'tickets/board.html', ctx)


@login_required
def board_fragment(request):
    return render(request, 'tickets/partials/_board_columns.html', _board_context(request))


@require_POST
@require_capability('tickets.move')
@require_capability('tickets.board_by_ticket')
def ticket_move(request):
    """Mueve cards de ticket completo (tablero del coordinador, board_mode='ticket').
    Exclusivo de quien tiene AMBAS capacidades — board_by_ticket, no solo move: un
    Ejecutor tiene tickets.move (para su propio tablero por subticket, ver
    assignment_move) pero no board_by_ticket, así que no puede tocar cards ajenas acá."""
    try:
        payload = json.loads(request.body)
        status = payload['status']
        order = payload.get('order', [])
    except (ValueError, KeyError):
        return HttpResponseBadRequest('payload inválido')

    if status not in Ticket.Status.values:
        return HttpResponseBadRequest('estado inválido')

    movable = {
        t.pk: t for t in _visible_tickets(request.user)
        .prefetch_related('assignments').filter(pk__in=order)
    }
    now = timezone.now()
    for index, tid in enumerate(order):
        ticket = movable.get(tid)
        if ticket is None:
            continue
        if ticket.suspended_at:
            continue   # bloqueado por el coordinador: solo se destraba vía ticket_suspend
        old_status = ticket.status
        status_changed = old_status != status
        ejec = list(ticket.executor_assignments)
        if status == Ticket.Status.BACKLOG and ejec:
            continue   # "Necesidad" es la bandeja de tickets sin ejecutor (ver _visible_statuses)
        ticket.position = index
        if status_changed:
            if status in _DRAG_STATUSES and ejec:
                # Sincroniza los subtickets de los ejecutores con la card arrastrada —
                # evita el desync ticket.status vs Assignment.status que dejaba, por
                # ejemplo, un ticket con ejecutores asignados cayendo en BACKLOG.
                for ea in ejec:
                    ea.advance_to(status, now)
                    if status == Ticket.Status.DONE:
                        ea.closed_date = now
                        if not ea.started_at:
                            ea.started_at = ea.created
                    ea.save()
                ticket.save(update_fields=['position', 'updated'])
                ticket.recompute_status()
            else:
                ticket.status = status
                if status == Ticket.Status.DONE and ticket.closed_date is None:
                    ticket.closed_date = timezone.now()
                elif status != Ticket.Status.DONE and ticket.closed_date is not None:
                    ticket.closed_date = None
                ticket.save(update_fields=['status', 'position', 'closed_date', 'updated'])
            _log(ticket, request.user, 'status', f'movió a «{ticket.get_status_display()}»')
            if old_status == Ticket.Status.BACKLOG and ticket.status == Ticket.Status.TODO:
                _notify_backlog_to_todo(request.user, ticket)
        else:
            ticket.save(update_fields=['position', 'updated'])
    return JsonResponse({'ok': True})


# ── Flujo de subtickets (ejecutor) + aprobación/suspensión (coordinador) ────────

_DRAG_STATUSES = (Ticket.Status.TODO, Ticket.Status.IN_PROGRESS, Ticket.Status.WAITING, Ticket.Status.DONE)


def _conclude_assignments(request, a, actor, conclusion=''):
    """Concluye (DONE) el/los subtickets de `a` — solo el propio si el ticket tiene
    subproductos, todos los ejecutores si es colaborativa. La conclusión (texto o link)
    es opcional. Compartido por assignment_conclude (modal) y assignment_move (drag
    directo a Concluido)."""
    now = timezone.now()
    targets = [a] if a.ticket.has_subproducts else list(a.ticket.executor_assignments)
    for ea in targets:
        ea.advance_to(Ticket.Status.DONE, now)
        ea.closed_date = now
        ea.conclusion = conclusion
        if not ea.started_at:
            ea.started_at = ea.created
        ea.save()
    _log(a.ticket, actor, 'conclude',
         'concluyó su subticket' if a.ticket.has_subproducts else 'concluyó la tarea', assignment=a)
    a.ticket.recompute_status()
    if a.ticket.reporter and a.ticket.reporter.pk != actor.pk:
        verb = 'concluyó un subticket (pendiente de aprobación)' if a.ticket.has_subproducts \
            else 'concluyó la tarea (pendiente de aprobación)'
        notify(a.ticket.reporter, verb, actor=actor, ticket=a.ticket)
    if conclusion.strip():
        prefix = 'Concluyó su subticket' if a.ticket.has_subproducts else 'Concluyó la tarea'
        comment = Comment.objects.create(ticket=a.ticket, author=actor, body=f'{prefix}: {conclusion.strip()}')
        _notify_new_comment(request, a.ticket, comment)
        for u in _ticket_people(a.ticket):
            if u.pk != actor.pk:
                notify(u, 'comentó en', actor=actor, ticket=a.ticket)


@require_POST
@require_capability('tickets.move')
def assignment_move(request):
    """El ejecutor mueve SU subticket entre Por hacer / En progreso / Esperando / Concluido."""
    try:
        payload = json.loads(request.body)
        aid = payload['assignment']
        status = payload['status']
    except (ValueError, KeyError):
        return HttpResponseBadRequest('payload inválido')
    if status not in _DRAG_STATUSES:
        return HttpResponseBadRequest('estado no permitido')
    a = get_object_or_404(Assignment, pk=aid, user=request.user, kind=Assignment.Kind.EJECUTOR)
    if a.ticket.suspended_at:
        return HttpResponseBadRequest('el ticket está suspendido por el coordinador')
    if a.status != status:
        if status == Ticket.Status.DONE:
            _conclude_assignments(request, a, request.user)
        else:
            now = timezone.now()
            if a.ticket.has_subproducts:
                a.advance_to(status, now)
                a.save()
                _log(a.ticket, request.user, 'status',
                     f'movió su subticket a «{a.get_status_display()}»', assignment=a)
            else:
                # Colaborativa: el estado es compartido → sincroniza a todos los ejecutores.
                for ea in a.ticket.executor_assignments:
                    ea.advance_to(status, now)
                    ea.save()
                _log(a.ticket, request.user, 'status', f'movió la tarea a «{a.ticket.Status(status).label}»')
            a.ticket.recompute_status()
    return JsonResponse({'ok': True, 'parent_status': a.ticket.status})


@login_required
@require_POST
def assignment_conclude(request, pk):
    """Concluir el subticket propio (el texto de conclusión es opcional: descripción o link)."""
    a = get_object_or_404(Assignment, pk=pk, user=request.user, kind=Assignment.Kind.EJECUTOR)
    conclusion = request.POST.get('conclusion', '').strip()
    _conclude_assignments(request, a, request.user, conclusion)
    msg = 'Subticket concluido. Pendiente de aprobación del coordinador.' if a.ticket.has_subproducts \
        else 'Tarea concluida. Pendiente de aprobación del coordinador.'
    messages.success(request, msg)
    return redirect('tickets:detail', pk=a.ticket_id)


@login_required
@require_capability('tickets.close')
@require_POST
def ticket_approve(request, pk):
    """El coordinador aprueba las conclusiones (subtickets DONE)."""
    ticket = get_object_or_404(Ticket, pk=pk)
    pending = ticket.executor_assignments.filter(status=Ticket.Status.DONE, approved_at__isnull=True)
    approved = list(pending.select_related('user'))
    if approved:
        pending.update(approved_at=timezone.now())
        _log(ticket, request.user, 'approve', 'aprobó la conclusión')
        ticket.recompute_status()
        for a in approved:
            if a.user and a.user.pk != request.user.pk:
                notify(a.user, 'aprobó tu conclusión', actor=request.user, ticket=ticket)
        messages.success(request, f'{ticket.key}: conclusión aprobada.')
    else:
        messages.info(request, 'No hay subtickets concluidos pendientes de aprobación.')
    return redirect('tickets:detail', pk=ticket.pk)


@login_required
@require_capability('tickets.close')
@require_POST
def ticket_suspend(request, pk):
    """El coordinador suspende/cancela el ticket (o lo reactiva). Solo el coordinador puede
    tocar este candado — mientras `suspended_at` está seteado, los ejecutores no pueden
    mover su subticket (ver assignment_move)."""
    ticket = get_object_or_404(Ticket, pk=pk)
    now = timezone.now()
    ejec = list(ticket.executor_assignments.filter(status=Ticket.Status.WAITING)) \
        if ticket.status == Ticket.Status.WAITING else list(ticket.executor_assignments)
    if ticket.status == Ticket.Status.WAITING:
        for ea in ejec:
            ea.advance_to(Ticket.Status.TODO, now)
            ea.save()
        ticket.suspended_at = None
        ticket.save(update_fields=['suspended_at', 'updated'])
        _log(ticket, request.user, 'status', 'reactivó el ticket')
        messages.success(request, f'{ticket.key} reactivado.')
    else:
        for ea in ejec:
            ea.advance_to(Ticket.Status.WAITING, now)
            ea.save()
        ticket.suspended_at = now
        ticket.save(update_fields=['suspended_at', 'updated'])
        _log(ticket, request.user, 'status', 'suspendió/canceló el ticket')
        messages.success(request, f'{ticket.key} suspendido/cancelado.')
    ticket.recompute_status()
    return redirect('tickets:detail', pk=ticket.pk)


# ── Detalle + chat ────────────────────────────────────────────────────────────

def _fmt_delta(delta):
    """Formatea un timedelta como 'Xd Yh Zm' legible (None/0 → None)."""
    if not delta:
        return None
    secs = int(delta.total_seconds())
    if secs <= 0:
        return None
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f'{days}d')
    if hours:
        parts.append(f'{hours}h')
    if mins and not days:
        parts.append(f'{mins}m')
    return ' '.join(parts) or '0m'


def _elapsed(assignment):
    """Tiempo trabajado en el subticket (string legible), o None si no empezó."""
    if not assignment.started_at:
        return None
    delta = (assignment.closed_date or timezone.now()) - assignment.started_at
    return _fmt_delta(delta) or '0m'


@login_required
def ticket_detail(request, pk):
    ticket = get_object_or_404(Ticket.objects.select_related('reporter', 'project', 'parent'), pk=pk)
    if not _can_see_ticket(request.user, ticket):
        raise PermissionDenied
    comments = ticket.comments.select_related('author', 'author__profile').prefetch_related('attachments')
    can_edit = _can_edit_ticket(request.user, ticket)
    can_archive_perm = _can_archive_ticket(request.user, ticket)

    executors = list(ticket.executor_assignments.select_related('user', 'user__profile'))
    experts = list(ticket.expert_assignments.select_related('user', 'user__profile'))
    now = timezone.now()
    for a in executors:
        a.elapsed = _elapsed(a)
        a.time_todo_fmt = _fmt_delta(a.time_in(Ticket.Status.TODO, now))
        a.time_in_progress_fmt = _fmt_delta(a.time_in(Ticket.Status.IN_PROGRESS, now))
    my_assignment = next((a for a in executors if a.user_id == request.user.id), None)

    can_close = has_capability(request.user, 'tickets.close')
    pending_approval = any(a.needs_approval for a in executors)
    children = ticket.children.all()
    split_summary = None
    if ticket.is_split:
        # Rollup de estados de las partes para mostrar en el detalle del contenedor
        # (el contenedor ya no aparece como card en el tablero, ver _visible_tickets).
        counts = {row['status']: row['n'] for row in children.values('status').annotate(n=Count('pk'))}
        split_summary = [(label, counts[value]) for value, label in Ticket.Status.choices if counts.get(value)]
    can_create = has_capability(request.user, 'tickets.create')
    return render(request, 'tickets/ticket_detail.html', {
        'ticket': ticket,
        'comments': comments,
        'events': ticket.events.select_related('actor'),
        'ticket_attachments': ticket.attachments.all(),
        'children': children,
        'executors': executors,
        'experts': experts,
        'my_assignment': my_assignment,
        'comment_form': CommentForm(),
        'can_write_chat': _can_write_chat(request.user, ticket),
        'can_moderate_chat': has_capability(request.user, 'tickets.edit_any'),
        'can_edit': can_edit,
        'pending_approval': pending_approval,
        'is_split': ticket.is_split,
        'split_summary': split_summary,
        'parent_is_split': bool(ticket.parent_id and ticket.parent.is_split),
        'can_divide': can_create,
        'can_derive': can_create and not ticket.is_split,
        'can_archive': can_archive_perm and ticket.status in (Ticket.Status.DONE, Ticket.Status.WAITING) and not ticket.is_archived,
        'can_approve': can_close and pending_approval,
        'can_suspend': can_close and ticket.status not in (Ticket.Status.DONE,),
        'drag_statuses': _DRAG_STATUSES,
    })


@login_required
@require_POST
def comment_add(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    if not _can_write_chat(request.user, ticket):
        raise PermissionDenied
    form = CommentForm(request.POST)
    if form.is_valid() and (form.cleaned_data['body'].strip() or request.FILES):
        comment = form.save(commit=False)
        comment.ticket = ticket
        comment.author = request.user
        comment.save()
        _store_files(request, comment, target=comment)
        _notify_new_comment(request, ticket, comment)
        for u in _ticket_people(ticket):
            if u.pk != request.user.pk:
                notify(u, 'comentó en', actor=request.user, ticket=ticket)
        # comment_add no pasa por _log (no es un evento del historial) — el contador de
        # mensajes de la card sí cambia, así que hay que avisar explícitamente.
        broadcast_board(ticket.pk)
    else:
        messages.error(request, 'El mensaje no puede estar vacío.')
    return redirect('tickets:detail', pk=ticket.pk)


def _can_moderate_comment(user, comment):
    return comment.author_id == user.id or has_capability(user, 'tickets.edit_any')


@login_required
@require_POST
def comment_edit(request, pk):
    comment = get_object_or_404(Comment.objects.select_related('ticket'), pk=pk)
    if not _can_moderate_comment(request.user, comment):
        raise PermissionDenied
    body = request.POST.get('body', '').strip()
    if body:
        comment.body = body
        comment.save(update_fields=['body', 'updated'])
    return redirect('tickets:detail', pk=comment.ticket_id)


@login_required
@require_POST
def comment_delete(request, pk):
    comment = get_object_or_404(Comment.objects.select_related('ticket'), pk=pk)
    if not _can_moderate_comment(request.user, comment):
        raise PermissionDenied
    tid = comment.ticket_id
    try:
        comment.delete()  # cascadea sus adjuntos (post_delete, ver attachments/signals.py)
    except Exception:
        # Backend de almacenamiento caído: no se borró nada (rollback) — avisar en vez de 500.
        messages.error(request, 'No se pudo borrar el mensaje (error de almacenamiento en sus adjuntos).')
    return redirect('tickets:detail', pk=tid)


# ── Adjuntos ──────────────────────────────────────────────────────────────────

def _store_files(request, ticket_or_comment, target):
    """Sube los archivos del request asociándolos a `target` (ticket o comment)."""
    files = request.FILES.getlist('files')
    for f in files:
        try:
            attachment_services.store(f, owner=request.user, content_object=target)
        except attachment_services.DuplicateAttachment:
            messages.info(request, f'«{f.name}» ya estaba adjunto (no se duplicó).')
        except ValidationError as exc:
            messages.error(request, f'{f.name}: {exc.messages[0]}')
        except Exception:
            messages.error(request, f'No se pudo subir «{f.name}» (error de almacenamiento).')


@login_required
@require_POST
def attachment_add(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    if not _can_write_chat(request.user, ticket):
        raise PermissionDenied
    _store_files(request, ticket, target=ticket)
    return redirect('tickets:detail', pk=ticket.pk)


@login_required
@require_POST
def attachment_delete(request, pk):
    from attachments.models import Attachment
    attachment = get_object_or_404(Attachment, pk=pk)
    ticket = _owning_ticket(attachment)
    if ticket is None or not _can_write_chat(request.user, ticket):
        raise PermissionDenied
    try:
        attachment.delete()  # borra el blob remoto + la fila (post_delete, ver signals.py)
    except Exception:
        # Backend de almacenamiento caído: no se borró nada (rollback) — avisar en vez de 500.
        messages.error(request, 'No se pudo borrar el adjunto (error de almacenamiento).')
    return redirect('tickets:detail', pk=ticket.pk)


@login_required
def attachment_serve(request, pk):
    from attachments.models import Attachment
    attachment = get_object_or_404(Attachment, pk=pk)
    ticket = _owning_ticket(attachment)
    if ticket is None or not _can_see_ticket(request.user, ticket):
        raise PermissionDenied
    try:
        stream, content_type = attachment_services.open_blob(attachment)
    except Exception:
        # Backend de almacenamiento caído/mal configurado → 404 en vez de 500.
        raise Http404('No se pudo recuperar el archivo del almacenamiento.')
    response = StreamingHttpResponse(stream, content_type=content_type)
    # `inline` solo para tipos sin contenido activo (rasters/PDF, ver SAFE_INLINE_TYPES) —
    # todo lo demás se descarga en vez de renderizarse same-origin con las cookies de sesión.
    disposition = 'inline' if (content_type or '').lower() in attachment_services.SAFE_INLINE_TYPES else 'attachment'
    response['Content-Disposition'] = f'{disposition}; filename="{attachment.filename}"'
    # Defensa en profundidad: aunque la CSP global no cubra esta respuesta, sandboxea
    # cualquier contenido activo que se cuele (scripts, forms, popups).
    response['Content-Security-Policy'] = "sandbox"
    return response


@login_required
def attachment_thumb(request, pk):
    from attachments import thumbnails
    from attachments.models import Attachment
    attachment = get_object_or_404(Attachment, pk=pk)
    ticket = _owning_ticket(attachment)
    if ticket is None or not _can_see_ticket(request.user, ticket):
        raise PermissionDenied
    png = thumbnails.get_thumbnail(attachment)
    if not png:
        raise Http404('Sin thumbnail.')
    resp = HttpResponse(png, content_type='image/png')
    resp['Cache-Control'] = 'private, max-age=86400'
    return resp


# ── Crear / editar ────────────────────────────────────────────────────────────

def _sync_assignments(ticket, executor_users, expert_users, status=Ticket.Status.TODO):
    """Sincroniza los Assignment del ticket con las selecciones. Devuelve los usuarios nuevos.
    `status` es el estado inicial de los Assignment nuevos (por defecto TODO; subdivide lo
    pisa para que el hijo nazca — y se mantenga, tras el recompute_status() de abajo — en el
    mismo estado que el padre)."""
    desired = {}
    for u in expert_users:
        desired[u.pk] = Assignment.Kind.EXPERTO
    for u in executor_users:
        desired[u.pk] = Assignment.Kind.EJECUTOR   # si está en ambos, gana ejecutor
    existing = {a.user_id: a for a in ticket.assignments.all()}
    for uid, a in existing.items():
        if uid not in desired:
            a.delete()
    added = []
    for uid, kind in desired.items():
        a = existing.get(uid)
        if a is None:
            Assignment.objects.create(ticket=ticket, user_id=uid, kind=kind, status=status)
            added.append(uid)
        elif a.kind != kind:
            a.kind = kind
            a.save(update_fields=['kind'])
    ticket.recompute_status()
    broadcast_board(ticket.pk)   # blindaje: por si algún caller futuro no pasa por _log
    return list(User.objects.filter(pk__in=added))


@login_required
@require_capability('tickets.create')
def ticket_create(request):
    can_assign = has_capability(request.user, 'tickets.assign')
    if request.method == 'POST':
        form = TicketForm(request.POST, can_assign=can_assign)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.reporter = request.user
            ticket.save()
            form.save_m2m()
            _log(ticket, request.user, 'created', 'creó el ticket')
            if can_assign:
                added = _sync_assignments(ticket, form.cleaned_data.get('executors', []),
                                          form.cleaned_data.get('experts', []))
                _notify_assignment(request, ticket, added)
            messages.success(request, f'{ticket.key} creado.')
            return redirect('tickets:detail', pk=ticket.pk)
    else:
        form = TicketForm(can_assign=can_assign)
    return render(request, 'tickets/ticket_form.html', {'form': form, 'creating': True})


@login_required
def ticket_edit(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    if not _can_edit_ticket(request.user, ticket):
        raise PermissionDenied
    can_assign = has_capability(request.user, 'tickets.assign')
    old = {'priority': ticket.priority, 'due_date': ticket.due_date, 'status': ticket.status}
    if request.method == 'POST':
        form = TicketForm(request.POST, instance=ticket, can_assign=can_assign)
        if form.is_valid():
            obj = form.save()
            if obj.priority != old['priority']:
                _log(obj, request.user, 'priority', f'cambió la prioridad a «{obj.get_priority_display()}»')
            if obj.due_date != old['due_date']:
                d = obj.due_date.strftime('%d/%m/%Y') if obj.due_date else 'sin fecha'
                _log(obj, request.user, 'due', f'cambió el vencimiento a {d}')
            if can_assign:
                added = _sync_assignments(obj, form.cleaned_data.get('executors', []),
                                          form.cleaned_data.get('experts', []))
                if added:
                    _log(obj, request.user, 'assignee', 'actualizó las asignaciones')
                    _notify_assignment(request, obj, added)
                if old['status'] == Ticket.Status.BACKLOG and obj.status == Ticket.Status.TODO:
                    _notify_backlog_to_todo(request.user, obj)
            messages.success(request, f'{ticket.key} actualizado.')
            return redirect('tickets:detail', pk=ticket.pk)
    else:
        form = TicketForm(instance=ticket, can_assign=can_assign)
    return render(request, 'tickets/ticket_form.html', {'form': form, 'creating': False, 'ticket': ticket})


# ── Derivación / Archivado ─────────────────────────────────────────────────────

def _can_edit_ticket(user, ticket):
    """Editar el ticket es exclusivo de coordinador (capacidad tickets.edit_any)."""
    return has_capability(user, 'tickets.edit_any')


def _can_archive_ticket(user, ticket):
    return (has_capability(user, 'tickets.edit_any')
            or ticket.reporter_id == user.id or ticket.is_participant(user))


def _spawn_child(request, parent, *, title_suffix):
    """Crea un hijo con código jerárquico (SKY-0014-N) heredando labels y asignados del
    padre. Común a «Derivar» (padre sigue activo) y «Dividir» (padre pasa a contenedor)."""
    child = parent.create_child(
        title=f'{parent.title} {title_suffix}',
        solicitante=parent.solicitante,
        project=parent.project,
        reporter=request.user,
        status=parent.status,
    )
    child.labels.set(parent.labels.all())
    executor_users = [a.user for a in parent.executor_assignments]
    expert_users = [a.user for a in parent.expert_assignments]
    # El hijo nace en la misma columna que el padre: los Assignment nuevos arrancan en
    # `parent.status` (no en TODO) para que el recompute_status() de _sync_assignments
    # derive ese mismo estado — y, a diferencia de pisar `child.status` por fuera, se
    # mantenga ahí ante cualquier recompute posterior (mover un subticket, aprobar, etc.).
    # BACKLOG no es un estado válido de Assignment (implica cero ejecutores): ticket_move ya
    # no permite que esto ocurra, pero se mantiene como defensa en profundidad ante otras
    # vías de mutación futuras.
    child_assignment_status = parent.status if parent.status in _DRAG_STATUSES else Ticket.Status.TODO
    added = _sync_assignments(child, executor_users, expert_users, status=child_assignment_status)
    _notify_assignment(request, child, added)
    return child


@login_required
@require_capability('tickets.create')
def ticket_derive(request, pk):
    """Desprende una subtarea subordinada: el padre sigue activo en el tablero."""
    parent = get_object_or_404(Ticket, pk=pk)
    child = _spawn_child(request, parent, title_suffix='(derivado)')
    _log(child, request.user, 'created', f'derivado de {parent.key}')
    messages.success(request, f'{child.key} creado (deriva de {parent.key}). Completá los datos.')
    return redirect('tickets:edit', pk=child.pk)


@login_required
@require_capability('tickets.create')
def ticket_divide(request, pk):
    """Descompone el ticket en partes hermanas (-1, -2…): el original pasa a ser un
    contenedor oculto del tablero — deja de ser una card activa, solo se ven las partes."""
    parent = get_object_or_404(Ticket, pk=pk)
    child = _spawn_child(request, parent, title_suffix='(parte)')
    if not parent.is_split:
        parent.split_at = timezone.now()
        parent.save(update_fields=['split_at', 'updated'])
        _log(parent, request.user, 'split', 'dividido en partes')
    _log(child, request.user, 'created', f'parte de {parent.key}')
    messages.success(request, f'{child.key} creado (parte de {parent.key}). Completá los datos.')
    return redirect('tickets:edit', pk=child.pk)


@login_required
@require_POST
def ticket_archive(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    if not _can_archive_ticket(request.user, ticket):
        raise PermissionDenied
    if ticket.status not in (Ticket.Status.DONE, Ticket.Status.WAITING):
        messages.error(request, 'Solo se archivan tickets Concluidos o Suspendidos/Cancelados.')
    else:
        ticket.archived_at = timezone.now()
        ticket.save(update_fields=['archived_at', 'updated'])
        _log(ticket, request.user, 'archived', 'archivó el ticket')
        messages.success(request, f'{ticket.key} archivado.')
    return redirect('tickets:board')


@login_required
@require_POST
def ticket_unarchive(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    if not request.user.is_superuser:
        raise PermissionDenied
    ticket.archived_at = None
    ticket.save(update_fields=['archived_at', 'updated'])
    _log(ticket, request.user, 'archived', 'desarchivó el ticket')
    messages.success(request, f'{ticket.key} desarchivado.')
    return redirect('tickets:archived')


@login_required
def archived(request):
    qs = _visible_tickets(request.user, include_archived=True, include_split=True).filter(
        archived_at__isnull=False,
    ).order_by('-archived_at')
    page_obj = Paginator(qs, 30).get_page(request.GET.get('page'))
    return render(request, 'tickets/archived.html', {
        'page_obj': page_obj, 'is_superuser': request.user.is_superuser,
    })


# ── Listados ──────────────────────────────────────────────────────────────────

_MY_TICKETS_SORTS = {
    # due_date NULL al final en los 3 primeros: sin vencimiento no debe taparle el
    # puesto a lo que sí tiene fecha (o prioridad) encima.
    'vence': [F('due_date').asc(nulls_last=True), '-prio_rank', '-created'],
    'prioridad': ['-prio_rank', F('due_date').asc(nulls_last=True), '-created'],
    'actividad': [F('last_at').desc(nulls_last=True), '-updated'],
    'modificado': ['-updated'],
}


@login_required
def my_tickets(request):
    last = Comment.objects.filter(ticket=OuterRef('pk')).order_by('-created')
    sort = request.GET.get('sort') if request.GET.get('sort') in _MY_TICKETS_SORTS else 'vence'
    qs = _apply_filters(
        Ticket.objects.select_related('reporter', 'project')
        .filter(assignments__user=request.user, split_at__isnull=True)
        # Se excluye por el Assignment propio (no por Ticket.status): un padre puede
        # quedar en DONE por desync de ticket_move mientras el subticket propio sigue
        # abierto (p.ej. tras derivar un ticket), y ese caso debe seguir viéndose acá.
        .exclude(assignments__user=request.user, assignments__status=Ticket.Status.DONE,
                 assignments__approved_at__isnull=False)
        .annotate(
            last_body=Subquery(last.values('body')[:1]),
            last_at=Subquery(last.values('created')[:1]),
            last_author_first=Subquery(last.values('author__first_name')[:1]),
            last_author_last=Subquery(last.values('author__last_name')[:1]),
            last_author_email=Subquery(last.values('author__email')[:1]),
            prio_rank=Case(
                When(priority=Ticket.Priority.URGENT, then=Value(4)),
                When(priority=Ticket.Priority.HIGH, then=Value(3)),
                When(priority=Ticket.Priority.MEDIUM, then=Value(2)),
                default=Value(1), output_field=IntegerField(),
            ),
        )
        .prefetch_related('labels', 'assignments__user__profile').distinct(),
        request,
    ).order_by(*_MY_TICKETS_SORTS[sort])
    page_obj = Paginator(qs, 24).get_page(request.GET.get('page'))
    # La card debe reflejar el avance propio del usuario (su Assignment), no el estado
    # agregado del ticket: recompute_status() lo deja en IN_PROGRESS hasta que todos los
    # ejecutores concluyan y el coordinador apruebe (models.py:212-236), aunque este
    # usuario ya haya terminado su parte — mismo criterio que _executor_columns.
    now = timezone.now()
    for t in page_obj:
        mine = next((a for a in t.assignments.all() if a.user_id == request.user.id), None)
        t.display_status = mine.status if mine else t.status
        t.display_status_label = Ticket.Status(t.display_status).label
        t.pending_approval = bool(mine) and mine.status == Ticket.Status.DONE \
            and t.status != Ticket.Status.DONE
        t.my_in_progress = _fmt_delta(mine.time_in(Ticket.Status.IN_PROGRESS, now)) if mine else None
    return render(request, 'tickets/my_tickets.html', {
        'page_obj': page_obj, 'sort': sort,
    })


@login_required
@require_capability('tickets.edit_any')
def labels_manage(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add':
            name = request.POST.get('name', '').strip()
            color = request.POST.get('color', Label.Color.NEUTRAL)
            if name and color in dict(Label.Color.choices):
                Label.objects.get_or_create(name=name, defaults={'color': color})
                messages.success(request, f'Etiqueta «{name}» creada.')
        elif action == 'delete':
            Label.objects.filter(pk=request.POST.get('id')).delete()
            messages.success(request, 'Etiqueta eliminada.')
        return redirect('tickets:labels')
    return render(request, 'tickets/labels.html', {
        'labels': Label.objects.all(), 'colors': Label.Color.choices,
    })


@login_required
@require_capability('projects.manage')
def projects_manage(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add':
            form = ProjectForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, 'Proyecto creado.')
            else:
                messages.error(request, 'Revisá los datos (¿código repetido?).')
        elif action == 'edit':
            project = get_object_or_404(Project, pk=request.POST.get('id'))
            form = ProjectForm(request.POST, instance=project)
            if form.is_valid():
                form.save()
                messages.success(request, 'Proyecto actualizado.')
            else:
                messages.error(request, 'No se pudo actualizar (¿código repetido?).')
        elif action == 'delete':
            get_object_or_404(Project, pk=request.POST.get('id')).delete()
            messages.success(request, 'Proyecto eliminado.')
        return redirect('tickets:projects')
    projects = Project.objects.annotate(num_tickets=Count('tickets'))
    return render(request, 'tickets/projects.html', {
        'projects': projects, 'form': ProjectForm(), 'statuses': Project.Status.choices,
    })


@login_required
@require_capability('chat.view_all')
def seguimiento(request):
    # Últimos dos comentarios por ticket vía subquery (sin cargar todos los comentarios en
    # memoria): [:1] trae el más reciente, [1:2] el anterior a ese.
    last = Comment.objects.filter(ticket=OuterRef('pk')).order_by('-created')
    qs = (
        Ticket.objects.select_related('reporter', 'project')
        .exclude(status=Ticket.Status.BACKLOG)
        .annotate(
            last_body=Subquery(last.values('body')[:1]),
            last_at=Subquery(last.values('created')[:1]),
            last_author_first=Subquery(last.values('author__first_name')[:1]),
            last_author_last=Subquery(last.values('author__last_name')[:1]),
            last_author_email=Subquery(last.values('author__email')[:1]),
            prev_body=Subquery(last.values('body')[1:2]),
            prev_at=Subquery(last.values('created')[1:2]),
            prev_author_first=Subquery(last.values('author__first_name')[1:2]),
            prev_author_last=Subquery(last.values('author__last_name')[1:2]),
            prev_author_email=Subquery(last.values('author__email')[1:2]),
        )
        .prefetch_related('labels')
        .order_by('-updated')
    )
    page_obj = Paginator(qs, 25).get_page(request.GET.get('page'))
    return render(request, 'tickets/seguimiento.html', {'page_obj': page_obj})


def _with_pct(items):
    """Añade 'pct' (0-100) a cada dict de `items` según su 'count' relativo al mayor de la
    lista — así cada sección de barras escala a su propio máximo."""
    top = max((i['count'] for i in items), default=0) or 1
    for i in items:
        i['pct'] = round(100 * i['count'] / top)
    return items


@login_required
@require_capability('dashboard.view')
def dashboard(request):
    today = timezone.localdate()
    # Archivados y contenedores divididos (split_at) ya no son actionables: no deben
    # inflar los conteos del dashboard (el board tampoco los muestra).
    active = Ticket.objects.filter(archived_at__isnull=True, split_at__isnull=True)
    counts = {row['status']: row['n'] for row in active.values('status').annotate(n=Count('id'))}
    open_count = active.exclude(status=Ticket.Status.DONE).count()
    overdue = active.filter(due_date__lt=today).exclude(status=Ticket.Status.DONE).count()
    # "Pendiente de aprobación": el ejecutor ya concluyó su subticket pero el coordinador
    # no lo aprobó — mismo criterio que t.pending_approval en el tablero/mis-tickets.
    pending_approval = (
        Assignment.objects.filter(
            kind=Assignment.Kind.EJECUTOR, status=Ticket.Status.DONE, approved_at__isnull=True,
        ).values('ticket_id').distinct().count()
    )
    done_30d = active.filter(
        status=Ticket.Status.DONE, closed_date__date__gte=today - timedelta(days=30),
    ).count()

    kpis = [
        {'label': 'Activos', 'count': active.count(), 'color': 'neutral'},
        {'label': 'Abiertos', 'count': open_count, 'color': 'warning'},
        {'label': 'En progreso', 'count': counts.get(Ticket.Status.IN_PROGRESS, 0), 'color': 'info'},
        {'label': 'Vencidos', 'count': overdue, 'color': 'error'},
        {'label': 'Por aprobar', 'count': pending_approval, 'color': 'success'},
        {'label': 'Concluidos (30d)', 'count': done_30d, 'color': 'success'},
    ]

    # Reutiliza el mapeo de colores ya definido en el modelo (status_color/priority_color)
    # sobre una instancia sin guardar — evita duplicar el dict value→color una vez más.
    status_rows = _with_pct([
        {'label': l, 'count': counts.get(v, 0), 'color': Ticket(status=v).status_color}
        for v, l in Ticket.Status.choices
    ])

    priority_counts = {
        row['priority']: row['n'] for row in
        active.exclude(status=Ticket.Status.DONE).values('priority').annotate(n=Count('id'))
    }
    priority_rows = _with_pct([
        {'label': l, 'count': priority_counts.get(v, 0), 'color': Ticket(priority=v).priority_color}
        for v, l in Ticket.Priority.choices
    ])

    by_assignee = _with_pct([
        {
            'label': (f"{r['user__first_name']} {r['user__last_name']}".strip()
                      or r['user__email'] or r['user__username']),
            'count': r['n'], 'color': 'neutral',
        }
        for r in Assignment.objects.filter(kind=Assignment.Kind.EJECUTOR)
        .exclude(ticket__status=Ticket.Status.DONE)
        .values('user__email', 'user__username', 'user__first_name', 'user__last_name')
        .annotate(n=Count('ticket', distinct=True)).order_by('-n')[:8]
    ])

    by_project = _with_pct([
        {'label': f"{r['project__code']} · {r['project__name']}", 'count': r['n'], 'color': 'neutral'}
        for r in active.exclude(status=Ticket.Status.DONE).filter(project__isnull=False)
        .values('project__code', 'project__name').annotate(n=Count('id')).order_by('-n')[:8]
    ])

    # Tiempo medio en cada estado (Assignment.time_in_progress/time_todo, ver models.py) y
    # tiempo medio de resolución (closed_date - created) — solo sobre lo ya concluido.
    time_avgs = Assignment.objects.filter(
        kind=Assignment.Kind.EJECUTOR, status=Ticket.Status.DONE,
    ).aggregate(avg_in_progress=Avg('time_in_progress'), avg_todo=Avg('time_todo'))
    avg_resolution = active.filter(
        status=Ticket.Status.DONE, closed_date__isnull=False,
    ).aggregate(
        avg=Avg(ExpressionWrapper(F('closed_date') - F('created'), output_field=DurationField())),
    )['avg']
    time_metrics = [
        {'label': 'Tiempo medio en progreso', 'value': _fmt_delta(time_avgs['avg_in_progress'])},
        {'label': 'Tiempo medio en Por hacer', 'value': _fmt_delta(time_avgs['avg_todo'])},
        {'label': 'Tiempo medio de resolución', 'value': _fmt_delta(avg_resolution)},
    ]

    # Throughput: concluidos por semana (lunes a lunes), últimas 8 semanas completas.
    since = today - timedelta(weeks=8)
    weekly_counts = {
        row['week'].date(): row['n'] for row in
        active.filter(status=Ticket.Status.DONE, closed_date__date__gte=since)
        .annotate(week=TruncWeek('closed_date')).values('week').annotate(n=Count('id'))
    }
    week_start = today - timedelta(days=today.weekday())
    throughput = []
    for i in range(7, -1, -1):
        wk = week_start - timedelta(weeks=i)
        throughput.append({'label': wk.strftime('%d/%m'), 'count': weekly_counts.get(wk, 0)})
    # Geometría de las columnas ya resuelta en Python (x/y/height): el template solo
    # imprime números, sin aritmética de tags — SVG viewBox fijo "0 0 100 40". Se
    # convierten a str porque LANGUAGE_CODE='es' hace que Django renderice floats con
    # coma decimal ("12,5") en vez de punto, lo que rompe los atributos numéricos del SVG.
    top_week = max((w['count'] for w in throughput), default=0) or 1
    bar_w, gap, chart_h, pad_top = 9, 4, 32, 4
    for idx, w in enumerate(throughput):
        height = round((w['count'] / top_week) * chart_h)
        w['height'] = str(height)
        w['y'] = str(pad_top + chart_h - height)
        w['x'] = str(idx * (bar_w + gap))
        w['w'] = str(bar_w)

    return render(request, 'tickets/dashboard.html', {
        'kpis': kpis,
        'status_rows': status_rows,
        'priority_rows': priority_rows,
        'by_assignee': by_assignee,
        'by_project': by_project,
        'time_metrics': time_metrics,
        'throughput': throughput,
    })
