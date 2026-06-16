from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import render

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken

from authentication.views import _set_jwt_cookies
from employees.models import Employee
from .models import Visitor, VisitLog
from .serializers import VisitorSerializer


def _client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _can_manage_visits(user):
    if user.is_superuser:
        return True
    try:
        return bool(user.employee.can_manage_visits)
    except Employee.DoesNotExist:
        return False


# ── Páginas (shells HTML) ──────────────────────────────────────────────────────

def manage_view(request):
    """Shell de gestión de visitas. La protección real se valida en frontend (me) + API."""
    return render(request, 'visits/manage.html')


def login_view(request):
    """Login de visitantes (solo correo)."""
    return render(request, 'visits/login.html')


# ── Gestión de visitantes (superuser o can_manage_visits) ──────────────────────

class VisitorListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can_manage_visits(request.user):
            return Response({'error': 'Acceso no autorizado'}, status=403)
        visitors = Visitor.objects.all().order_by('full_name')
        return Response(VisitorSerializer(visitors, many=True).data)

    def post(self, request):
        if not _can_manage_visits(request.user):
            return Response({'error': 'Acceso no autorizado'}, status=403)

        full_name = (request.data.get('full_name') or '').strip()
        email = (request.data.get('email') or '').strip().lower()
        if not full_name or not email:
            return Response({'error': 'Nombre y correo son requeridos'}, status=400)
        if Visitor.objects.filter(email=email).exists() or User.objects.filter(username=email).exists():
            return Response({'error': 'Ya existe un usuario con ese correo'}, status=400)

        try:
            with transaction.atomic():
                user = User.objects.create(username=email, email=email, first_name=full_name[:150])
                user.set_unusable_password()
                user.save(update_fields=['password'])
                visitor = Visitor.objects.create(user=user, full_name=full_name, email=email)
        except IntegrityError:
            return Response({'error': 'Ya existe un usuario con ese correo'}, status=400)

        return Response(VisitorSerializer(visitor).data, status=status.HTTP_201_CREATED)


class VisitorDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, visitor_id):
        """Activa/desactiva un visitante."""
        if not _can_manage_visits(request.user):
            return Response({'error': 'Acceso no autorizado'}, status=403)
        try:
            visitor = Visitor.objects.get(id=visitor_id)
        except Visitor.DoesNotExist:
            return Response({'error': 'Visita no encontrada'}, status=404)

        if 'is_active' in request.data:
            visitor.is_active = bool(request.data.get('is_active'))
            visitor.save(update_fields=['is_active'])
            visitor.user.is_active = visitor.is_active
            visitor.user.save(update_fields=['is_active'])
        return Response(VisitorSerializer(visitor).data)

    def delete(self, request, visitor_id):
        if not _can_manage_visits(request.user):
            return Response({'error': 'Acceso no autorizado'}, status=403)
        try:
            visitor = Visitor.objects.get(id=visitor_id)
        except Visitor.DoesNotExist:
            return Response({'error': 'Visita no encontrada'}, status=404)
        visitor.user.delete()  # cascada elimina Visitor + VisitLog
        return Response(status=status.HTTP_204_NO_CONTENT)


class VisitorLogsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, visitor_id):
        if not _can_manage_visits(request.user):
            return Response({'error': 'Acceso no autorizado'}, status=403)
        try:
            visitor = Visitor.objects.get(id=visitor_id)
        except Visitor.DoesNotExist:
            return Response({'error': 'Visita no encontrada'}, status=404)
        logs = [{
            'logged_at': log.logged_at,
            'ip_address': log.ip_address,
        } for log in visitor.logins.order_by('-logged_at')[:200]]
        return Response({'full_name': visitor.full_name, 'email': visitor.email, 'logins': logs})


# ── Login de visitantes (solo correo) ──────────────────────────────────────────

def _active_visitor(email):
    try:
        return Visitor.objects.select_related('user').get(email=email, is_active=True)
    except Visitor.DoesNotExist:
        return None


def _issue_tokens(visitor, request):
    """Registra el ingreso y emite JWT (con cookies), igual que el login móvil."""
    VisitLog.objects.create(visitor=visitor, ip_address=_client_ip(request))
    refresh = RefreshToken.for_user(visitor.user)
    access = str(refresh.access_token)
    ref = str(refresh)
    response = Response({'status': 'ok', 'access': access, 'refresh': ref})
    _set_jwt_cookies(response, access, ref)
    return response


class VisitorAuthCheckView(APIView):
    """Paso 1: el visitante ingresa su correo. Indica si existe y si ya tiene contraseña."""
    permission_classes = [AllowAny]

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        if not email:
            return Response({'error': 'Correo requerido'}, status=400)
        visitor = _active_visitor(email)
        if not visitor:
            return Response({'exists': False})
        return Response({
            'exists': True,
            'has_password': visitor.user.has_usable_password(),
            'full_name': visitor.full_name,
        })


class VisitorSetPasswordView(APIView):
    """Paso 2 (primera vez): el visitante crea su contraseña y queda logueado."""
    permission_classes = [AllowAny]

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        password = request.data.get('password') or ''
        visitor = _active_visitor(email)
        if not visitor:
            return Response({'error': 'Correo no autorizado'}, status=400)
        if visitor.user.has_usable_password():
            return Response({'error': 'La contraseña ya fue creada. Inicia sesión.'}, status=400)
        try:
            validate_password(password, visitor.user)
        except ValidationError as e:
            return Response({'error': ' '.join(e.messages)}, status=400)

        visitor.user.set_password(password)
        visitor.user.save(update_fields=['password'])
        return _issue_tokens(visitor, request)


class VisitorLoginView(APIView):
    """Paso 2 (siguientes veces): el visitante ingresa su contraseña."""
    permission_classes = [AllowAny]

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        password = request.data.get('password') or ''
        visitor = _active_visitor(email)
        if not visitor:
            return Response({'error': 'Correo no autorizado'}, status=400)

        user = authenticate(request, username=email, password=password)
        if user is None or user.id != visitor.user_id:
            return Response({'error': 'Contraseña incorrecta'}, status=status.HTTP_401_UNAUTHORIZED)
        return _issue_tokens(visitor, request)
