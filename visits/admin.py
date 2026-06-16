from django.contrib import admin
from core.admin import admin_site
from .models import Visitor, VisitLog


class VisitLogInline(admin.TabularInline):
    model = VisitLog
    extra = 0
    can_delete = False
    readonly_fields = ['logged_at', 'ip_address']
    ordering = ['-logged_at']

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Visitor, site=admin_site)
class VisitorAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'email', 'is_active', 'login_count', 'last_login_at', 'created_at']
    list_filter = ['is_active']
    search_fields = ['full_name', 'email']
    ordering = ['full_name']
    readonly_fields = ['user', 'created_at']
    inlines = [VisitLogInline]

    @admin.display(description='Ingresos')
    def login_count(self, obj):
        return obj.login_count

    @admin.display(description='Último ingreso')
    def last_login_at(self, obj):
        return obj.last_login_at
