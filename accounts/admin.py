from django.contrib import admin
from django.core.exceptions import ValidationError

from .models import (
    AllowedDomain, AllowedEmail, Company, EmailConfig, NextcloudOAuthConfig, Profile,
    RolePermission,
)


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'ticket_prefix', 'ticket_seq', 'is_active', 'created')
    list_filter = ('is_active',)
    search_fields = ('name', 'slug', 'ticket_prefix')
    readonly_fields = ('ticket_seq', 'created', 'updated')


@admin.register(AllowedDomain)
class AllowedDomainAdmin(admin.ModelAdmin):
    list_display = ('domain', 'company', 'default_role', 'is_active', 'created')
    list_filter = ('company', 'is_active', 'default_role')
    search_fields = ('domain',)


@admin.register(AllowedEmail)
class AllowedEmailAdmin(admin.ModelAdmin):
    list_display = ('email', 'company', 'default_role', 'is_active', 'created')
    list_filter = ('company', 'is_active', 'default_role')
    search_fields = ('email',)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'company', 'role', 'created')
    list_filter = ('company', 'role')
    search_fields = ('user__email', 'user__username')
    autocomplete_fields = ('user',)
    filter_horizontal = ('extra_companies',)

    def save_model(self, request, obj, form, change):
        # Cambiar de empresa a un usuario con trabajo asignado dejaría Assignments
        # cruzando empresas (tickets de A asignados a alguien de B): se bloquea.
        if change and 'company' in form.changed_data:
            from tickets.models import Assignment
            if Assignment.objects.filter(user=obj.user).exclude(ticket__company=obj.company).exists():
                raise ValidationError(
                    'Este usuario tiene tickets asignados en su empresa actual; no se puede mover.'
                )
        super().save_model(request, obj, form, change)


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ('company', 'role', 'capability', 'enabled')
    list_filter = ('company', 'role', 'enabled')
    search_fields = ('capability',)


@admin.register(NextcloudOAuthConfig)
class NextcloudOAuthConfigAdmin(admin.ModelAdmin):
    list_display = ('company', 'enabled', 'base_url', 'updated')
    list_filter = ('enabled',)


@admin.register(EmailConfig)
class EmailConfigAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'host', 'notify_assignment', 'notify_comment', 'updated')
