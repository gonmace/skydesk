from django.contrib import admin

from .models import Attachment, NextcloudConfig


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ('filename', 'company', 'mime_type', 'size', 'storage_backend', 'content_type', 'object_id', 'created')
    list_filter = ('company', 'storage_backend', 'mime_type')
    search_fields = ('filename', 'storage_key')
    readonly_fields = ('created',)


@admin.register(NextcloudConfig)
class NextcloudConfigAdmin(admin.ModelAdmin):
    list_display = ('company', 'enabled', 'base_url', 'root', 'updated')
    list_filter = ('enabled',)
