import io
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

    # full_name siempre en MAYÚSCULAS (consistente con la migración 0019 y el
    # entorno local). Sin esto, cada login web revertía full_name al displayname
    # de Nextcloud en title-case. first/last quedan en title-case del displayname.
    full_name_upper = display_name.upper()

    employee, _ = Employee.objects.get_or_create(
        nextcloud_username=login_name,
        defaults={'user': user, 'full_name': full_name_upper},
    )
    update_fields = []
    if employee.full_name != full_name_upper:
        employee.full_name = full_name_upper
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
            # Visitante externo (rol "visita"): solo accede a estadísticas globales.
            from visits.models import Visitor
            try:
                visitor = request.user.visitor
            except Visitor.DoesNotExist:
                return Response({'error': 'Perfil de empleado no encontrado'}, status=404)
            return Response({
                'is_visitor': True,
                'full_name': visitor.full_name,
                'email': visitor.email,
                'is_executive': False,
                'can_view_stats': False,
                'is_superuser': False,
            })
        data = EmployeeSerializer(employee).data
        data['agent_latest_version'] = settings.AGENT_LATEST_VERSION
        data['agent_min_version'] = settings.AGENT_MIN_VERSION
        data['is_superuser'] = request.user.is_superuser
        # Superuser impersonando a este empleado (marcado en la sesión por ImpersonateView)
        imp_id = request.session.get('impersonator_id')
        data['impersonating'] = bool(imp_id and imp_id != request.user.id)
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

        if act.employee.is_executive:
            return Response({'error': 'Los ejecutivos no usan el agente de escritorio'}, status=403)

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


