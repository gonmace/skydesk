from django.contrib import admin

from .models import AllowedDomain, AllowedEmail, Profile, RolePermission


@admin.register(AllowedDomain)
class AllowedDomainAdmin(admin.ModelAdmin):
    list_display = ('domain', 'default_role', 'is_active', 'created')
    list_filter = ('is_active', 'default_role')
    search_fields = ('domain',)


@admin.register(AllowedEmail)
class AllowedEmailAdmin(admin.ModelAdmin):
    list_display = ('email', 'default_role', 'is_active', 'created')
    list_filter = ('is_active', 'default_role')
    search_fields = ('email',)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'created')
    list_filter = ('role',)
    search_fields = ('user__email', 'user__username')
    autocomplete_fields = ('user',)


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ('role', 'capability', 'enabled')
    list_filter = ('role', 'enabled')
    search_fields = ('capability',)
