import io
import json
import secrets
import zipfile
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
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from employees.models import Employee
from .models import AgentRegistration, AgentActivationToken
from .serializers import EmployeeSerializer


class AgentPollThrottle(AnonRateThrottle):
    rate = '30/min'


# ── JWT Cookie helpers ────────────────────────────────────────────────────────

def _set_jwt_cookies(response, access, refresh):
    """Guarda access y refresh token como cookies SameSite=None para iframe cross-origin."""
    secure = not settings.DEBUG
    common = dict(path='/', samesite='None', httponly=False, secure=secure)
    response.set_cookie('access',  access,  max_age=7200,   **common)
    response.set_cookie('refresh', refresh, max_age=2592000, **common)


def _clear_jwt_cookies(response):
    secure = not settings.DEBUG
    response.set_cookie('access',  '', max_age=0, path='/', samesite='None', secure=secure)
    response.set_cookie('refresh', '', max_age=0, path='/', samesite='None', secure=secure)


# ── Helpers compartidos ───────────────────────────────────────────────────────

def _fetch_nextcloud_user(login_name, bearer_token):
    """Obtiene perfil + grupos del usuario desde la OCS API de Nextcloud.

    Roles según grupos de Nextcloud:
      - skylog + Executives → ejecutivo (is_executive=True, skylog_access=True)
      - skylog solo          → empleado  (is_executive=False, skylog_access=True)
      - ninguno              → sin acceso (is_executive=False, skylog_access=False)
    """
    display_name = login_name
    email = ''
    is_executive = False
    skylog_access = False
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
            groups = ocs_user.get('groups') or []
            skylog_access = 'skylog' in groups
            is_executive = skylog_access and 'Executives' in groups
    except Exception:
        pass
    return display_name, email, is_executive, skylog_access


def _upsert_user_and_employee(login_name, display_name, email, is_executive, skylog_access):
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
    if employee.skylog_access != skylog_access:
        employee.skylog_access = skylog_access
        update_fields.append('skylog_access')
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
        oauth2_url = f"{settings.NEXTCLOUD_SERVER_URL}/apps/oauth2/authorize?{params}"
        # Renderizar página que navega el frame superior a Nextcloud.
        # Un 302 directo navigaría el iframe, donde el cookie de sesión de Nextcloud
        # no se envía (SameSite=Lax en sub-frames cross-origin) → Nextcloud redirige
        # al login en lugar de mostrar la pantalla de autorización.
        return render(request, 'authentication/oauth2_redirect.html', {'url': oauth2_url})


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
        display_name, email, is_executive, skylog_access = _fetch_nextcloud_user(login_name, nc_access_token)

        # Crear/actualizar usuario en Django
        user, employee = _upsert_user_and_employee(login_name, display_name, email, is_executive, skylog_access)

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
            response = render(request, 'authentication/agent_setup_success.html', {
                'access': django_access,
                'refresh': django_refresh,
            })
            _set_jwt_cookies(response, django_access, django_refresh)
            return response

        # Login normal: guardar JWT en sesión para que el iframe pueda reclamarlo,
        # luego renderizar página que también guarda en localStorage y redirige.
        request.session['pending_iframe_jwt'] = {
            'access': django_access,
            'refresh': django_refresh,
        }
        return_url = settings.NEXTCLOUD_RETURN_URL or request.build_absolute_uri('/dashboard/')
        response = render(request, 'authentication/oauth2_success.html', {
            'access': django_access,
            'refresh': django_refresh,
            'redirect_url': return_url,
        })
        _set_jwt_cookies(response, django_access, django_refresh)
        return response


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

class ClaimIframeJWTView(APIView):
    """
    El iframe llama este endpoint tras el login OAuth para obtener el JWT
    almacenado en la sesión del servidor. Uso único: borra el token de la sesión
    al entregarlo. Requiere la cookie de sesión (SameSite=None en producción).
    """
    permission_classes = [AllowAny]

    def get(self, request):
        pending = request.session.pop('pending_iframe_jwt', None)
        if not pending:
            return Response({'access': None, 'refresh': None})
        response = Response(pending)
        _set_jwt_cookies(response, pending['access'], pending['refresh'])
        return response


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


