from django.contrib.admin import AdminSite
from django.utils import timezone


class RedLineAdminSite(AdminSite):
    site_header = 'RedLine GS — Panel Administrativo'
    site_title = 'RedLine GS Admin'
    index_title = 'Panel de Control'

    def index(self, request, extra_context=None):
        from workdays.models import Workday
        from screenshots.models import Screenshot
        today = timezone.now().date()
        extra_context = extra_context or {}
        extra_context.update({
            'today': today,
            'active_count': Workday.objects.filter(status='in_progress').count(),
            'completed_count': Workday.objects.filter(status='completed', start_time__date=today).count(),
            'screenshot_count': Screenshot.objects.filter(captured_at__date=today).count(),
        })
        return super().index(request, extra_context)


admin_site = RedLineAdminSite(name='admin')

# Register Django built-in models with the custom site
from django.contrib.auth.models import User, Group
from django.contrib.auth.admin import UserAdmin, GroupAdmin

admin_site.register(User, UserAdmin)
admin_site.register(Group, GroupAdmin)
