from django.contrib import admin

from .models import Assignment, Comment, Label, Project, Ticket


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    fields = ('author', 'body', 'created')
    readonly_fields = ('created',)


class AssignmentInline(admin.TabularInline):
    model = Assignment
    extra = 0
    fields = ('user', 'kind', 'status', 'started_at', 'closed_date', 'approved_at')
    autocomplete_fields = ('user',)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('key', 'company', 'title', 'status', 'priority', 'reporter', 'updated')
    list_filter = ('company', 'status', 'priority')
    search_fields = ('title', 'description', 'code')
    autocomplete_fields = ('reporter', 'parent')
    inlines = [AssignmentInline, CommentInline]

    @admin.display(description='Key')
    def key(self, obj):
        return obj.key


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'author', 'created')
    list_filter = ('ticket__company',)
    search_fields = ('body',)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'company', 'city', 'status')
    list_filter = ('company', 'status')
    search_fields = ('code', 'name')


@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'color')
    list_filter = ('company', 'color')
    search_fields = ('name',)
