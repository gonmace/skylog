from django.urls import path
from django.views.generic import TemplateView

app_name = 'workdays'

urlpatterns = [
    path('', TemplateView.as_view(template_name='dashboard/dashboard.html'), name='dashboard'),
]
