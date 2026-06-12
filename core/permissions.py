from rest_framework.permissions import BasePermission
from django.conf import settings


class IsInternalRequest(BasePermission):
    """Auth para endpoints internos disparados por n8n via header X-Internal-Token."""
    message = 'No autorizado'

    def has_permission(self, request, view):
        token = request.headers.get('X-Internal-Token', '')
        return bool(token) and token == settings.INTERNAL_API_TOKEN
