from django.urls import path
from django.views.decorators.cache import never_cache
from . import views

app_name = 'visits'

urlpatterns = [
    path('', never_cache(views.manage_view), name='manage'),
    path('login/', never_cache(views.login_view), name='login'),
]
