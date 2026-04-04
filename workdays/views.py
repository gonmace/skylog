from datetime import timedelta
from django.db import models
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from employees.models import Employee
from authentication.serializers import AGENT_ACTIVE_THRESHOLD_MINUTES
from .models import Workday, DailyReport, CaptureConfig, InactivityPeriod


class WorkdayStartView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            employee = request.user.employee
        except Exception:
            return Response({'error': 'Perfil de empleado no encontrado'}, status=404)

        if Workday.objects.filter(employee=employee, status=Workday.STATUS_IN_PROGRESS).exists():
            return Response(
                {'error': 'Ya tienes una jornada activa'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        workday = Workday.objects.create(
            employee=employee,
            start_time=timezone.now(),
            status=Workday.STATUS_IN_PROGRESS,
        )
        return Response({
            'workday_id': workday.id,
            'start_time': workday.start_time,
            'status': workday.status,
        }, status=status.HTTP_201_CREATED)


class WorkdayEndView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            employee = request.user.employee
        except Exception:
            return Response({'error': 'Perfil de empleado no encontrado'}, status=404)

        workday_id = request.data.get('workday_id')
        activities_done = request.data.get('activities_done', '').strip()
        activities_planned = request.data.get('activities_planned', '').strip()

        if not workday_id:
            return Response({'error': 'workday_id es requerido'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            workday = Workday.objects.get(id=workday_id, employee=employee, status=Workday.STATUS_IN_PROGRESS)
        except Workday.DoesNotExist:
            return Response(
                {'error': 'Jornada activa no encontrada'},
                status=status.HTTP_404_NOT_FOUND,
            )

        end_time = timezone.now()
        duration = int((end_time - workday.start_time).total_seconds() // 60)
        workday.end_time = end_time
        workday.duration_minutes = duration
        workday.status = Workday.STATUS_COMPLETED
        workday.save()

        DailyReport.objects.create(
            workday=workday,
            activities_done=activities_done,
            activities_planned=activities_planned,
        )

        return Response({
            'workday_id': workday.id,
            'duration_minutes': duration,
            'status': workday.status,
        })


class ActiveWorkdayView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            employee = request.user.employee
        except Exception:
            return Response({'active': False})

        now = timezone.now()

        # Intervalo efectivo: override por empleado o global
        effective_interval = (
            employee.capture_interval_minutes
            if employee.capture_interval_minutes is not None
            else CaptureConfig.get().capture_interval_minutes
        )

        # Detectar inactividad: si el gap desde el último heartbeat supera 1.5× el intervalo
        # y hay una jornada activa, registrar el período de inactividad
        prev_seen = employee.agent_last_seen
        gap_threshold = timedelta(minutes=effective_interval * 1.5)
        if prev_seen and (now - prev_seen) > gap_threshold:
            try:
                active_workday = Workday.objects.get(employee=employee, status=Workday.STATUS_IN_PROGRESS)
                gap_minutes = int((now - prev_seen).total_seconds() // 60)
                InactivityPeriod.objects.create(
                    workday=active_workday,
                    started_at=prev_seen,
                    ended_at=now,
                    duration_minutes=gap_minutes,
                )
            except Workday.DoesNotExist:
                pass

        # Stamp agent heartbeat y versión en cada poll
        employee.agent_last_seen = now
        version = request.headers.get('X-Agent-Version', '')
        update_fields = ['agent_last_seen']
        if version and employee.agent_version != version:
            employee.agent_version = version
            update_fields.append('agent_version')
        employee.save(update_fields=update_fields)

        screenshots_enabled = employee.screenshots_enabled

        try:
            workday = Workday.objects.get(employee=employee, status=Workday.STATUS_IN_PROGRESS)
            inactive_minutes = InactivityPeriod.objects.filter(workday=workday).aggregate(
                total=models.Sum('duration_minutes')
            )['total'] or 0
            return Response({
                'active': True,
                'workday_id': workday.id,
                'start_time': workday.start_time,
                'capture_interval_minutes': effective_interval,
                'screenshots_enabled': screenshots_enabled,
                'inactive_minutes': inactive_minutes,
            })
        except Workday.DoesNotExist:
            return Response({
                'active': False,
                'capture_interval_minutes': effective_interval,
                'screenshots_enabled': screenshots_enabled,
            })


class EmployeeOverviewView(APIView):
    """Vista exclusiva para ejecutivos: estado de todos los empleados."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            employee = request.user.employee
        except Exception:
            return Response({'error': 'Perfil no encontrado'}, status=404)

        if not employee.is_executive:
            return Response({'error': 'Acceso no autorizado'}, status=403)

        now = timezone.now()

        employees = Employee.objects.filter(is_active=True, is_executive=False).order_by('full_name')

        global_interval = CaptureConfig.get().capture_interval_minutes

        # Jornadas activas en un solo query
        active_workdays = {
            w.employee_id: w
            for w in Workday.objects.filter(
                employee__in=employees,
                status=Workday.STATUS_IN_PROGRESS,
            )
        }

        # Minutos inactivos por jornada activa
        inactive_by_workday = {
            row['workday_id']: row['total']
            for row in InactivityPeriod.objects.filter(
                workday_id__in=active_workdays.values()
            ).values('workday_id').annotate(total=models.Sum('duration_minutes'))
        }

        result = []
        for emp in employees:
            workday = active_workdays.get(emp.id)

            effective_interval = (
                emp.capture_interval_minutes
                if emp.capture_interval_minutes is not None
                else global_interval
            )

            agent_active = emp.agent_online
            result.append({
                'id': emp.id,
                'full_name': emp.full_name,
                'agent_is_active': agent_active,
                'agent_version': emp.agent_version,
                'agent_last_seen': emp.agent_last_seen,
                'capture_interval_minutes': effective_interval,
                'screenshots_enabled': emp.screenshots_enabled,
                'skylog_access': emp.skylog_access,
                'workday': {
                    'active': True,
                    'workday_id': workday.id,
                    'start_time': workday.start_time,
                    'duration_minutes': int((now - workday.start_time).total_seconds() // 60),
                    'inactive_minutes': inactive_by_workday.get(workday.id, 0),
                } if workday else None,
            })

        agents_online = sum(1 for e in result if e['agent_is_active'])
        return Response({
            'summary': {
                'active_now': len(active_workdays),
                'completed_today': 0,
                'agents_online': agents_online,
                'total_employees': len(result),
            },
            'employees': result,
        })


class CaptureNowView(APIView):
    """Ejecutivo solicita captura inmediata del agente de un empleado via WebSocket."""
    permission_classes = [IsAuthenticated]

    def post(self, request, employee_id):
        try:
            executive = request.user.employee
        except Exception:
            return Response({'error': 'Perfil no encontrado'}, status=404)

        if not executive.is_executive:
            return Response({'error': 'Acceso no autorizado'}, status=403)

        try:
            Employee.objects.get(id=employee_id, is_active=True, is_executive=False)
        except Employee.DoesNotExist:
            return Response({'error': 'Empleado no encontrado'}, status=404)

        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        try:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'agent_{employee_id}',
                {'type': 'capture_command', 'command': 'capture'},
            )
        except Exception as e:
            return Response({'error': f'Error al enviar comando al agente: {e}'}, status=500)
        return Response({'status': 'ok'})


class EmployeeSkylogToggleView(APIView):
    """Ejecutivo habilita/deshabilita el acceso a Skylog de un empleado."""
    permission_classes = [IsAuthenticated]

    def patch(self, request, employee_id):
        try:
            executive = request.user.employee
        except Exception:
            return Response({'error': 'Perfil no encontrado'}, status=404)

        if not executive.is_executive:
            return Response({'error': 'Acceso no autorizado'}, status=403)

        enabled = request.data.get('skylog_access')
        if enabled is None:
            return Response({'error': 'skylog_access es requerido'}, status=400)

        try:
            emp = Employee.objects.get(id=employee_id, is_executive=False)
        except Employee.DoesNotExist:
            return Response({'error': 'Empleado no encontrado'}, status=404)

        emp.skylog_access = bool(enabled)
        emp.save(update_fields=['skylog_access'])
        return Response({'skylog_access': emp.skylog_access})


class EmployeeScreenshotsToggleView(APIView):
    """Ejecutivo habilita/deshabilita capturas de pantalla de un empleado."""
    permission_classes = [IsAuthenticated]

    def patch(self, request, employee_id):
        try:
            executive = request.user.employee
        except Exception:
            return Response({'error': 'Perfil no encontrado'}, status=404)

        if not executive.is_executive:
            return Response({'error': 'Acceso no autorizado'}, status=403)

        enabled = request.data.get('screenshots_enabled')
        if enabled is None:
            return Response({'error': 'screenshots_enabled es requerido'}, status=400)

        try:
            emp = Employee.objects.get(id=employee_id, is_active=True, is_executive=False)
        except Employee.DoesNotExist:
            return Response({'error': 'Empleado no encontrado'}, status=404)

        emp.screenshots_enabled = bool(enabled)
        emp.save(update_fields=['screenshots_enabled'])
        return Response({'screenshots_enabled': emp.screenshots_enabled})


class LastReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            employee = request.user.employee
        except Exception:
            return Response({})

        last = (
            Workday.objects
            .filter(employee=employee, status=Workday.STATUS_COMPLETED)
            .select_related('daily_report')
            .order_by('-end_time')
            .first()
        )

        if not last or not hasattr(last, 'daily_report'):
            return Response({'has_report': False})

        return Response({
            'has_report': True,
            'activities_done': last.daily_report.activities_done,
            'activities_planned': last.daily_report.activities_planned,
            'date': last.end_time.date(),
        })