class AgentPairTokenView(APIView):
    """El dashboard (navegador ya autenticado) pide aquí un token de emparejamiento
    de un solo uso y se lo entrega al agente local (POST http://127.0.0.1:7337/pair).
    Así el agente aprende la identidad del empleado al conectarse por Skylog,
    sin depender de un config.json descargado en la instalación."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            employee = request.user.employee
        except Employee.DoesNotExist:
            return Response({'error': 'Perfil de empleado no encontrado'}, status=404)
        if not employee.is_active or not employee.skylog_access:
            return Response({'error': 'Sin acceso a Skylog'}, status=403)
        if employee.is_executive:
            # El WS del agente rechaza ejecutivos; emparejarlo sería un agente zombi.
            return Response({'error': 'Los ejecutivos no usan el agente de escritorio'}, status=403)

        activation_token = AgentActivationToken.create_for_employee(employee)
        return Response({
            'activation_token': activation_token.token,
            'server_url': request.build_absolute_uri('/').rstrip('/'),
        })


class AgentDownloadView(APIView):
    """Descarga un ZIP con el instalador del agente. Sin config.json: el agente
    se instala sin identidad y se empareja automáticamente desde el dashboard."""
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

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(agent_file, agent_filename)
        buf.seek(0)

        response = HttpResponse(buf.read(), content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="RedLineGS.zip"'
        return response


# ── Impersonación (helpers compartidos por DevLoginView e ImpersonateView) ────

def _find_employee(param):
    from employees.models import Employee
    qs = Employee.objects.select_related('user')
    if str(param).isdigit():
        return qs.filter(pk=int(param)).first()
    return qs.filter(nextcloud_username=param).first()


def _issue_jwt_login(request, user, redirect_url=None):
    """Emite JWT para `user`, lo setea como cookies y redirige al dashboard."""
    refresh = RefreshToken.for_user(user)
    access  = str(refresh.access_token)
    ref     = str(refresh)
    return_url = redirect_url or settings.NEXTCLOUD_RETURN_URL or request.build_absolute_uri('/dashboard/')
    response = render(request, 'authentication/oauth2_success.html', {
        'access': access,
        'refresh': ref,
        'redirect_url': return_url,
    })
    _set_jwt_cookies(response, access, ref)
    return response


def _render_employee_picker(request, title, subtitle, dev_links=False):
    from django.db.models import Count
    from django.http import HttpResponse
    from employees.models import Employee
    emps = (Employee.objects
            .filter(is_active=True)
            .select_related('user')
            .annotate(
                n_reports=Count('workdays__daily_report', distinct=True),
                n_acts=Count('workdays__daily_report__activity_items', distinct=True),
            )
            .order_by('-n_acts', '-n_reports', 'full_name'))
    rows = []
    for e in emps:
        rol = 'Ejecutivo' if e.is_executive else 'Empleado'
        acc = '' if e.skylog_access else ' <span style="color:#e11">(sin skylog)</span>'
        nouser = '' if e.user_id else ' <span style="color:#e11">(sin user)</span>'
        disabled = 'pointer-events:none;opacity:.45' if e.user_id is None else ''
        rows.append(
            f'<tr><td><a style="{disabled}" href="?employee={e.pk}">{e.full_name}</a>{acc}{nouser}</td>'
            f'<td>{rol}</td><td style="text-align:right">{e.n_reports}</td>'
            f'<td style="text-align:right">{e.n_acts}</td></tr>')
    extra = ('<br>También: <a href="?role=executive">Dev ejecutivo</a> · '
             '<a href="?role=employee">Dev empleado vacío</a> · '
             '<a href="?role=superuser">Dev superuser</a>') if dev_links else ''
    html = f'''<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>
 body{{font-family:system-ui,sans-serif;background:#0f1115;color:#e5e7eb;max-width:760px;margin:40px auto;padding:0 16px}}
 h1{{font-size:18px}} p{{color:#9ca3af;font-size:13px}}
 table{{width:100%;border-collapse:collapse;margin-top:16px;font-size:14px}}
 th,td{{padding:8px 10px;border-bottom:1px solid #232733;text-align:left}}
 th{{color:#9ca3af;font-size:12px;text-transform:uppercase;letter-spacing:.05em}}
 a{{color:#60a5fa;text-decoration:none}} a:hover{{text-decoration:underline}}
 tr:hover td{{background:#161a22}}
</style></head><body>
<h1>{title}</h1>
<p>{subtitle} Ordenado por cantidad de actividades.{extra}</p>
<table><thead><tr><th>Empleado</th><th>Rol</th><th>Reportes</th><th>Actividades</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</body></html>'''
    return HttpResponse(html)


def _superuser_from_request(request):
    """Devuelve el superuser autenticado (por sesión de Django o JWT en cookie/header), o None."""
    if request.user.is_authenticated and request.user.is_superuser:
        return request.user
    from rest_framework_simplejwt.authentication import JWTAuthentication
    raw = request.COOKIES.get('access', '')
    header = request.META.get('HTTP_AUTHORIZATION', '')
    if not raw and header.startswith('Bearer '):
        raw = header[7:]
    if raw:
        try:
            auth = JWTAuthentication()
            user = auth.get_user(auth.get_validated_token(raw))
            if user.is_superuser:
                return user
        except Exception:
            pass
    return None


class ImpersonateView(View):
    """Un superuser entra al dashboard como cualquier empleado. Disponible en
    producción y desarrollo; responde 404 a cualquiera que no sea superuser.

    - /impersonar/                        → lista de empleados para elegir
    - /impersonar/?employee=<id|username> → emite JWT como ese empleado
    - /impersonar/?volver=1               → restaura la cuenta del superuser original

    Al impersonar, la identidad del superuser queda guardada en la sesión de
    Django (server-side, independiente de las cookies JWT), así el dashboard
    muestra la barra "Estás viendo como…" con el botón Volver.
    """

    def get(self, request):
        from django.http import Http404, HttpResponseNotFound

        # Volver a la cuenta original: se valida contra la sesión (el JWT actual
        # es el del empleado impersonado, no el del superuser).
        if request.GET.get('volver'):
            orig_id = request.session.pop('impersonator_id', None)
            orig = User.objects.filter(pk=orig_id, is_superuser=True, is_active=True).first() if orig_id else None
            if orig is None:
                raise Http404
            return _issue_jwt_login(request, orig, redirect_url=request.build_absolute_uri('/dashboard/'))

        superuser = _superuser_from_request(request)
        if superuser is None:
            raise Http404

        emp_param = request.GET.get('employee')
        if emp_param:
            employee = _find_employee(emp_param)
            if employee is None or employee.user_id is None:
                return HttpResponseNotFound(f'Empleado "{emp_param}" no encontrado o sin usuario asociado.')
            if employee.user_id != superuser.id:
                request.session['impersonator_id'] = superuser.id
            return _issue_jwt_login(request, employee.user)

        return _render_employee_picker(
            request,
            title='Impersonar empleado',
            subtitle='Solo superusers. Clic en un nombre para entrar al dashboard como ese empleado '
                     '(reemplaza tu sesión actual).',
        )


class DevLoginView(View):
    """Login automático para desarrollo local. Solo disponible con DEBUG=True.

    - /dev-login/                        → usuario dev ejecutivo sintético (default)
    - /dev-login/?role=employee          → usuario dev empleado sintético (sin datos)
    - /dev-login/?role=superuser         → usuario dev ejecutivo + superuser (ve
                                           Cuentas, Impersonar, Permisos, etc.)
    - /dev-login/?pick=1                 → lista de empleados reales (con su cantidad
                                           de datos) para elegir a quién impersonar
    - /dev-login/?employee=<id|username> → impersona a ese empleado real (con sus datos)
    """

    def get(self, request):
        if not settings.DEBUG:
            from django.http import Http404
            raise Http404

        # Selector de empleados reales.
        if request.GET.get('pick'):
            return _render_employee_picker(
                request,
                title='Dev login — impersonar empleado',
                subtitle='Solo desarrollo (DEBUG). Clic en un nombre para loguearte como ese empleado y ver su pantalla.',
                dev_links=True,
            )

        # Impersonar un empleado real existente (id o nextcloud_username).
        emp_param = request.GET.get('employee')
        if emp_param:
            from django.http import HttpResponseNotFound
            employee = _find_employee(emp_param)
            if employee is None or employee.user_id is None:
                return HttpResponseNotFound(f'Empleado "{emp_param}" no encontrado o sin usuario asociado.')
            return _issue_jwt_login(request, employee.user)

        # Usuario dev sintético por rol (comportamiento original).
        role = request.GET.get('role', 'executive')  # 'executive' | 'employee' | 'superuser'
        username = f'dev_{role}'
        is_superuser = (role == 'superuser')
        is_executive = (role == 'executive') or is_superuser
        user, _ = User.objects.get_or_create(username=username, defaults={
            'first_name': 'Dev',
            'last_name': role.capitalize(),
            'email': f'{username}@localhost',
        })
        if is_superuser and not (user.is_superuser and user.is_staff):
            user.is_superuser = True
            user.is_staff = True
            user.save(update_fields=['is_superuser', 'is_staff'])

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
        changed = []
        if employee.is_executive != is_executive:
            employee.is_executive = is_executive; changed.append('is_executive')
        if not employee.skylog_access:
            employee.skylog_access = True; changed.append('skylog_access')
        if changed:
            employee.save(update_fields=changed)

        return _issue_jwt_login(request, user)


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

        device_id = request.data.get('device_id', '').strip()
        if employee.solo_movil and device_id:
            if not employee.mobile_device_id:
                employee.mobile_device_id = device_id
                employee.save(update_fields=['mobile_device_id'])
            elif employee.mobile_device_id != device_id:
                return Response(
                    {'error': 'Este usuario ya está vinculado a otro dispositivo. Contacta al administrador.'},
                    status=status.HTTP_403_FORBIDDEN,
                )

        refresh = RefreshToken.for_user(user)
        access  = str(refresh.access_token)
        ref     = str(refresh)

        response = Response({'status': 'ok', 'access': access, 'refresh': ref,
                             'solo_movil': employee.solo_movil, 'mobile_type': employee.mobile_type})
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
