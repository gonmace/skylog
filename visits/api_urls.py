from django.urls import path
from . import views

urlpatterns = [
    # Gestión (superuser o can_manage_visits)
    path('visits/', views.VisitorListCreateView.as_view()),
    path('visits/<int:visitor_id>/', views.VisitorDetailView.as_view()),
    path('visits/<int:visitor_id>/logs/', views.VisitorLogsView.as_view()),

    # Login de visitantes (solo correo)
    path('visits/auth/check/', views.VisitorAuthCheckView.as_view()),
    path('visits/auth/set-password/', views.VisitorSetPasswordView.as_view()),
    path('visits/auth/login/', views.VisitorLoginView.as_view()),
]
