from django.urls import path
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView

app_name = 'workdays'

urlpatterns = [
    path('', never_cache(TemplateView.as_view(template_name='dashboard/dashboard.html')), name='dashboard'),
]
