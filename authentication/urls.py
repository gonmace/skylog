from django.urls import path
from django.views.generic import TemplateView
from .views import (
    NextcloudOAuth2AuthorizeView,
    NextcloudOAuth2CallbackView,
    AgentSetupView,
    AgentOAuth2RedirectView,
)

app_name = 'authentication'

urlpatterns = [
    path('', TemplateView.as_view(template_name='authentication/login.html'), name='login'),
    path('nextcloud/', NextcloudOAuth2AuthorizeView.as_view(), name='oauth2_authorize'),
    path('callback/', NextcloudOAuth2CallbackView.as_view(), name='oauth2_callback'),
    path('agent/setup/', AgentSetupView.as_view(), name='agent_setup'),
    path('agent/oauth/', AgentOAuth2RedirectView.as_view(), name='agent_oauth'),
]
