from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from django.contrib.sitemaps.views import sitemap
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from home.sitemaps import StaticViewSitemap
from core.admin import admin_site

sitemaps = {
    'static': StaticViewSitemap,
}

def health_check(request):
    return JsonResponse({'status': 'ok'})


urlpatterns = [
    path('health/', health_check),
    path(settings.ADMIN_URL, admin_site.urls),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', TemplateView.as_view(
        template_name='robots.txt',
        content_type='text/plain',
        extra_context={'ADMIN_URL': settings.ADMIN_URL},
    )),
    path('api/', include('authentication.api_urls')),
    path('api/', include('workdays.api_urls')),
    path('api/', include('screenshots.api_urls')),
    path('api/', include('visits.api_urls')),
    path('login/', include('authentication.urls')),
    path('reporte/', include('workdays.reporte_urls')),
    path('estadisticas/', include('workdays.estadisticas_urls')),
    path('visitas/', include('visits.urls')),
    path('etiquetas/', never_cache(TemplateView.as_view(template_name='workdays/tags.html')), name='tags_admin'),
    path('permisos/', never_cache(TemplateView.as_view(template_name='workdays/permisos.html')), name='permisos_admin'),
    path('dashboard/', include('workdays.urls')),
    path('dashboard/employee/', never_cache(TemplateView.as_view(template_name='dashboard/employee.html')), name='dashboard_employee'),
    path('dashboard/executive/', never_cache(TemplateView.as_view(template_name='dashboard/executive.html')), name='dashboard_executive'),
    path('mobile/', never_cache(TemplateView.as_view(template_name='mobile/dashboard.html')), name='mobile_dashboard'),
    path('', include('home.urls')),
]

if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns
    from authentication.views import DevLoginView

    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += [
        path('__reload__/', include('django_browser_reload.urls')),
        path('dev-login/', DevLoginView.as_view(), name='dev_login'),
    ]