class CookieTokenRefreshView(TokenRefreshView):
    """TokenRefreshView que ademas setea los tokens como cookies SameSite=None."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            _set_jwt_cookies(response, response.data.get('access', ''), response.data.get('refresh', ''))
        return response


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
    """Descarga un ZIP con el ejecutable del agente y un config.json pre-activado."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import os
        from django.http import HttpResponse

        # Preferir el installer de Inno Setup; fallback al exe directo para dev
        installer_path = os.path.join(settings.BASE_DIR, 'agent', 'dist', 'RedLineGS_setup.exe')
        exe_path       = os.path.join(settings.BASE_DIR, 'agent', 'dist', 'redline_agent.exe')
        use_installer  = os.path.exists(installer_path)
        agent_file     = installer_path if use_installer else exe_path
        agent_filename = 'RedLineGS_setup.exe' if use_installer else 'redline_agent.exe'

        if not os.path.exists(agent_file):
            return Response({'error': 'El agente compilado no está disponible aún'}, status=503)

        try:
            employee = request.user.employee
        except Exception:
            return Response({'error': 'Perfil de empleado no encontrado'}, status=404)

        activation_token = AgentActivationToken.create_for_employee(employee)

        server_url = request.build_absolute_uri('/').rstrip('/')
        config_data = {
            'server_url': server_url,
            'jwt_token': '',
            'activation_token': activation_token.token,
            'capture_interval_minutes': 30,
        }
        config_bytes = json.dumps(config_data, indent=2, ensure_ascii=False).encode('utf-8')

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(agent_file, agent_filename)
            zf.writestr('config.json', config_bytes)
        buf.seek(0)

        response = HttpResponse(buf.read(), content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="RedLineGS.zip"'
        return response


class DevLoginView(View):
    """Login automático para desarrollo local. Solo disponible con DEBUG=True."""

    def get(self, request):
        if not settings.DEBUG:
            from django.http import Http404
            raise Http404

        role = request.GET.get('role', 'executive')  # 'executive' | 'employee'
        username = f'dev_{role}'

        is_executive = (role == 'executive')
        user, _ = User.objects.get_or_create(username=username, defaults={
            'first_name': 'Dev',
            'last_name': role.capitalize(),
            'email': f'{username}@localhost',
        })

        from employees.models import Employee
        employee, _ = Employee.objects.get_or_create(
            nextcloud_username=username,
            defaults={
                'user': user,
                'full_name': f'Dev {role.capitalize()}',
                'is_executive': is_executive,
                'skylog_access': True,
                'is_active': True,
            },
        )
        # Sincronizar en caso de que ya existiera con valores distintos
        changed = []
        if employee.is_executive != is_executive:
            employee.is_executive = is_executive; changed.append('is_executive')
        if not employee.skylog_access:
            employee.skylog_access = True; changed.append('skylog_access')
        if changed:
            employee.save(update_fields=changed)

        refresh = RefreshToken.for_user(user)
        access  = str(refresh.access_token)
        ref     = str(refresh)

        return_url = settings.NEXTCLOUD_RETURN_URL or request.build_absolute_uri('/dashboard/')
        response = render(request, 'authentication/oauth2_success.html', {
            'access': access,
            'refresh': ref,
            'redirect_url': return_url,
        })
        _set_jwt_cookies(response, access, ref)
        return response


class MobileLoginView(APIView):
    """Login con usuario/contraseña para usuarios móviles creados en el admin."""
    permission_classes = [AllowAny]

    def post(self, request):
        from django.contrib.auth import authenticate
        username = request.data.get('username', '').strip()
        password = request.data.get('password', '')
        if not username or not password:
            return Response({'error': 'Usuario y contraseña requeridos'}, status=400)

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response({'error': 'Credenciales inválidas'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            employee = user.employee
        except Exception:
            return Response({'error': 'Perfil de empleado no encontrado'}, status=404)

        refresh = RefreshToken.for_user(user)
        access  = str(refresh.access_token)
        ref     = str(refresh)

        response = Response({'status': 'ok', 'access': access, 'refresh': ref,
                             'is_mobile': employee.is_mobile})
        _set_jwt_cookies(response, access, ref)
        return response


class AgentInstallerView(APIView):
    """Descarga un ZIP con el installer para actualizaciones (sin config.json)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import os
        from django.http import HttpResponse
        installer_path = os.path.join(settings.BASE_DIR, 'agent', 'dist', 'RedLineGS_setup.exe')
        if not os.path.exists(installer_path):
            return Response({'error': 'El instalador no está disponible'}, status=503)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(installer_path, 'RedLineGS_setup.exe')
        buf.seek(0)
        response = HttpResponse(buf.read(), content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="RedLineGS_update.zip"'
        return response
