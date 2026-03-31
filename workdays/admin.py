import csv
from django.contrib import admin
from django.http import HttpResponse
from django.utils.html import format_html
from core.admin import admin_site
from .models import Workday, DailyReport, CaptureConfig
from screenshots.models import Screenshot


class DailyReportInline(admin.StackedInline):
    model = DailyReport
    extra = 0
    readonly_fields = ['submitted_at']


class ScreenshotInline(admin.TabularInline):
    model = Screenshot
    extra = 0
    readonly_fields = ['thumbnail', 'captured_at', 'file_path']
    fields = ['thumbnail', 'captured_at', 'file_path']

    def thumbnail(self, obj):
        return format_html('<img src="{}" style="max-height:80px; border-radius:4px;">', obj.get_absolute_url())
    thumbnail.short_description = 'Vista previa'


@admin.register(Workday, site=admin_site)
class WorkdayAdmin(admin.ModelAdmin):
    list_display = ['employee', 'start_time', 'end_time', 'duration_minutes', 'status_badge']
    list_filter = ['status', 'start_time', 'employee__department']
    search_fields = ['employee__full_name', 'employee__nextcloud_username']
    ordering = ['-start_time']
    inlines = [DailyReportInline, ScreenshotInline]
    date_hierarchy = 'start_time'
    actions = ['export_csv']
    readonly_fields = ['duration_minutes']

    def status_badge(self, obj):
        colors = {
            'in_progress': '#10b981',
            'completed': '#6366f1',
            'incomplete': '#f59e0b',
        }
        color = colors.get(obj.status, '#999')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:12px;font-size:12px;">{}</span>',
            color,
            obj.get_status_display(),
        )
    status_badge.short_description = 'Estado'

    @admin.action(description='Exportar selección a CSV')
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="jornadas.csv"'
        response.write('\ufeff')  # BOM for Excel
        writer = csv.writer(response)
        writer.writerow([
            'Empleado', 'Usuario Nextcloud', 'Departamento',
            'Inicio', 'Fin', 'Duración (min)', 'Estado',
            'Actividades realizadas', 'Actividades planificadas',
        ])
        for w in queryset.select_related('employee', 'daily_report'):
            report = getattr(w, 'daily_report', None)
            writer.writerow([
                w.employee.full_name,
                w.employee.nextcloud_username,
                w.employee.department,
                w.start_time.strftime('%Y-%m-%d %H:%M'),
                w.end_time.strftime('%Y-%m-%d %H:%M') if w.end_time else '',
                w.duration_minutes or '',
                w.get_status_display(),
                report.activities_done if report else '',
                report.activities_planned if report else '',
            ])
        return response


@admin.register(CaptureConfig, site=admin_site)
class CaptureConfigAdmin(admin.ModelAdmin):
    fields = ['capture_interval_minutes']

    def has_add_permission(self, request):
        return not CaptureConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Redirigir directo al formulario de edición del singleton
        CaptureConfig.objects.get_or_create(pk=1)
        from django.urls import reverse
        from django.shortcuts import redirect
        url = reverse('admin:workdays_captureconfig_change', args=[1])
        return redirect(url)


@admin.register(DailyReport, site=admin_site)
class DailyReportAdmin(admin.ModelAdmin):
    list_display = ['workday', 'submitted_at']
    search_fields = ['workday__employee__full_name', 'activities_done', 'activities_planned']
    readonly_fields = ['submitted_at']
