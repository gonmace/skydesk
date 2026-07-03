from django.contrib import admin

from .models import Attachment


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ('filename', 'mime_type', 'size', 'storage_backend', 'content_type', 'object_id', 'created')
    list_filter = ('storage_backend', 'mime_type')
    search_fields = ('filename', 'storage_key')
    readonly_fields = ('created',)
