from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Notification


@login_required
def menu_fragment(request):
    """Badge + dropdown de notificaciones, para refresco AJAX (ver static/js/live.js
    tras un push 'notif.new' por WebSocket) sin recargar la página."""
    recent = list(request.user.notifications.select_related('actor', 'ticket')[:6])
    return render(request, 'notifications/partials/_menu.html', {
        'notif_unread': request.user.notifications.filter(is_read=False).count(),
        'notif_recent': recent,
    })


@login_required
def notifications_list(request):
    qs = request.user.notifications.select_related('actor', 'ticket')
    page_obj = Paginator(qs, 30).get_page(request.GET.get('page'))
    return render(request, 'notifications/list.html', {'page_obj': page_obj})


@login_required
def open_notification(request, pk):
    n = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if not n.is_read:
        n.is_read = True
        n.save(update_fields=['is_read'])
    if n.ticket_id:
        return redirect('tickets:detail', pk=n.ticket_id)
    return redirect('notifications:list')


@login_required
@require_POST
def mark_all_read(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return redirect('notifications:list')
