import logging
from django.contrib import admin, messages
from django.conf import settings
from django.utils.html import format_html
from rest_framework_simplejwt.tokens import RefreshToken
from core.admin import admin_site
from .models import Employee

log = logging.getLogger(__name__)


@admin.register(Employee, site=admin_site)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'nextcloud_username', 'department', 'is_active', 'is_executive', 'solo_movil', 'agent_version_badge', 'created_at']
    list_filter = ['department', 'is_active', 'is_executive', 'solo_movil']
    search_fields = ['full_name', 'nextcloud_username', 'user__email']
    ordering = ['full_name']
    readonly_fields = ['created_at', 'nextcloud_username', 'agent_version', 'agent_last_seen', 'agent_token']
    actions = ['request_capture']

    fieldsets = [
        ('Información', {'fields': ['user', 'nextcloud_username', 'full_name', 'department', 'is_active', 'is_executive', 'solo_movil', 'created_at']}),
        ('Agente', {'fields': ['agent_version', 'agent_last_seen', 'capture_interval_minutes', 'screenshots_enabled'], 'description': 'Intervalo vacío = usa el global.'}),
        ('Token para agente Windows', {'fields': ['agent_token'], 'classes': ['collapse']}),
    ]

    @admin.action(description='Solicitar captura inmediata')
    def request_capture(self, request, queryset):
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()
        sent = 0
        skipped_exec = 0

        for employee in queryset.filter(is_active=True):
            if employee.is_executive:
                skipped_exec += 1
                continue
            try:
                async_to_sync(channel_layer.group_send)(
                    f'agent_{employee.pk}',
                    {'type': 'capture.command', 'command': 'capture'},
                )
                sent += 1
                log.info('Captura solicitada para employee_id=%s por user=%s', employee.pk, request.user.username)
            except Exception as e:
                log.error('Error enviando captura a employee_id=%s: %s', employee.pk, e)

        if sent:
            self.message_user(request, f'Solicitud enviada a {sent} agente(s).', level=messages.SUCCESS)
        if skipped_exec:
            self.message_user(request, f'{skipped_exec} ejecutivo(s) omitidos.', level=messages.INFO)

    def agent_version_badge(self, obj):
        version = obj.agent_version or '—'
        latest = getattr(settings, 'AGENT_LATEST_VERSION', '')
        if not obj.agent_version:
            color, label = '#9ca3af', version
        elif latest and obj.agent_version != latest:
            color, label = '#f59e0b', f'{version} → {latest} disponible'
        else:
            color, label = '#10b981', version
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:12px;font-size:12px;white-space:nowrap;">{}</span>',
            color, label,
        )
    agent_version_badge.short_description = 'Versión agente'

    def agent_token(self, obj):
        import json as _json
        try:
            refresh = RefreshToken.for_user(obj.user)
            config_snippet = _json.dumps({
                'server_url': settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else 'https://skylog.redlinegs.com',
                'jwt_token': str(refresh.access_token),
                'refresh_token': str(refresh),
                'capture_interval_minutes': 30,
            }, indent=2)
        except Exception as e:
            return format_html('<span style="color:red;">Error: {}</span>', str(e))

        return format_html(
            '''
            <div style="display:flex;align-items:center;gap:8px;">
              <textarea id="jwt-{id}" readonly rows="7"
                style="font-family:monospace;font-size:11px;padding:6px 8px;border:1px solid #ccc;
                       border-radius:4px;width:480px;background:#f9f9f9;color:#333;resize:none;">{config}</textarea>
              <button type="button"
                onclick="
                  var inp = document.getElementById('jwt-{id}');
                  navigator.clipboard.writeText(inp.value);
                  this.textContent='✓ Copiado';
                  setTimeout(()=>this.textContent='Copiar',2000);
                "
                style="padding:6px 12px;background:#6366f1;color:#fff;border:none;
                       border-radius:4px;cursor:pointer;white-space:nowrap;align-self:flex-start;">
                Copiar
              </button>
            </div>
            <p style="margin:6px 0 0;font-size:11px;color:#888;">
              Reemplaza el contenido de <code>config.json</code> del agente Windows.
              El access token caduca en 8 horas, pero el refresh token permite renovarlo automáticamente.
            </p>
            ''',
            id=obj.pk,
            config=config_snippet,
        )
    agent_token.short_description = 'config.json para agente'
