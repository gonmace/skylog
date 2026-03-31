import secrets
import requests as http_requests
from django.conf import settings
from django.contrib.auth.models import User
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import AnonRateThrottle


class AgentPollThrottle(AnonRateThrottle):
    rate = '30/min'
from rest_framework_simplejwt.tokens import RefreshToken
from employees.models import Employee
from .models import AgentRegistration, AgentActivationToken
from .serializers import EmployeeSerializer


# ── Helpers compartidos ───────────────────────────────────────────────────────

def _fetch_nextcloud_user(login_name, bearer_token):
    """Obtiene perfil + grupos del usuario desde la OCS API de Nextcloud."""
    display_name = login_name
    email = ''
    is_executive = False
    try:
        ocs_url = f"{settings.NEXTCLOUD_SERVER_URL}/ocs/v1.php/cloud/users/{login_name}?format=json"
        resp = http_requests.get(
            ocs_url,
            headers={
                'OCS-APIREQUEST': 'true',
                'Authorization': f'Bearer {bearer_token}',
            },
            timeout=10,
        )
        if resp.status_code == 200:
            ocs_user = resp.json().get('ocs', {}).get('data', {})
            display_name = ocs_user.get('displayname') or login_name
            email = ocs_user.get('email') or ''
            is_executive = 'skylog' in (ocs_user.get('groups') or [])
    except Exception:
        pass
    return display_name, email, is_executive


def _upsert_user_and_employee(login_name, display_name, email, is_executive):
    """Crea o actualiza el User de Django y el Employee asociado."""
    user, _ = User.objects.get_or_create(username=login_name)
    if email:
        user.email = email
    name_parts = display_name.split(' ', 1)
    user.first_name = name_parts[0]
    user.last_name = name_parts[1] if len(name_parts) > 1 else ''
    user.save()

    employee, _ = Employee.objects.get_or_create(
        nextcloud_username=login_name,
        defaults={'user': user, 'full_name': display_name},
    )
    update_fields = []
    if employee.full_name != display_name:
        employee.full_name = display_name
        update_fields.append('full_name')
    if employee.is_executive != is_executive:
        employee.is_executive = is_executive
        update_fields.append('is_executive')
    if update_fields:
        employee.save(update_fields=update_fields)
    return user, employee


# ── OAuth2 con Nextcloud ──────────────────────────────────────────────────────

class NextcloudOAuth2AuthorizeView(View):
    """Inicia el flujo OAuth2: genera state, guarda en sesión y redirige a Nextcloud."""

    def get(self, request):
        from urllib.parse import urlencode

        state = secrets.token_urlsafe(32)
        request.session['oauth2_state'] = state

        redirect_uri = (
            settings.NEXTCLOUD_OAUTH2_REDIRECT_URI
            or request.build_absolute_uri('/login/callback/')
        )

        params = urlencode({
            'response_type': 'code',
            'client_id': settings.NEXTCLOUD_OAUTH2_CLIENT_ID,
            'redirect_uri': redirect_uri,
            'state': state,
        })
        return redirect(f"{settings.NEXTCLOUD_SERVER_URL}/apps/oauth2/authorize?{params}")


