from django.urls import path
from .views import (
    MeView,
    ClaimIframeJWTView,
    CookieTokenRefreshView,
    AgentTokenPollView,
    AgentActivateView,
    AgentDownloadView,
    AgentSetupAuthorizeView,
)

urlpatterns = [
    path('auth/me/', MeView.as_view()),
    path('auth/claim-token/', ClaimIframeJWTView.as_view()),
    path('auth/token/refresh/', CookieTokenRefreshView.as_view()),
    path('agent/token/', AgentTokenPollView.as_view()),
    path('agent/activate/', AgentActivateView.as_view()),
    path('agent/download/', AgentDownloadView.as_view()),
    path('agent/setup/', AgentSetupAuthorizeView.as_view()),
]
