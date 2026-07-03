from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'verb', 'ticket', 'is_read', 'created')
    list_filter = ('is_read',)
    search_fields = ('verb', 'recipient__email')