class NextcloudOAuth2CallbackView(View):
    """Maneja el callback OAuth2 de Nextcloud, crea el usuario y emite JWT."""

    def get(self, request):
        error = request.GET.get('error')
        if error:
            return render(request, 'authentication/oauth2_error.html', {'error': error})

        code = request.GET.get('code', '')
        state = request.GET.get('state', '')
        expected_state = request.session.pop('oauth2_state', None)

        if not code or not state or state != expected_state:
            return render(request, 'authentication/oauth2_error.html',
                          {'error': 'Parámetros de autorización inválidos. Intenta de nuevo.'})

        redirect_uri = (
            settings.NEXTCLOUD_OAUTH2_REDIRECT_URI
            or request.build_absolute_uri('/login/callback/')
        )

        # Intercambiar code por access_token
        try:
            token_resp = http_requests.post(
                f"{settings.NEXTCLOUD_SERVER_URL}/apps/oauth2/api/v1/token",
                data={
                    'grant_type': 'authorization_code',
                    'code': code,
                    'redirect_uri': redirect_uri,
                    'client_id': settings.NEXTCLOUD_OAUTH2_CLIENT_ID,
                    'client_secret': settings.NEXTCLOUD_OAUTH2_CLIENT_SECRET,
                },
                timeout=15,
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()
        except Exception as e:
            return render(request, 'authentication/oauth2_error.html',
                          {'error': f'Error al obtener token de Nextcloud: {e}'})

        nc_access_token = token_data.get('access_token', '')
        login_name = token_data.get('user_id', '')

        if not nc_access_token or not login_name:
            return render(request, 'authentication/oauth2_error.html',
                          {'error': 'Respuesta inválida de Nextcloud.'})

        # Obtener perfil del usuario
        display_name, email, is_executive = _fetch_nextcloud_user(login_name, nc_access_token)

        # Crear/actualizar usuario en Django
        user, employee = _upsert_user_and_employee(login_name, display_name, email, is_executive)

        # Emitir JWT de Django
        refresh = RefreshToken.for_user(user)
        django_access = str(refresh.access_token)
        django_refresh = str(refresh)

        # Si viene de activación de agente: guardar tokens en AgentRegistration
        device_token = request.session.pop('agent_device_token', None)
        if device_token:
            AgentRegistration.objects.update_or_create(
                device_token=device_token,
                defaults={'jwt_access': django_access, 'jwt_refresh': django_refresh},
            )
            return render(request, 'authentication/agent_setup_success.html')

        # Login normal: renderizar página que guarda los tokens en localStorage y redirige
        return_url = settings.NEXTCLOUD_RETURN_URL or request.build_absolute_uri('/dashboard/')
        return render(request, 'authentication/oauth2_success.html', {
            'access': django_access,
            'refresh': django_refresh,
            'redirect_url': return_url,
        })


class AgentSetupView(View):
    """Página de activación del agente.
    Si el usuario ya tiene JWT en el navegador, lo autoriza sin pasar por OAuth2.
    Si no, guarda el device_token en sesión y redirige al flujo OAuth2."""

    def get(self, request):
        device_token = request.GET.get('device', '').strip()
        if not device_token:
            return render(request, 'authentication/oauth2_error.html',
                          {'error': 'Token de dispositivo no proporcionado.'})
        # Renderizar la página — el JS decide si usar JWT existente o ir a OAuth2
        return render(request, 'authentication/agent_setup.html', {'device_token': device_token})


class AgentOAuth2RedirectView(View):
    """Guarda el device_token en sesión y redirige al flujo OAuth2 (fallback sin JWT)."""

    def get(self, request):
        device_token = request.GET.get('device', '').strip()
        if not device_token:
            return render(request, 'authentication/oauth2_error.html',
                          {'error': 'Token de dispositivo no proporcionado.'})
        request.session['agent_device_token'] = device_token
        return redirect('/login/nextcloud/')


class AgentSetupAuthorizeView(APIView):
    """El browser llama a este endpoint con su JWT para autorizar al agente directamente."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        device_token = request.data.get('device_token', '').strip()
        if not device_token:
            return Response({'error': 'device_token es requerido'}, status=400)

        refresh = RefreshToken.for_user(request.user)
        AgentRegistration.objects.update_or_create(
            device_token=device_token,
            defaults={
                'jwt_access': str(refresh.access_token),
                'jwt_refresh': str(refresh),
            },
        )
        return Response({'status': 'ok'})


# ── API Views ─────────────────────────────────────────────────────────────────

class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            employee = request.user.employee
        except Employee.DoesNotExist:
            return Response({'error': 'Perfil de empleado no encontrado'}, status=404)
        data = EmployeeSerializer(employee).data
        data['agent_latest_version'] = settings.AGENT_LATEST_VERSION
        return Response(data)


class AgentTokenPollView(APIView):
    """El agente pollea este endpoint hasta que el empleado complete el login en el navegador."""
    permission_classes = [AllowAny]
    throttle_classes = [AgentPollThrottle]

    def get(self, request):
        device_token = request.query_params.get('device')
        if not device_token:
            return Response({'error': 'device es requerido'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            reg = AgentRegistration.objects.get(device_token=device_token)
        except AgentRegistration.DoesNotExist:
            return Response({'status': 'not_found'}, status=status.HTTP_404_NOT_FOUND)

        if not reg.is_ready():
            return Response({'status': 'pending'}, status=status.HTTP_202_ACCEPTED)

        access = reg.jwt_access
        refresh = reg.jwt_refresh
        reg.delete()
        return Response({'status': 'ok', 'access': access, 'refresh': refresh})


class AgentActivateView(APIView):
    """El agente envía su activation_token y recibe el JWT. Sin interacción del usuario."""
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('activation_token')
        if not token:
            return Response({'error': 'activation_token es requerido'}, status=400)

        try:
            act = AgentActivationToken.objects.select_related('employee__user').get(token=token)
        except AgentActivationToken.DoesNotExist:
            return Response({'error': 'Token inválido'}, status=status.HTTP_404_NOT_FOUND)

        if not act.is_valid():
            return Response({'error': 'Token expirado o ya utilizado'}, status=status.HTTP_410_GONE)

        employee = act.employee
        refresh = RefreshToken.for_user(employee.user)

        act.used = True
        act.save(update_fields=['used'])

        return Response({
            'status': 'ok',
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'employee_name': employee.full_name,
            'employee_email': employee.user.email,
        })


class AgentDownloadView(APIView):
    """Descarga el ejecutable del agente. La activación se completa en el navegador al ejecutarlo."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import os
        from django.conf import settings
        from django.http import FileResponse

        exe_path = os.path.join(settings.BASE_DIR, 'agent', 'dist', 'redline_agent.exe')
        if not os.path.exists(exe_path):
            return Response({'error': 'El agente compilado no está disponible aún'}, status=503)

        response = FileResponse(open(exe_path, 'rb'), content_type='application/octet-stream')
        response['Content-Disposition'] = 'attachment; filename="redline_agent.exe"'
        return response
