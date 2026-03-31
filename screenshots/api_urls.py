from django.urls import path
from .views import ScreenshotUploadView, ScreenshotImageView

urlpatterns = [
    path('screenshot/', ScreenshotUploadView.as_view()),
    path('screenshot/<int:pk>/image/', ScreenshotImageView.as_view(), name='screenshot-image'),
]
