from django.urls import path
from . import views

app_name = 'estadisticas'

urlpatterns = [
    path('', views.estadisticas_view, name='index'),
]
