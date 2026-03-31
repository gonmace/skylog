import os
import requests as http_requests
from django.conf import settings
from django.http import StreamingHttpResponse, Http404
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from PIL import Image
from io import BytesIO
from workdays.models import Workday
from .models import Screenshot


def _nextcloud_configured():
    return bool(getattr(settings, 'NEXTCLOUD_SCREENSHOTS_USER', ''))


_nc_dirs_created = set()  # directorios ya confirmados en Nextcloud esta sesión


def _nextcloud_upload(image_bytes, remote_path):
    """Sube bytes a Nextcloud vía WebDAV. Lanza excepción si falla."""
    nc_url = settings.NEXTCLOUD_SERVER_URL.rstrip('/')
    nc_user = settings.NEXTCLOUD_SCREENSHOTS_USER
    nc_pass = settings.NEXTCLOUD_SCREENSHOTS_PASSWORD
    nc_folder = settings.NEXTCLOUD_SCREENSHOTS_FOLDER.strip('/')

    # Crear cada segmento de directorio, saltando los ya conocidos
    file_dir = '/'.join(remote_path.split('/')[:-1])  # user/2026-03-29
    full_dir = f"{nc_folder}/{file_dir}"               # 100_Skylog/screenshots/user/2026-03-29
    segments = full_dir.split('/')
    for i in range(1, len(segments) + 1):
        path = '/'.join(segments[:i])
        if path not in _nc_dirs_created:
            dav_dir = f"{nc_url}/remote.php/dav/files/{nc_user}/{path}"
            http_requests.request('MKCOL', dav_dir, auth=(nc_user, nc_pass), timeout=15)
            _nc_dirs_created.add(path)

    dav_url = f"{nc_url}/remote.php/dav/files/{nc_user}/{nc_folder}/{remote_path}"
    resp = http_requests.put(
        dav_url,
        data=image_bytes,
        auth=(nc_user, nc_pass),
        headers={'Content-Type': 'image/jpeg'},
        timeout=60,
    )
    if resp.status_code not in (200, 201, 204):
        raise RuntimeError(f"WebDAV PUT falló: {resp.status_code} {resp.text[:200]}")


class ScreenshotUploadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            employee = request.user.employee
        except Exception:
            return Response({'error': 'Perfil de empleado no encontrado'}, status=404)

        if not employee.screenshots_enabled:
            return Response(
                {'error': 'Las capturas están deshabilitadas para este empleado'},
                status=status.HTTP_403_FORBIDDEN,
            )

        workday_id = request.data.get('workday_id')
        image_file = request.FILES.get('image')

        if not workday_id or not image_file:
            return Response(
                {'error': 'workday_id e image son requeridos'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            workday = Workday.objects.get(
                id=workday_id,
                employee=employee,
                status=Workday.STATUS_IN_PROGRESS,
            )
        except Workday.DoesNotExist:
            return Response(
                {'error': 'Jornada activa no encontrada o no pertenece a este usuario'},
                status=status.HTTP_404_NOT_FOUND,
            )

        MESES = ['enero','febrero','marzo','abril','mayo','junio',
                 'julio','agosto','septiembre','octubre','noviembre','diciembre']
        now = timezone.localtime(timezone.now())
        display_name = employee.full_name
        year_month   = f"{now.strftime('%y')}-{MESES[now.month - 1]}"  # ej. 26-marzo
        day_time     = now.strftime('%d-%Hh%M')                         # ej. 29-21h06
        rel_path = f"{display_name}/{year_month}/{day_time}.jpg"

        # Procesar imagen
        try:
            img = Image.open(image_file)
            img = img.convert('RGB')
            buf = BytesIO()
            img.save(buf, format='JPEG', quality=85, optimize=True)
            image_bytes = buf.getvalue()
        except Exception as e:
            return Response(
                {'error': f'Error procesando imagen: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if _nextcloud_configured():
            try:
                _nextcloud_upload(image_bytes, rel_path)
            except Exception as e:
                return Response(
                    {'error': f'Error subiendo a Nextcloud: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            storage_backend = Screenshot.STORAGE_NEXTCLOUD
            stored_path = rel_path
        else:
            storage_base = getattr(settings, 'SCREENSHOT_STORAGE_PATH', 'screenshots')
            stored_path = f"{storage_base}/{rel_path}"
            full_path = os.path.join(settings.MEDIA_ROOT, stored_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'wb') as f:
                f.write(image_bytes)
            storage_backend = Screenshot.STORAGE_LOCAL

        screenshot = Screenshot.objects.create(
            employee=employee,
            workday=workday,
            file_path=stored_path,
            storage=storage_backend,
        )

        return Response({
            'screenshot_id': screenshot.id,
            'captured_at': screenshot.captured_at,
            'file_path': stored_path,
        }, status=status.HTTP_201_CREATED)


class ScreenshotImageView(APIView):
    """Proxy para servir capturas almacenadas en Nextcloud. Solo staff."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not request.user.is_staff:
            return Response({'error': 'No autorizado'}, status=status.HTTP_403_FORBIDDEN)

        try:
            screenshot = Screenshot.objects.select_related('employee').get(pk=pk)
        except Screenshot.DoesNotExist:
            raise Http404

        if screenshot.storage != Screenshot.STORAGE_NEXTCLOUD:
            raise Http404

        nc_url = settings.NEXTCLOUD_SERVER_URL.rstrip('/')
        nc_user = settings.NEXTCLOUD_SCREENSHOTS_USER
        nc_pass = settings.NEXTCLOUD_SCREENSHOTS_PASSWORD
        nc_folder = settings.NEXTCLOUD_SCREENSHOTS_FOLDER.strip('/')
        dav_url = f"{nc_url}/remote.php/dav/files/{nc_user}/{nc_folder}/{screenshot.file_path}"

        try:
            nc_resp = http_requests.get(dav_url, auth=(nc_user, nc_pass), stream=True, timeout=30)
            nc_resp.raise_for_status()
        except Exception:
            raise Http404

        response = StreamingHttpResponse(
            nc_resp.iter_content(chunk_size=8192),
            content_type='image/jpeg',
        )
        response['Cache-Control'] = 'private, max-age=3600'
        return response
