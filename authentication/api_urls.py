from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    MeView,
    AgentTokenPollView,
    AgentActivateView,
    AgentDownloadView,
    AgentSetupAuthorizeView,
)

urlpatterns = [
    path('auth/me/', MeView.as_view()),
    path('auth/token/refresh/', TokenRefreshView.as_view()),
    path('agent/token/', AgentTokenPollView.as_view()),
    path('agent/activate/', AgentActivateView.as_view()),
    path('agent/download/', AgentDownloadView.as_view()),
    path('agent/setup/', AgentSetupAuthorizeView.as_view()),
]
