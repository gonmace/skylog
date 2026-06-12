import csv
from django import forms
from django.contrib import admin
from django.http import HttpResponse
from django.utils.html import format_html
from core.admin import admin_site
from .models import Workday, DailyReport, CaptureConfig, ExecutiveMessage, ActivityItem, ActivityCategory, ActivityTag
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
    list_filter = ['status', 'start_time', 'employee__cargo']
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
                w.employee.cargo,
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


@admin.register(ActivityCategory, site=admin_site)
class ActivityCategoryAdmin(admin.ModelAdmin):
    """Lista de categorías administrable. Las base (is_protected) no se borran ni
    cambian de código; sí se puede editar label/color/orden/activa, y agregar nuevas."""
    list_display = ['order', 'code', 'label', 'color', 'color_swatch', 'is_active', 'is_protected']
    list_display_links = ['code']
    list_editable = ['label', 'color', 'order', 'is_active']
    list_filter = ['is_active', 'is_protected']
    search_fields = ['code', 'label']
    ordering = ['order', 'label']

    def color_swatch(self, obj):
        return format_html(
            '<span style="display:inline-block;width:16px;height:16px;border-radius:4px;'
            'border:1px solid #ccc;background:{};"></span>', obj.color)
    color_swatch.short_description = ''

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_protected:
            return False
        return super().has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        # No permitir cambiar el código (ni desproteger) de una categoría base.
        if obj is not None and obj.is_protected:
            return ['code', 'is_protected']
        return []


@admin.register(ActivityTag, site=admin_site)
class ActivityTagAdmin(admin.ModelAdmin):
    """Inspección de tags extraídos por el LLM. La fusión principal se hace desde
    el dashboard ejecutivo; aquí se puede ver/editar y apuntar `canonical` a mano."""
    list_display = ['name', 'kind', 'canonical', 'item_count', 'created_at']
    list_filter = ['kind']
    search_fields = ['name', 'key']
    raw_id_fields = ['canonical']
    readonly_fields = ['key', 'created_at']

    def item_count(self, obj):
        return obj.items.count()
    item_count.short_description = 'Ítems'


@admin.register(ActivityItem, site=admin_site)
class ActivityItemAdmin(admin.ModelAdmin):
    list_display = ['short_text', 'kind', 'category', 'source', 'matched_keyword', 'manual_override', 'employee_name', 'report_date']
    list_filter = ['category', 'kind', 'source', 'manual_override']
    list_editable = ['category']
    search_fields = ['text', 'report__workday__employee__full_name']
    list_select_related = ['report__workday__employee']
    readonly_fields = ['matched_keyword', 'classified_at']
    actions = ['reclassify']

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        # `category` es un CharField (no FK) pero queremos un dropdown desde la tabla.
        if db_field.name == 'category':
            choices = [(c.code, str(c)) for c in ActivityCategory.objects.order_by('order', 'label')]
            return forms.ChoiceField(choices=choices, required=not db_field.blank)
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def short_text(self, obj):
        return obj.text[:70] + '…' if len(obj.text) > 70 else obj.text
    short_text.short_description = 'Actividad'

    def employee_name(self, obj):
        return obj.report.workday.employee.full_name
    employee_name.short_description = 'Empleado'

    def report_date(self, obj):
        return obj.report.workday.start_time.strftime('%Y-%m-%d')
    report_date.short_description = 'Fecha'

    def save_model(self, request, obj, form, change):
        # Editar la categoría a mano la marca como override (el clasificador no la pisa).
        if change and 'category' in form.changed_data:
            obj.manual_override = True
        super().save_model(request, obj, form, change)

    @admin.action(description='Reclasificar (descarta override manual)')
    def reclassify(self, request, queryset):
        from .classifier import classify
        n = 0
        for item in queryset:
            cat, kw = classify(item.text)
            item.category = cat
            item.matched_keyword = kw
            item.source = ActivityItem.SOURCE_KEYWORD
            item.manual_override = False
            item.save()
            n += 1
        self.message_user(request, f'{n} ítems reclasificados.')


@admin.register(ExecutiveMessage, site=admin_site)
class ExecutiveMessageAdmin(admin.ModelAdmin):
    list_display = ['sent_at', 'sender', 'recipient', 'body_preview', 'acknowledged_at']
    list_filter = ['sent_at', 'acknowledged_at']
    search_fields = ['sender__full_name', 'recipient__full_name', 'body']
    readonly_fields = ['sent_at', 'acknowledged_at']
    ordering = ['-sent_at']
    date_hierarchy = 'sent_at'

    def body_preview(self, obj):
        return obj.body[:80] + '…' if len(obj.body) > 80 else obj.body
    body_preview.short_description = 'Mensaje'
