from django.contrib import admin
from core.admin import admin_site
from .models import Screenshot


@admin.register(Screenshot, site=admin_site)
class ScreenshotAdmin(admin.ModelAdmin):
    list_display = ['employee', 'workday', 'captured_at']
    list_filter = ['employee', 'captured_at']
    search_fields = ['employee__full_name', 'employee__nextcloud_username']
    readonly_fields = ['employee', 'workday', 'file_path', 'captured_at']
    ordering = ['-captured_at']
