import calendar as _cal
import io
import os
from datetime import timedelta, datetime as _datetime, time as _time, date as _date
from django.conf import settings
from django.db import models
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from employees.models import Employee
from authentication.serializers import AGENT_ACTIVE_THRESHOLD_MINUTES
from .models import Workday, DailyReport, CaptureConfig, InactivityPeriod, ExecutiveMessage, CalendarNote, EmployeeLeave


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

        lat = request.data.get('latitude')
        lng = request.data.get('longitude')

        workday = Workday.objects.create(
            employee=employee,
            start_time=timezone.now(),
            status=Workday.STATUS_IN_PROGRESS,
            start_latitude=lat or None,
            start_longitude=lng or None,
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
        lat = request.data.get('latitude')
        lng = request.data.get('longitude')

        if not workday_id:
            return Response({'error': 'workday_id es requerido'}, status=status.HTTP_400_BAD_REQUEST)

        if employee.solo_movil and (not lat or not lng):
            return Response(
                {'error': 'La ubicación es requerida para finalizar la jornada', 'location_required': True},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
        workday.end_latitude  = lat or None
        workday.end_longitude = lng or None
        workday.save()

        # Captura de pantalla al finalizar jornada
        try:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
            async_to_sync(get_channel_layer().group_send)(
                f'agent_{employee.id}',
                {'type': 'capture_command', 'command': 'capture'},
            )
        except Exception:
            pass

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


def _local_now():
    return timezone.localtime(timezone.now())


def _month_range(year, month):
    """Devuelve (first_aware, last_aware) en zona local para filtrar por mes."""
    first = timezone.make_aware(_datetime(_date(year, month, 1).year, month, 1, 0, 0, 0))
    last_day = _cal.monthrange(year, month)[1]
    last = timezone.make_aware(_datetime(year, month, last_day, 23, 59, 59))
    return first, last


def _close_stale_workdays():
    """Cierra jornadas que quedaron abiertas de días anteriores (a las 17:00 hora local)."""
    today = _local_now().date()
    stale = Workday.objects.filter(
        status=Workday.STATUS_IN_PROGRESS,
        start_time__lt=timezone.make_aware(_datetime.combine(today, _time(0, 0))),
    )
    for w in stale:
        local_start = timezone.localtime(w.start_time)
        close_at = timezone.make_aware(
            _datetime.combine(local_start.date(), _time(17, 0))
        )
        if w.start_time >= close_at:
            close_at = w.start_time + timedelta(minutes=1)
        duration = max(1, int((close_at - w.start_time).total_seconds() // 60))
        w.end_time = close_at
        w.duration_minutes = duration
        w.status = Workday.STATUS_COMPLETED
        w.auto_closed = True
        w.save(update_fields=['end_time', 'duration_minutes', 'status', 'auto_closed'])


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

        _close_stale_workdays()

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
                'solo_movil': emp.solo_movil,
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
                    'auto_closed': workday.auto_closed,
                    'start_latitude':  float(workday.start_latitude)  if workday.start_latitude  else None,
                    'start_longitude': float(workday.start_longitude) if workday.start_longitude else None,
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


class SendMessageView(APIView):
    """Ejecutivo envía un mensaje a un empleado específico."""
    permission_classes = [IsAuthenticated]

    def post(self, request, employee_id):
        try:
            executive = request.user.employee
        except Exception:
            return Response({'error': 'Perfil no encontrado'}, status=404)

        if not executive.is_executive:
            return Response({'error': 'Acceso no autorizado'}, status=403)

        body = request.data.get('body', '').strip()
        if not body:
            return Response({'error': 'El mensaje no puede estar vacío'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            recipient = Employee.objects.get(id=employee_id, is_active=True, is_executive=False)
        except Employee.DoesNotExist:
            return Response({'error': 'Empleado no encontrado'}, status=404)

        message = ExecutiveMessage.objects.create(
            sender=executive,
            recipient=recipient,
            body=body,
        )

        # Notificar en tiempo real al dashboard del empleado (si está conectado)
        try:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'dashboard_{recipient.id}',
                {'type': 'new_message'},
            )
        except Exception:
            pass

        return Response({'id': message.id, 'sent_at': message.sent_at}, status=status.HTTP_201_CREATED)


class PendingMessagesView(APIView):
    """Empleado obtiene sus mensajes pendientes de confirmar."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            employee = request.user.employee
        except Exception:
            return Response({'error': 'Perfil no encontrado'}, status=404)

        messages = (
            ExecutiveMessage.objects
            .filter(recipient=employee, acknowledged_at__isnull=True)
            .select_related('sender')
        )
        data = [
            {
                'id': m.id,
                'body': m.body,
                'sent_at': m.sent_at,
                'sender_name': m.sender.full_name,
            }
            for m in messages
        ]
        return Response(data)


class WorkdayMonthlyView(APIView):
    """Devuelve horas trabajadas por día para el mes solicitado."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            employee = request.user.employee
        except Exception:
            return Response({})

        local_now = _local_now()
        try:
            year  = int(request.query_params.get('year',  local_now.year))
            month = int(request.query_params.get('month', local_now.month))
        except (TypeError, ValueError):
            return Response({'error': 'year y month deben ser enteros'}, status=400)

        first_dt, last_dt = _month_range(year, month)
        completed = Workday.objects.filter(
            employee=employee,
            status=Workday.STATUS_COMPLETED,
            start_time__gte=first_dt,
            start_time__lte=last_dt,
        ).values('start_time', 'duration_minutes', 'auto_closed')

        days: dict = {}
        auto_closed_days: set = set()
        for w in completed:
            day = timezone.localtime(w['start_time']).day
            if w['auto_closed']:
                auto_closed_days.add(day)
            else:
                days[day] = days.get(day, 0) + (w['duration_minutes'] or 0) / 60

        # Incluir jornada activa si cae en el mes solicitado
        active_day = None
        try:
            active = Workday.objects.get(employee=employee, status=Workday.STATUS_IN_PROGRESS)
            local_start = timezone.localtime(active.start_time)
            if local_start.year == year and local_start.month == month:
                active_day = local_start.day
                elapsed = int((local_now - active.start_time).total_seconds() // 60) / 60
                days[active_day] = days.get(active_day, 0) + elapsed
        except Workday.DoesNotExist:
            pass

        # Notas globales del mes
        notes_qs = CalendarNote.objects.filter(date__year=year, date__month=month)
        notes = {str(n.date.day): {'text': n.text, 'type': n.note_type} for n in notes_qs}

        # Ausencias del empleado en el mes
        first_date = _date(year, month, 1)
        last_date  = _date(year, month, _cal.monthrange(year, month)[1])
        leaves_qs = EmployeeLeave.objects.filter(
            employee=employee,
            start_date__lte=last_date,
            end_date__gte=first_date,
        )
        leave_days = {}
        for lv in leaves_qs:
            cur = max(lv.start_date, first_date)
            end = min(lv.end_date, last_date)
            while cur <= end:
                leave_days[str(cur.day)] = {'type': lv.leave_type, 'note': lv.note, 'id': lv.id}
                cur += timedelta(days=1)

        return Response({
            'year': year,
            'month': month,
            'active_day': active_day,
            'auto_closed_days': list(auto_closed_days),
            'days': {str(k): round(v, 2) for k, v in days.items()},
            'notes': notes,
            'leaves': leave_days,
        })


class EmployeeMonthlyView(APIView):
    """Ejecutivo ve el calendario de horas trabajadas de un empleado específico."""
    permission_classes = [IsAuthenticated]

    def get(self, request, employee_id):
        try:
            executive = request.user.employee
        except Exception:
            return Response({})

        if not executive.is_executive:
            return Response({'error': 'Acceso no autorizado'}, status=403)

        try:
            employee = Employee.objects.get(id=employee_id, is_active=True, is_executive=False)
        except Employee.DoesNotExist:
            return Response({'error': 'Empleado no encontrado'}, status=404)

        local_now = _local_now()
        try:
            year  = int(request.query_params.get('year',  local_now.year))
            month = int(request.query_params.get('month', local_now.month))
        except (TypeError, ValueError):
            return Response({'error': 'year y month deben ser enteros'}, status=400)

        first_dt, last_dt = _month_range(year, month)
        completed = Workday.objects.filter(
            employee=employee,
            status=Workday.STATUS_COMPLETED,
            start_time__gte=first_dt,
            start_time__lte=last_dt,
        ).values('start_time', 'duration_minutes', 'auto_closed')

        days: dict = {}
        auto_closed_days: set = set()
        for w in completed:
            day = timezone.localtime(w['start_time']).day
            days[day] = days.get(day, 0) + (w['duration_minutes'] or 0) / 60
            if w['auto_closed']:
                auto_closed_days.add(day)

        active_day = None
        try:
            active = Workday.objects.get(employee=employee, status=Workday.STATUS_IN_PROGRESS)
            local_start = timezone.localtime(active.start_time)
            if local_start.year == year and local_start.month == month:
                active_day = local_start.day
                elapsed = int((local_now - active.start_time).total_seconds() // 60) / 60
                days[active_day] = days.get(active_day, 0) + elapsed
        except Workday.DoesNotExist:
            pass

        notes_qs = CalendarNote.objects.filter(date__year=year, date__month=month)
        notes = {str(n.date.day): {'text': n.text, 'type': n.note_type, 'id': n.id} for n in notes_qs}

        first_date = _date(year, month, 1)
        last_date  = _date(year, month, _cal.monthrange(year, month)[1])
        leaves_qs = EmployeeLeave.objects.filter(
            employee=employee,
            start_date__lte=last_date,
            end_date__gte=first_date,
        )
        leave_days = {}
        for lv in leaves_qs:
            cur = max(lv.start_date, first_date)
            end = min(lv.end_date, last_date)
            while cur <= end:
                leave_days[str(cur.day)] = {'type': lv.leave_type, 'note': lv.note, 'id': lv.id}
                cur += timedelta(days=1)

        return Response({
            'year': year,
            'month': month,
            'active_day': active_day,
            'auto_closed_days': list(auto_closed_days),
            'days': {str(k): round(v, 2) for k, v in days.items()},
            'notes': notes,
            'leaves': leave_days,
        })


class AcknowledgeMessageView(APIView):
    """Empleado confirma haber leído un mensaje."""
    permission_classes = [IsAuthenticated]

    def post(self, request, message_id):
        try:
            employee = request.user.employee
        except Exception:
            return Response({'error': 'Perfil no encontrado'}, status=404)

        try:
            message = ExecutiveMessage.objects.get(id=message_id, recipient=employee)
        except ExecutiveMessage.DoesNotExist:
            return Response({'error': 'Mensaje no encontrado'}, status=404)

        if message.acknowledged_at is None:
            message.acknowledged_at = timezone.now()
            message.save(update_fields=['acknowledged_at'])

        return Response({'ok': True})


class CalendarNotesView(APIView):
    """CRUD de notas globales de calendario (ejecutivos)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Lista notas de un mes: ?year=YYYY&month=MM"""
        now = timezone.now()
        try:
            year  = int(request.query_params.get('year',  now.year))
            month = int(request.query_params.get('month', now.month))
        except (TypeError, ValueError):
            return Response({'error': 'Parámetros inválidos'}, status=400)

        notes = CalendarNote.objects.filter(date__year=year, date__month=month)
        return Response([
            {'id': n.id, 'date': n.date, 'text': n.text, 'note_type': n.note_type}
            for n in notes
        ])

    def post(self, request):
        """Crea una nota. Solo ejecutivos."""
        try:
            executive = request.user.employee
        except Exception:
            return Response({'error': 'Perfil no encontrado'}, status=404)
        if not executive.is_executive:
            return Response({'error': 'Acceso no autorizado'}, status=403)

        date_str  = request.data.get('date', '')
        text      = request.data.get('text', '').strip()
        note_type = request.data.get('note_type', CalendarNote.TYPE_FERIADO)

        if not date_str or not text:
            return Response({'error': 'date y text son requeridos'}, status=400)
        try:
            from datetime import date as date_type
            import datetime
            date_obj = datetime.date.fromisoformat(date_str)
        except ValueError:
            return Response({'error': 'Formato de fecha inválido (YYYY-MM-DD)'}, status=400)

        note, created = CalendarNote.objects.update_or_create(
            date=date_obj,
            defaults={'text': text, 'note_type': note_type, 'created_by': executive},
        )
        return Response(
            {'id': note.id, 'date': note.date, 'text': note.text, 'note_type': note.note_type},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class CalendarNoteDetailView(APIView):
    """Elimina una nota de calendario. Solo ejecutivos."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, note_id):
        try:
            executive = request.user.employee
        except Exception:
            return Response({'error': 'Perfil no encontrado'}, status=404)
        if not executive.is_executive:
            return Response({'error': 'Acceso no autorizado'}, status=403)
        try:
            note = CalendarNote.objects.get(id=note_id)
        except CalendarNote.DoesNotExist:
            return Response({'error': 'Nota no encontrada'}, status=404)
        note.delete()
        return Response({'ok': True})


class EmployeeLeavesView(APIView):
    """Lista y crea ausencias de un empleado. Solo ejecutivos."""
    permission_classes = [IsAuthenticated]

    def get(self, request, employee_id):
        try:
            executive = request.user.employee
        except Exception:
            return Response({'error': 'Perfil no encontrado'}, status=404)
        if not executive.is_executive:
            return Response({'error': 'Acceso no autorizado'}, status=403)

        now = timezone.now()
        try:
            year  = int(request.query_params.get('year',  now.year))
            month = int(request.query_params.get('month', now.month))
        except (TypeError, ValueError):
            return Response({'error': 'Parámetros inválidos'}, status=400)

        leaves = EmployeeLeave.objects.filter(
            employee_id=employee_id,
            start_date__year=year,
            start_date__month=month,
        )
        return Response([
            {
                'id': l.id,
                'start_date': l.start_date,
                'end_date': l.end_date,
                'leave_type': l.leave_type,
                'note': l.note,
            }
            for l in leaves
        ])

    def post(self, request, employee_id):
        try:
            executive = request.user.employee
        except Exception:
            return Response({'error': 'Perfil no encontrado'}, status=404)
        if not executive.is_executive:
            return Response({'error': 'Acceso no autorizado'}, status=403)

        try:
            emp = Employee.objects.get(id=employee_id, is_active=True, is_executive=False)
        except Employee.DoesNotExist:
            return Response({'error': 'Empleado no encontrado'}, status=404)

        start_str  = request.data.get('start_date', '')
        end_str    = request.data.get('end_date', '') or start_str
        leave_type = request.data.get('leave_type', '')
        note       = request.data.get('note', '').strip()

        if not start_str or not leave_type:
            return Response({'error': 'start_date y leave_type son requeridos'}, status=400)

        try:
            import datetime
            start = datetime.date.fromisoformat(start_str)
            end   = datetime.date.fromisoformat(end_str)
            if end < start:
                end = start
        except ValueError:
            return Response({'error': 'Formato de fecha inválido (YYYY-MM-DD)'}, status=400)

        leave = EmployeeLeave.objects.create(
            employee=emp,
            start_date=start,
            end_date=end,
            leave_type=leave_type,
            note=note,
            created_by=executive,
        )
        return Response(
            {'id': leave.id, 'start_date': leave.start_date, 'end_date': leave.end_date,
             'leave_type': leave.leave_type, 'note': leave.note},
            status=status.HTTP_201_CREATED,
        )


class EmployeeLeaveDetailView(APIView):
    """Elimina una ausencia. Solo ejecutivos."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, employee_id, leave_id):
        try:
            executive = request.user.employee
        except Exception:
            return Response({'error': 'Perfil no encontrado'}, status=404)
        if not executive.is_executive:
            return Response({'error': 'Acceso no autorizado'}, status=403)
        try:
            leave = EmployeeLeave.objects.get(id=leave_id, employee_id=employee_id)
        except EmployeeLeave.DoesNotExist:
            return Response({'error': 'Ausencia no encontrada'}, status=404)
        leave.delete()
        return Response({'ok': True})


_MONTH_NAMES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
_DAY_NAMES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']


def reporte_view(request):
    """Sirve el shell HTML del reporte. Los datos se cargan desde /api/reporte/ via JS."""
    local_now = _local_now()
    years_range = list(range(local_now.year - 2, local_now.year + 1))
    return render(request, 'workdays/reporte.html', {
        'current_year': local_now.year,
        'current_month': local_now.month,
        'months': list(enumerate(_MONTH_NAMES, 1)),
        'years': years_range,
    })


class ReporteAPIView(APIView):
    """Datos del reporte de asistencia. Solo ejecutivos."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            executive = request.user.employee
        except Exception:
            return Response({'error': 'Perfil no encontrado'}, status=404)
        if not executive.is_executive:
            return Response({'error': 'Acceso no autorizado'}, status=403)

        local_now = _local_now()
        filter_mode = request.query_params.get('mode', 'month')

        if filter_mode == 'range':
            from_str = request.query_params.get('from', '')
            to_str   = request.query_params.get('to', '')
            try:
                from_date = _date.fromisoformat(from_str)
                to_date   = _date.fromisoformat(to_str)
                if to_date < from_date:
                    to_date = from_date
            except (ValueError, TypeError):
                filter_mode = 'month'

        if filter_mode == 'month':
            try:
                sel_year  = int(request.query_params.get('year',  local_now.year))
                sel_month = int(request.query_params.get('month', local_now.month))
                if not (1 <= sel_month <= 12):
                    raise ValueError
            except (ValueError, TypeError):
                sel_year, sel_month = local_now.year, local_now.month
            from_date = _date(sel_year, sel_month, 1)
            to_date   = _date(sel_year, sel_month, _cal.monthrange(sel_year, sel_month)[1])
            label = f'{_MONTH_NAMES[sel_month - 1]} {sel_year}'
        else:
            label = f'{from_date.strftime("%d/%m/%Y")} — {to_date.strftime("%d/%m/%Y")}'

        first_dt = timezone.make_aware(_datetime.combine(from_date, _time(0, 0, 0)))
        last_dt  = timezone.make_aware(_datetime.combine(to_date,   _time(23, 59, 59)))

        from employees.models import Employee as _Employee
        employees = list(_Employee.objects.filter(is_active=True, is_executive=False).order_by('full_name'))

        # Workday lookup: (emp_id, date) -> workday
        wd_lookup = {}
        for wd in Workday.objects.filter(
            employee__is_active=True, employee__is_executive=False,
            status=Workday.STATUS_COMPLETED,
            start_time__gte=first_dt, start_time__lte=last_dt,
        ).select_related('employee'):
            local_start = timezone.localtime(wd.start_time)
            wd_lookup[(wd.employee_id, local_start.date())] = wd

        # Leaves lookup: (emp_id, date) -> [texts]
        leave_type_labels = dict(EmployeeLeave.TYPE_CHOICES)
        leaves_lookup = {}
        for lv in EmployeeLeave.objects.filter(
            employee__is_active=True, employee__is_executive=False,
            start_date__lte=to_date, end_date__gte=from_date,
        ):
            d = lv.start_date
            while d <= lv.end_date:
                if from_date <= d <= to_date:
                    txt = leave_type_labels.get(lv.leave_type, lv.leave_type)
                    if lv.note:
                        txt += f' ({lv.note})'
                    leaves_lookup.setdefault((lv.employee_id, d), []).append(txt)
                d += timedelta(days=1)

        note_type_labels = dict(CalendarNote.TYPE_CHOICES)
        notes_lookup = {}
        for note in CalendarNote.objects.filter(date__gte=from_date, date__lte=to_date):
            lbl = note_type_labels.get(note.note_type, note.note_type)
            notes_lookup.setdefault(note.date, []).append(f'{lbl}: {note.text}')

        all_dates = []
        d = from_date
        while d <= to_date:
            all_dates.append(d)
            d += timedelta(days=1)

        rows = []
        for emp_counter, emp in enumerate(employees, start=1):
            for day_num, day in enumerate(all_dates, start=1):
                wd = wd_lookup.get((emp.id, day))
                if wd:
                    local_start = timezone.localtime(wd.start_time)
                    local_end   = timezone.localtime(wd.end_time) if wd.end_time else None
                    ref_mins    = emp.hora_entrada.hour * 60 + emp.hora_entrada.minute
                    start_mins  = local_start.hour * 60 + local_start.minute
                    atraso      = max(0, start_mins - ref_mins)
                    neto        = max(0, (wd.duration_minutes or 0) - 60)
                    hora_ingreso    = local_start.strftime('%H:%M')
                    hora_salida     = local_end.strftime('%H:%M') if local_end else '—'
                    horas_trabajadas = f'{neto // 60:02d}:{neto % 60:02d}'
                    atraso_minutos  = atraso
                else:
                    hora_ingreso = hora_salida = horas_trabajadas = ''
                    atraso_minutos = None

                rows.append({
                    'emp_num':   emp_counter,
                    'day_num':   day_num,
                    'nombre':    emp.full_name,
                    'cargo':     emp.cargo,
                    'haber_basico': str(emp.haber_basico) if emp.haber_basico else None,
                    'fecha':     day.strftime('%d-%m-%Y'),
                    'dia':       _DAY_NAMES[day.weekday()],
                    'hora_ingreso':    hora_ingreso,
                    'hora_salida':     hora_salida,
                    'horas_trabajadas': horas_trabajadas,
                    'atraso_minutos':  atraso_minutos,
                    'comentario_leaves': leaves_lookup.get((emp.id, day), []),
                    'comentario_notes':  notes_lookup.get(day, []),
                    'is_weekend':      day.weekday() >= 5,
                    'is_first_of_employee': day_num == 1,
                })

        return Response({'rows': rows, 'total': len(rows), 'label': label})


def _xls_sheet_name(nombre):
    parts = nombre.strip().split()
    inicial = (parts[0][0].upper() + '.') if parts else ''
    apellido = parts[1] if len(parts) > 1 else ''
    name = f'{inicial} {apellido}'.strip()[:31]
    for ch in r'\/*?:[]':
        name = name.replace(ch, '')
    return name or 'Empleado'


class ReporteExportView(APIView):
    """Descarga el reporte de asistencia como .xlsx usando la plantilla corporativa."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            executive = request.user.employee
        except Exception:
            return Response({'error': 'Perfil no encontrado'}, status=404)
        if not executive.is_executive:
            return Response({'error': 'Acceso no autorizado'}, status=403)

        local_now = _local_now()
        filter_mode = request.query_params.get('mode', 'month')

        if filter_mode == 'range':
            try:
                from_date = _date.fromisoformat(request.query_params.get('from', ''))
                to_date   = _date.fromisoformat(request.query_params.get('to', ''))
                if to_date < from_date:
                    to_date = from_date
            except (ValueError, TypeError):
                filter_mode = 'month'

        if filter_mode == 'month':
            try:
                sel_year  = int(request.query_params.get('year',  local_now.year))
                sel_month = int(request.query_params.get('month', local_now.month))
                if not (1 <= sel_month <= 12):
                    raise ValueError
            except (ValueError, TypeError):
                sel_year, sel_month = local_now.year, local_now.month
            from_date = _date(sel_year, sel_month, 1)
            to_date   = _date(sel_year, sel_month, _cal.monthrange(sel_year, sel_month)[1])
            label = f'{_MONTH_NAMES[sel_month - 1]}-{sel_year}'
        else:
            label = f'{from_date.strftime("%d-%m-%Y")}__{to_date.strftime("%d-%m-%Y")}'

        first_dt = timezone.make_aware(_datetime.combine(from_date, _time(0, 0, 0)))
        last_dt  = timezone.make_aware(_datetime.combine(to_date,   _time(23, 59, 59)))

        from employees.models import Employee as _EmpXls
        xls_employees = list(_EmpXls.objects.filter(is_active=True, is_executive=False).order_by('full_name'))

        # Workday lookup
        xls_wd_lookup = {}
        for wd in Workday.objects.filter(
            employee__is_active=True, employee__is_executive=False,
            status=Workday.STATUS_COMPLETED,
            start_time__gte=first_dt, start_time__lte=last_dt,
        ).select_related('employee'):
            ls = timezone.localtime(wd.start_time)
            xls_wd_lookup[(wd.employee_id, ls.date())] = wd

        # Per-date lookups for comments
        xls_leave_labels = dict(EmployeeLeave.TYPE_CHOICES)
        xls_leaves_lookup = {}
        emp_ids_xls = {e.id for e in xls_employees}
        for lv in EmployeeLeave.objects.filter(
            employee_id__in=emp_ids_xls,
            start_date__lte=to_date, end_date__gte=from_date,
        ):
            d = lv.start_date
            while d <= lv.end_date:
                if from_date <= d <= to_date:
                    txt = xls_leave_labels.get(lv.leave_type, lv.leave_type)
                    if lv.note:
                        txt += f' ({lv.note})'
                    xls_leaves_lookup.setdefault((lv.employee_id, d), []).append(txt)
                d += timedelta(days=1)

        xls_note_labels = dict(CalendarNote.TYPE_CHOICES)
        xls_notes_lookup = {}
        for note in CalendarNote.objects.filter(date__gte=from_date, date__lte=to_date):
            lbl = xls_note_labels.get(note.note_type, note.note_type)
            xls_notes_lookup.setdefault(note.date, []).append(f'{lbl}: {note.text}')

        xls_all_dates = []
        d = from_date
        while d <= to_date:
            xls_all_dates.append(d)
            d += timedelta(days=1)

        # Agrupar por empleado con todos los días
        groups = {}
        order = []
        for emp_counter, emp in enumerate(xls_employees, start=1):
            groups[emp_counter] = {
                'emp_num': emp_counter,
                'nombre':  emp.full_name,
                'cargo':   emp.cargo,
                'haber_basico': float(emp.haber_basico) if emp.haber_basico else '',
                'rows': [],
            }
            order.append(emp_counter)
            for day in xls_all_dates:
                wd = xls_wd_lookup.get((emp.id, day))
                if wd:
                    ls  = timezone.localtime(wd.start_time)
                    le  = timezone.localtime(wd.end_time) if wd.end_time else None
                    ref = emp.hora_entrada.hour * 60 + emp.hora_entrada.minute
                    neto = max(0, (wd.duration_minutes or 0) - 60)
                    atraso = max(0, ls.hour * 60 + ls.minute - ref)
                    row_data = [
                        day.strftime('%d-%m-%Y'), _DAY_NAMES[day.weekday()],
                        ls.strftime('%H:%M'), le.strftime('%H:%M') if le else '—',
                        '1:00', f'{neto // 60:02d}:{neto % 60:02d}', atraso,
                    ]
                else:
                    row_data = [day.strftime('%d-%m-%Y'), _DAY_NAMES[day.weekday()], '', '', '', '', '']
                groups[emp_counter]['rows'].append({
                    'data': row_data, 'emp_id': emp.id, 'date': day,
                })

        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        # ── Coca-Cola palette ──────────────────────────────────
        CC_RED      = 'CC0000'
        CC_DARK_RED = '8B0000'
        CC_WHITE    = 'FFFFFF'
        CC_CREAM    = 'FFF5F5'
        CC_ROW_A    = 'FFFFFF'
        CC_ROW_B    = 'FDF0F0'
        CC_WEEKEND  = 'FFE8E8'
        CC_DIM      = 'AAAAAA'
        CC_TEXT     = '1A1A1A'
        CC_BORDER   = 'E0C0C0'
        CC_LEAVE    = 'CC2222'
        CC_NOTE     = '336699'

        def _fill(c):
            return PatternFill('solid', fgColor=c)

        def _font(bold=False, color=CC_TEXT, size=10, italic=False):
            return Font(name='Calibri', bold=bold, color=color, size=size, italic=italic)

        def _border(color=CC_BORDER):
            s = Side(style='thin', color=color)
            return Border(left=s, right=s, top=s, bottom=s)

        def _align(h='left', v='center', wrap=False):
            return Alignment(horizontal=h, vertical=v, wrap_text=wrap)

        COL_WIDTHS   = [13, 10, 14, 14, 11, 17, 14, 32]
        COL_HEADERS  = ['Fecha', 'Día', 'Hora Ingreso', 'Hora Salida',
                        'Refrigerio', 'Horas Trabajadas', 'Atrasos (min)', 'Comentario']
        INFO_LABELS  = ['Item', 'Nombre', 'Cargo', 'Haber Básico']

        wb = openpyxl.Workbook()
        wb.remove(wb.active)  # remove default sheet

        used_names = {}
        for emp_num in order:
            g = groups[emp_num]

            name = _xls_sheet_name(g['nombre'])
            if used_names.get(name):
                used_names[name] += 1
                name = (name + str(used_names[name]))[:31]
            else:
                used_names[name] = 1
            ws = wb.create_sheet(title=name)

            # ── Column widths ──────────────────────────────────
            for ci, w in enumerate(COL_WIDTHS, start=1):
                ws.column_dimensions[get_column_letter(ci)].width = w

            # ── Employee header rows 1-4 ───────────────────────
            info_vals = [g['emp_num'], g['nombre'], g['cargo'],
                         f"Bs. {g['haber_basico']}" if g['haber_basico'] else '—']
            for ri, (lbl, val) in enumerate(zip(INFO_LABELS, info_vals), start=1):
                ca = ws.cell(row=ri, column=1, value=lbl)
                ca.fill = _fill(CC_DARK_RED)
                ca.font = _font(bold=True, color=CC_WHITE, size=9)
                ca.alignment = _align('left')
                ca.border = Border(bottom=Side(style='thin', color=CC_RED))

                cb = ws.cell(row=ri, column=2, value=val)
                cb.fill = _fill(CC_CREAM)
                cb.font = _font(bold=(ri == 2), color=CC_TEXT, size=10)
                cb.alignment = _align('left')
                cb.border = Border(bottom=Side(style='thin', color='EEC0C0'))

                for ci in range(3, 9):
                    c = ws.cell(row=ri, column=ci)
                    c.fill = _fill(CC_CREAM)
                    c.border = Border(bottom=Side(style='thin', color='EEC0C0'))
                ws.row_dimensions[ri].height = 18

            # ── Row 5: thin separator ──────────────────────────
            for ci in range(1, 9):
                c = ws.cell(row=5, column=ci)
                c.fill = _fill(CC_RED)
            ws.row_dimensions[5].height = 4

            # ── Row 6: column headers ──────────────────────────
            for ci, lbl in enumerate(COL_HEADERS, start=1):
                c = ws.cell(row=6, column=ci, value=lbl)
                c.fill = _fill(CC_RED)
                c.font = _font(bold=True, color=CC_WHITE, size=10)
                c.alignment = _align('center')
                c.border = Border(
                    left=Side(style='thin', color='AA0000'),
                    right=Side(style='thin', color='AA0000'),
                    bottom=Side(style='medium', color=CC_DARK_RED),
                )
            ws.row_dimensions[6].height = 22

            # ── Data rows from row 7 ───────────────────────────
            for i, row_obj in enumerate(g['rows']):
                r = 7 + i
                has_wd   = bool(row_obj['data'][2])  # hora_ingreso not empty
                is_wkend = row_obj['date'].weekday() >= 5
                row_bg   = CC_WEEKEND if is_wkend else CC_ROW_A
                txt_col  = CC_DIM if not has_wd else CC_TEXT

                for ci, val in enumerate(row_obj['data'], start=1):
                    cell = ws.cell(row=r, column=ci, value=val)
                    cell.fill = _fill(row_bg)
                    cell.font = _font(color=txt_col, size=9)
                    cell.border = _border()
                    cell.alignment = _align('left' if ci <= 2 else 'center')
                ws.row_dimensions[r].height = 16

                # Refrigerio: only if workday exists
                ws.cell(row=r, column=5).value = '1:00' if has_wd else ''

                # Comment col 8
                leaves_c = xls_leaves_lookup.get((row_obj['emp_id'], row_obj['date']), [])
                notes_c  = xls_notes_lookup.get(row_obj['date'], [])
                comment  = ' · '.join(leaves_c + notes_c)
                cc = ws.cell(row=r, column=8, value=comment)
                cc.fill = _fill(row_bg)
                cc.border = _border()
                cc.alignment = _align('left', wrap=True)
                if comment:
                    cc.font = _font(
                        color=CC_LEAVE if leaves_c else CC_NOTE,
                        size=9, italic=True,
                    )

            # ── Freeze panes below headers ─────────────────────
            ws.freeze_panes = 'A7'

            # ── Thin red bottom border on last data row ────────
            last_r = 7 + len(g['rows']) - 1
            if last_r >= 7:
                for ci in range(1, 9):
                    ws.cell(row=last_r, column=ci).border = Border(
                        left=Side(style='thin', color=CC_BORDER),
                        right=Side(style='thin', color=CC_BORDER),
                        top=Side(style='thin', color=CC_BORDER),
                        bottom=Side(style='medium', color=CC_RED),
                    )

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        filename = f'reporte-asistencia-{label}.xlsx'
        response = HttpResponse(
            buf.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


# ════════════════════════════════════════════════════════════════════════════
#  CERTIFICADO DE PAGO — replica template.xlsx (PL + hojas 1..N por empleado)
# ════════════════════════════════════════════════════════════════════════════

CERT_RED           = 'FFFF0000'
CERT_WHITE         = 'FFFFFFFF'
CERT_BLACK         = 'FF000000'
CERT_EXCHANGE_RATE = 0.461310893326238
CERT_WORKDAYS      = 22
CERT_CATERING_FEE  = 1.16
CERT_CLIENT        = 'EMBOL S.A. / GERENCIA DE OPERACIONES E INNOVACION TECNOLOGICA'
CERT_SERVICE       = 'SERVICIO DE SUPERVISION DE PROYECTOS'
CERT_CURRENCY      = 'Bolivianos'
CERT_ACCT_FMT      = '_(* #,##0.00_);_(* \\(#,##0.00\\);_(* "-"??_);_(@_)'

# (item, descripción, día_ida, día_regreso, días, P.U. (formula o número), cantidad)
CERT_TRAVEL_ROWS = [
    (1, 'Scz-Lpz-Scz',               None, None, None, '=852*2',  None),
    (2, 'Scz-Cba-Scz',               22,   23,   None, '=1021*2', 1),
    (3, 'Scz-Tja-Scz',               None, None, None, '=851*2',  None),
    (4, 'Lpz-Cba-Lpz',               None, None, None, '=443*2',  None),
    (5, 'Alojamiento y Alimentación', 22,   23,   1,    350,       None),
]

# (item, descripción, cantidad, costo_unitario)
CERT_EQUIPMENT_ROWS = [
    (1, 'Dotación de Equipos de Computación i5/i7 de ÚLTIMA GENERACIÓN con Licencia Software Basico - Contrato anual.', 11, 785),
    (2, 'Dotación de Equipos de Computación i5/i7 de ÚLTIMA GENERACIÓN con Licencia Software Especializado de diseño - Contrato anual.', 0, 4857.5),
]


def _cert_side(color=CERT_BLACK):
    from openpyxl.styles import Side
    return Side(style='thin', color=color)


def _cert_border_all(color=CERT_BLACK):
    from openpyxl.styles import Border
    s = _cert_side(color)
    return Border(left=s, right=s, top=s, bottom=s)


def _cert_header_style(cell, size=11, h='center', v='center', wrap=True):
    from openpyxl.styles import Font, PatternFill, Alignment
    cell.fill = PatternFill('solid', fgColor=CERT_RED)
    cell.font = Font(name='Calibri', size=size, bold=True, color=CERT_WHITE)
    cell.alignment = Alignment(horizontal=h, vertical=v, wrap_text=wrap)
    cell.border = _cert_border_all()


def _cert_body_style(cell, h='center', v='center', bold=False, num_fmt=None, wrap=False):
    from openpyxl.styles import Font, Alignment
    cell.font = Font(name='Calibri', size=11, bold=bold, color=CERT_BLACK)
    cell.alignment = Alignment(horizontal=h, vertical=v, wrap_text=wrap)
    cell.border = _cert_border_all()
    if num_fmt:
        cell.number_format = num_fmt


def _cert_merge_header(ws, range_str, text, size=11, h='center', v='center', wrap=True):
    """Merge a range, set text in top-left, apply red header style to all cells inside."""
    ws.merge_cells(range_str)
    from openpyxl.utils.cell import range_boundaries
    min_c, min_r, max_c, max_r = range_boundaries(range_str)
    top_left = ws.cell(row=min_r, column=min_c, value=text)
    _cert_header_style(top_left, size=size, h=h, v=v, wrap=wrap)
    # Apply border to every cell in range (merged cells need individual borders for display)
    for r in range(min_r, max_r + 1):
        for c in range(min_c, max_c + 1):
            cell = ws.cell(row=r, column=c)
            if cell is not top_left:
                cell.border = _cert_border_all()


def _cert_merge_body(ws, range_str, value=None, h='center', v='center', bold=False, num_fmt=None, wrap=False):
    ws.merge_cells(range_str)
    from openpyxl.utils.cell import range_boundaries
    min_c, min_r, max_c, max_r = range_boundaries(range_str)
    top_left = ws.cell(row=min_r, column=min_c, value=value)
    _cert_body_style(top_left, h=h, v=v, bold=bold, num_fmt=num_fmt, wrap=wrap)
    for r in range(min_r, max_r + 1):
        for c in range(min_c, max_c + 1):
            cell = ws.cell(row=r, column=c)
            if cell is not top_left:
                cell.border = _cert_border_all()


def _cert_col_letter(idx):
    from openpyxl.utils import get_column_letter
    return get_column_letter(idx)


def _build_cert_employee_sheet(wb, item, emp, year, month, wd_lookup, leaves_lookup, notes_lookup):
    """Replicates template sheet '1' for one employee."""
    from openpyxl.styles import Font, Alignment

    ws = wb.create_sheet(title=str(item))

    # Column widths (from template)
    widths = {'A': 15.89, 'B': 14.33, 'C': 14.11, 'D': 12.33, 'E': 13.00,
              'F': 14.89, 'G': 17.44, 'H': 15.33}
    for letter, w in widths.items():
        ws.column_dimensions[letter].width = w

    ws.row_dimensions[3].height = 4.8
    ws.row_dimensions[8].height = 4.8

    # Title A2:H2
    _cert_merge_header(ws, 'A2:H2', 'PLANILLA CONTROL DE ASISTENCIA', size=11, h='center')

    # Info rows 4-7 (label en col A con estilo rojo, valor en col B)
    info = [
        ('ITEM', item, None),
        ('NOMBRE', emp.full_name, None),
        ('CARGO', emp.cargo or '', None),
        ('HABER BASICO', float(emp.haber_basico) if emp.haber_basico else 0, CERT_ACCT_FMT),
    ]
    for i, (lbl, val, nfmt) in enumerate(info):
        r = 4 + i
        ca = ws.cell(row=r, column=1, value=lbl)
        _cert_header_style(ca, size=11, h='left')
        cb = ws.cell(row=r, column=2, value=val)
        _cert_body_style(cb, h='left', num_fmt=nfmt)

    # Column headers row 9
    col_headers = ['FECHA', 'DIA', 'HORA INGRESO', 'HORA SALIDA',
                   'REFRIGERIO', 'HORAS TRABAJO', 'ATRASOS MINUTOS', 'OBSERVACIONES']
    for i, h in enumerate(col_headers, start=1):
        c = ws.cell(row=9, column=i, value=h)
        _cert_header_style(c, size=11, h='center')

    # Data rows
    days_in_month = _cal.monthrange(year, month)[1]
    first_data = 10
    last_data = first_data + days_in_month - 1

    for d in range(1, days_in_month + 1):
        r = first_data + d - 1
        day_date = _date(year, month, d)
        wd = wd_lookup.get((emp.id, day_date))

        ca = ws.cell(row=r, column=1, value=day_date)
        _cert_body_style(ca, h='center', num_fmt='yyyy-mm-dd')

        cb = ws.cell(row=r, column=2, value=f'=+A{r}')
        _cert_body_style(cb, h='center', num_fmt='dddd')

        if wd:
            ls = timezone.localtime(wd.start_time)
            le = timezone.localtime(wd.end_time) if wd.end_time else None
            cc = ws.cell(row=r, column=3, value=_time(ls.hour, ls.minute))
            cd = ws.cell(row=r, column=4, value=_time(le.hour, le.minute) if le else None)
            ce = ws.cell(row=r, column=5, value=1)
        else:
            cc = ws.cell(row=r, column=3)
            cd = ws.cell(row=r, column=4)
            ce = ws.cell(row=r, column=5)
        _cert_body_style(cc, h='center', num_fmt='hh:mm')
        _cert_body_style(cd, h='center', num_fmt='hh:mm')
        _cert_body_style(ce, h='center')

        cf = ws.cell(row=r, column=6, value=f'=+(D{r}-C{r})*24-E{r}')
        _cert_body_style(cf, h='center', num_fmt='0.00')

        cg = ws.cell(row=r, column=7,
                     value=f'=+IF(C{r}>0.333333333333333,+(C{r}-0.333333333333333)*24*60,"0")')
        _cert_body_style(cg, h='center', num_fmt='0')

        leaves = leaves_lookup.get((emp.id, day_date), [])
        notes  = notes_lookup.get(day_date, [])
        obs = ' · '.join(leaves + notes)
        ch = ws.cell(row=r, column=8, value=obs)
        _cert_body_style(ch, h='left', wrap=True)

    # Totals rows
    trows = [
        ('TOTAL DIAS TRABAJADOS',  f'=+COUNT(C{first_data}:C{last_data})', '0'),
        ('TOTAL HORAS TRABAJADAS', f'=SUM(F{first_data}:F{last_data})',     '0.00'),
        ('ATRASOS',                f'=SUM(G{first_data}:G{last_data})',     '0'),
    ]
    for i, (label, formula, nfmt) in enumerate(trows):
        r = last_data + 1 + i
        _cert_merge_header(ws, f'A{r}:B{r}', label, size=11, h='right')
        _cert_merge_body(ws, f'C{r}:G{r}', value=formula, h='center', num_fmt=nfmt, bold=True)


def _build_cert_pl_sheet(wb, employees, year, month, wd_lookup):
    """Replicates template sheet 'PL1' (renamed to 'PL') as consolidation."""
    from openpyxl.styles import Font, Alignment, PatternFill

    ws = wb.create_sheet(title='PL', index=0)

    N = len(employees)
    days_in_month = _cal.monthrange(year, month)[1]

    # Widths (from template PL1)
    widths_explicit = {'A': 7.66, 'B': 42.78, 'C': 29.44, 'D': 13.22, 'E': 13.44, 'F': 5.78, 'AL': 15.89}
    for letter, w in widths_explicit.items():
        ws.column_dimensions[letter].width = w
    for col_idx in range(7, 37):  # G..AJ
        ws.column_dimensions[_cert_col_letter(col_idx)].width = 13.0

    # Row heights (selected)
    heights = {
        1: 23.4, 2: 15.0, 3: 18.0, 4: 18.0, 5: 18.0, 6: 18.0, 8: 23.4, 10: 31.2, 11: 5.4,
    }
    for r, h in heights.items():
        ws.row_dimensions[r].height = h

    # ── Section 1: Header (rows 1-10) ────────────────────────────
    _cert_merge_header(ws, 'D1:AK2', 'CERTIFICADO DE PAGO', size=18, h='center', v='center')

    ws.merge_cells('A1:C8')  # left margin

    # Fecha / Certificado number top-right
    ws['AL1'] = 'Fecha:'
    _cert_body_style(ws['AL1'], h='left', v='top')
    ws['AL1'].font = Font(name='Calibri', size=14, bold=False, color=CERT_BLACK)
    ws['AM1'] = _local_now().date()
    _cert_body_style(ws['AM1'], h='left', v='top', num_fmt='yyyy-mm-dd')

    _cert_merge_body(ws, 'AL2:AM7', value=1, h='center', v='center', bold=True)
    _cert_merge_header(ws, 'AL8:AM8', 'CERTIFICADO', size=11, h='center')

    # Cliente
    ws['D3'] = 'CLIENTE:'
    _cert_body_style(ws['D3'], h='left', v='top', bold=True)
    _cert_merge_body(ws, 'E3:V4', value=CERT_CLIENT, h='left', v='center', wrap=True)

    # Periodo
    ws['W3'] = 'PERIODO:'
    _cert_body_style(ws['W3'], h='left', v='center', bold=True)
    _cert_merge_body(ws, 'Y3:AK4', value=_date(year, month, 1), h='center', v='center', num_fmt='mmmm yyyy')

    # Servicio
    ws['D5'] = 'SERVICIO:'
    _cert_body_style(ws['D5'], h='left', v='top', bold=True)
    _cert_merge_body(ws, 'E5:V6', value=CERT_SERVICE, h='left', v='center', wrap=True)

    # Días laborables
    ws['W5'] = 'DIAS LABORABLES:'
    _cert_body_style(ws['W5'], h='left', v='center', bold=True)
    _cert_merge_body(ws, 'AB5:AK6', value=CERT_WORKDAYS, h='left', v='center', bold=True)
    ws['AB5'].font = Font(name='Calibri', size=18, bold=True, color=CERT_BLACK)

    # Orden de compra
    ws['D7'] = 'ORDEN DE COMPRA:'
    _cert_body_style(ws['D7'], h='left', v='center', bold=True)
    _cert_merge_body(ws, 'F7:V8', value='', h='left', v='center')

    # Moneda
    ws['W7'] = 'MONEDA:'
    _cert_body_style(ws['W7'], h='left', v='center', bold=True)
    _cert_merge_body(ws, 'Y7:AK8', value=CERT_CURRENCY, h='left', v='center')

    # Section title
    _cert_merge_header(ws, 'A10:AM10', 'PLANILLA DE PERSONAL', size=24, h='center')

    # ── Section 2: Planilla (rows 12-..) ─────────────────────────
    pl_header_r = 12
    pl_days_r   = 13
    pl_first    = 14
    pl_last     = 13 + N
    pl_subtotal = pl_last + 1

    # Header row 12 (merged with row 13 for some cols)
    _cert_merge_header(ws, f'A{pl_header_r}:A{pl_days_r}', 'ITEM', size=11, h='center')
    _cert_merge_header(ws, f'B{pl_header_r}:B{pl_days_r}', 'NOMBRE', size=11, h='center')
    _cert_merge_header(ws, f'C{pl_header_r}:C{pl_days_r}', 'CARGO', size=11, h='center')
    _cert_merge_header(ws, f'D{pl_header_r}:D{pl_days_r}', 'FECHA DE INICIO', size=11, h='center')
    _cert_merge_header(ws, f'E{pl_header_r}:E{pl_days_r}', 'HABER BASICO', size=11, h='center')
    _cert_merge_header(ws, f'F{pl_header_r}:AJ{pl_header_r}', 'DIAS', size=11, h='center')
    _cert_merge_header(ws, f'AK{pl_header_r}:AK{pl_days_r}', 'TOTAL DIAS', size=11, h='center')
    _cert_merge_header(ws, f'AL{pl_header_r}:AL{pl_days_r}', 'HABER GANADO', size=11, h='center')
    _cert_merge_header(ws, f'AM{pl_header_r}:AM{pl_days_r}', 'FACTURADO', size=11, h='center')

    # Day numbers row 13
    for d in range(1, 32):
        col = 5 + d  # F=6 → day 1
        cell = ws.cell(row=pl_days_r, column=col)
        if d <= days_in_month:
            cell.value = d
        _cert_header_style(cell, size=11, h='center')

    # Employee rows
    month_start = _date(year, month, 1)
    for idx, emp in enumerate(employees, start=1):
        r = 13 + idx
        ws.cell(row=r, column=1, value=idx)
        _cert_body_style(ws.cell(row=r, column=1), h='center')
        ws.cell(row=r, column=2, value=emp.full_name)
        _cert_body_style(ws.cell(row=r, column=2), h='left')
        ws.cell(row=r, column=3, value=emp.cargo or '')
        _cert_body_style(ws.cell(row=r, column=3), h='left')
        ws.cell(row=r, column=4, value=month_start)
        _cert_body_style(ws.cell(row=r, column=4), h='center', num_fmt='yyyy-mm-dd')
        ws.cell(row=r, column=5, value=float(emp.haber_basico) if emp.haber_basico else 0)
        _cert_body_style(ws.cell(row=r, column=5), h='center', num_fmt=CERT_ACCT_FMT)

        # Days F..AJ (31 columns; use formula linking to employee sheet)
        for d in range(1, 32):
            col = 5 + d
            cell = ws.cell(row=r, column=col)
            if d <= days_in_month:
                emp_sheet_row = 9 + d  # employee sheet day rows: 10..10+days-1
                cell.value = f'=+IF(\'{idx}\'!F{emp_sheet_row}>1,"SI","NO")'
            _cert_body_style(cell, h='center')

        # AK: COUNTIF(F:AJ, "SI")
        ws.cell(row=r, column=37, value=f'=+COUNTIF(F{r}:AJ{r},"SI")')
        _cert_body_style(ws.cell(row=r, column=37), h='center')
        # AL: AK/$AB$5*E
        ws.cell(row=r, column=38, value=f'=+AK{r}/$AB$5*E{r}')
        _cert_body_style(ws.cell(row=r, column=38), h='center', num_fmt=CERT_ACCT_FMT)
        # AM: AL/exchange_rate
        ws.cell(row=r, column=39, value=f'=+AL{r}/{CERT_EXCHANGE_RATE}')
        _cert_body_style(ws.cell(row=r, column=39), h='center', num_fmt=CERT_ACCT_FMT)

        ws.row_dimensions[r].height = 19.95

    # Subtotal AM
    ws.cell(row=pl_subtotal, column=39, value=f'=SUM(AM14:AM{pl_last})' if N > 0 else 0)
    _cert_body_style(ws.cell(row=pl_subtotal, column=39), h='center', bold=True, num_fmt=CERT_ACCT_FMT)
    ws.row_dimensions[pl_subtotal].height = 22.2

    pl_subtotal_ref = f'AM{pl_subtotal}'

    # shift offset for downstream sections (template base: 26)
    shift = pl_subtotal - 26

    # ── Section 3: Pasajes y Viáticos + Equipos (rows 28..37) ─────
    travel_title_r    = 28 + shift
    travel_detail_r   = 30 + shift
    travel_first_r    = 32 + shift
    travel_last_r     = 36 + shift
    travel_subtotal_r = 37 + shift

    ws.row_dimensions[travel_title_r].height = 31.2

    # Titles
    _cert_merge_header(ws, f'A{travel_title_r}:S{travel_title_r}', 'PASAJES Y VIATICOS', size=24, h='center')
    _cert_merge_header(ws, f'U{travel_title_r}:AM{travel_title_r}', 'ALQUILER EQUIPOS DE COMPUTACION', size=24, h='center')

    # Pasajes detail header (rows 30-31 merged)
    _cert_merge_header(ws, f'A{travel_detail_r}:A{travel_detail_r+1}', 'ITEM')
    _cert_merge_header(ws, f'B{travel_detail_r}:B{travel_detail_r+1}', 'NOMBRE')
    _cert_merge_header(ws, f'C{travel_detail_r}:C{travel_detail_r+1}', 'DESCRIPCION')
    _cert_merge_header(ws, f'D{travel_detail_r}:D{travel_detail_r+1}', 'FECHA IDA')
    _cert_merge_header(ws, f'E{travel_detail_r}:E{travel_detail_r+1}', 'FECHA REGRESO')
    _cert_merge_header(ws, f'F{travel_detail_r}:G{travel_detail_r+1}', 'DIAS')
    _cert_merge_header(ws, f'H{travel_detail_r}:J{travel_detail_r+1}', 'P.U.\n(Variable)')
    _cert_merge_header(ws, f'K{travel_detail_r}:M{travel_detail_r+1}', 'CANTIDAD')
    _cert_merge_header(ws, f'N{travel_detail_r}:O{travel_detail_r+1}', 'COSTO TOTAL')
    _cert_merge_header(ws, f'P{travel_detail_r}:S{travel_detail_r+1}', 'FACTURADO')

    # Equipos detail header
    _cert_merge_header(ws, f'U{travel_detail_r}:V{travel_detail_r+1}', 'ITEM')
    _cert_merge_header(ws, f'W{travel_detail_r}:AI{travel_detail_r+1}', 'DESCRIPCION')
    _cert_merge_header(ws, f'AJ{travel_detail_r}:AK{travel_detail_r+1}', 'CANTIDAD')
    _cert_merge_header(ws, f'AL{travel_detail_r}:AL{travel_detail_r+1}', 'COSTO TOTAL')
    _cert_merge_header(ws, f'AM{travel_detail_r}:AM{travel_detail_r+1}', 'FACTURADO')

    # Travel rows
    for i, (item, desc, dia_ida, dia_reg, dias, pu, qty) in enumerate(CERT_TRAVEL_ROWS):
        r = travel_first_r + i
        ws.cell(row=r, column=1, value=item)
        _cert_body_style(ws.cell(row=r, column=1), h='center')
        _cert_body_style(ws.cell(row=r, column=2), h='left')
        ws.cell(row=r, column=3, value=desc)
        _cert_body_style(ws.cell(row=r, column=3), h='left', wrap=True)
        # Fechas ida/regreso
        if dia_ida:
            ida_day = min(dia_ida, days_in_month)
            ws.cell(row=r, column=4, value=_date(year, month, ida_day))
            _cert_body_style(ws.cell(row=r, column=4), h='center', num_fmt='yyyy-mm-dd')
        else:
            _cert_body_style(ws.cell(row=r, column=4), h='center')
        if dia_reg:
            reg_day = min(dia_reg, days_in_month)
            ws.cell(row=r, column=5, value=_date(year, month, reg_day))
            _cert_body_style(ws.cell(row=r, column=5), h='center', num_fmt='yyyy-mm-dd')
        else:
            _cert_body_style(ws.cell(row=r, column=5), h='center')
        # Días F:G merged
        _cert_merge_body(ws, f'F{r}:G{r}', value=dias, h='center')
        # P.U. H:J merged
        _cert_merge_body(ws, f'H{r}:J{r}', value=pu, h='center', num_fmt=CERT_ACCT_FMT)
        # Cantidad K:M
        _cert_merge_body(ws, f'K{r}:M{r}', value=qty, h='center')
        # Costo total N:O
        if qty is not None:
            costo = f'=+K{r}*H{r}' if dias is None else f'=+F{r}*H{r}'
        elif dias is not None:
            costo = f'=+F{r}*H{r}'
        else:
            costo = f'=+K{r}*H{r}'
        _cert_merge_body(ws, f'N{r}:O{r}', value=costo, h='center', num_fmt=CERT_ACCT_FMT)
        # Facturado P:S
        _cert_merge_body(ws, f'P{r}:S{r}', value=f'=+N{r}*1.25', h='center', bold=True, num_fmt=CERT_ACCT_FMT)

    # Travel subtotal
    _cert_merge_body(ws, f'P{travel_subtotal_r}:S{travel_subtotal_r}',
                     value=f'=SUM(P{travel_first_r}:S{travel_last_r})',
                     h='center', bold=True, num_fmt=CERT_ACCT_FMT)

    # Equipment rows (only 2; use first two travel rows worth of space)
    for i, (item, desc, qty, cu) in enumerate(CERT_EQUIPMENT_ROWS):
        r = travel_first_r + i
        _cert_merge_body(ws, f'U{r}:V{r}', value=item, h='center')
        _cert_merge_body(ws, f'W{r}:AI{r}', value=desc, h='left', wrap=True)
        _cert_merge_body(ws, f'AJ{r}:AK{r}', value=qty, h='center')
        ws.cell(row=r, column=38, value=cu)
        _cert_body_style(ws.cell(row=r, column=38), h='center', num_fmt=CERT_ACCT_FMT)
        ws.cell(row=r, column=39, value=f'=+AL{r}*AJ{r}')
        _cert_body_style(ws.cell(row=r, column=39), h='center', bold=True, num_fmt=CERT_ACCT_FMT)

    # Equipment subtotal (at travel_first_r + len(CERT_EQUIPMENT_ROWS))
    eq_subtotal_r = travel_first_r + len(CERT_EQUIPMENT_ROWS)
    ws.cell(row=eq_subtotal_r, column=39,
            value=f'=SUM(AM{travel_first_r}:AM{travel_first_r + len(CERT_EQUIPMENT_ROWS) - 1})')
    _cert_body_style(ws.cell(row=eq_subtotal_r, column=39),
                     h='center', bold=True, num_fmt=CERT_ACCT_FMT)

    pl_travel_ref   = f'P{travel_subtotal_r}'
    pl_equip_ref    = f'AM{eq_subtotal_r}'

    # ── Catering sections (LPZ, CBA, SCZ) ────────────────────────
    def _build_catering(section_title, city_code, title_row):
        ws.row_dimensions[title_row].height = 31.2
        _cert_merge_header(ws, f'A{title_row}:AK{title_row}', section_title, size=24, h='center')
        # Fee cont cell
        ws.cell(row=title_row, column=38, value='Fee Cont')
        _cert_body_style(ws.cell(row=title_row, column=38), h='center', bold=True)
        fee_cell = ws.cell(row=title_row, column=39, value=CERT_CATERING_FEE)
        _cert_body_style(fee_cell, h='center', bold=True, num_fmt='0.00')
        fee_ref = f'$AM${title_row}'

        detail_r = title_row + 2
        _cert_merge_header(ws, f'A{detail_r}:A{detail_r+1}', 'ITEM')
        _cert_merge_header(ws, f'B{detail_r}:B{detail_r+1}', 'NOMBRE')
        _cert_merge_header(ws, f'C{detail_r}:C{detail_r+1}', 'CARGO')
        _cert_merge_header(ws, f'D{detail_r}:D{detail_r+1}', 'FECHA DE INICIO')
        _cert_merge_header(ws, f'E{detail_r}:E{detail_r+1}', 'P.U. CATERING')
        _cert_merge_header(ws, f'F{detail_r}:AJ{detail_r}', 'DIAS')
        _cert_merge_header(ws, f'AK{detail_r}:AK{detail_r+1}', 'TOTAL DIAS')
        _cert_merge_header(ws, f'AL{detail_r}:AL{detail_r+1}', 'COSTO TOTAL')
        _cert_merge_header(ws, f'AM{detail_r}:AM{detail_r+1}', 'FACTURADO')

        # Day numbers row
        days_r = detail_r + 1
        for d in range(1, 32):
            col = 5 + d
            cell = ws.cell(row=days_r, column=col)
            if d <= days_in_month:
                cell.value = d
            _cert_header_style(cell, size=11, h='center')

        # Employee rows for this city
        city_employees = [(i + 1, e) for i, e in enumerate(employees) if e.ciudad == city_code]
        first_emp_r = days_r + 1
        last_emp_r  = first_emp_r + len(city_employees) - 1 if city_employees else first_emp_r

        for i, (orig_item, emp) in enumerate(city_employees):
            r = first_emp_r + i
            ws.cell(row=r, column=1, value=orig_item)
            _cert_body_style(ws.cell(row=r, column=1), h='center')
            ws.cell(row=r, column=2, value=emp.full_name)
            _cert_body_style(ws.cell(row=r, column=2), h='left')
            ws.cell(row=r, column=3, value=emp.cargo or '')
            _cert_body_style(ws.cell(row=r, column=3), h='left')
            ws.cell(row=r, column=4, value=month_start)
            _cert_body_style(ws.cell(row=r, column=4), h='center', num_fmt='yyyy-mm-dd')
            ws.cell(row=r, column=5, value=25)
            _cert_body_style(ws.cell(row=r, column=5), h='center', num_fmt=CERT_ACCT_FMT)
            # Days from employee sheet
            for d in range(1, 32):
                col = 5 + d
                cell = ws.cell(row=r, column=col)
                if d <= days_in_month:
                    emp_sheet_row = 9 + d
                    cell.value = f'=+IF(\'{orig_item}\'!F{emp_sheet_row}>1,"SI","NO")'
                _cert_body_style(cell, h='center')
            ws.cell(row=r, column=37, value=f'=+COUNTIF(F{r}:AJ{r},"SI")')
            _cert_body_style(ws.cell(row=r, column=37), h='center')
            ws.cell(row=r, column=38, value=f'=+AK{r}*E{r}')
            _cert_body_style(ws.cell(row=r, column=38), h='center', num_fmt=CERT_ACCT_FMT)
            ws.cell(row=r, column=39, value=f'=+AL{r}*{fee_ref}')
            _cert_body_style(ws.cell(row=r, column=39), h='center', bold=True, num_fmt=CERT_ACCT_FMT)
            ws.row_dimensions[r].height = 19.95

        # Subtotal
        sub_r = last_emp_r + 1 if city_employees else first_emp_r
        if city_employees:
            ws.cell(row=sub_r, column=39,
                    value=f'=SUM(AM{first_emp_r}:AM{last_emp_r})')
        else:
            ws.cell(row=sub_r, column=39, value=0)
        _cert_body_style(ws.cell(row=sub_r, column=39), h='center', bold=True, num_fmt=CERT_ACCT_FMT)

        return sub_r

    # Template LPZ title at row 39 (shift applied)
    lpz_title_r = 39 + shift
    lpz_sub_r = _build_catering('PLANILLA DE ALIMENTACION LA PAZ', 'LPZ', lpz_title_r)

    cba_title_r = lpz_sub_r + 2
    cba_sub_r = _build_catering('PLANILLA DE ALIMENTACION CBA', 'CBA', cba_title_r)

    scz_title_r = cba_sub_r + 2
    scz_sub_r = _build_catering('PLANILLA DE ALIMENTACION SCZ', 'SCZ', scz_title_r)

    # ── Grand total ─────────────────────────────────────────────
    total_r = scz_sub_r + 2
    ws.row_dimensions[total_r].height = 25.8
    _cert_merge_body(ws, f'W{total_r}:AK{total_r}', value='TOTAL FACTURACION',
                     h='center', bold=True)
    ws[f'W{total_r}'].font = Font(name='Calibri', size=20, bold=True, color=CERT_BLACK)

    grand_total_formula = (
        f'=+{pl_subtotal_ref}+{pl_travel_ref}+{pl_equip_ref}+'
        f'AM{lpz_sub_r}+AM{cba_sub_r}+AM{scz_sub_r}'
    )
    _cert_merge_body(ws, f'AL{total_r}:AM{total_r}', value=grand_total_formula,
                     h='center', bold=True, num_fmt=CERT_ACCT_FMT)
    ws[f'AL{total_r}'].font = Font(name='Calibri', size=20, bold=True, color=CERT_BLACK)

    # "Son : [total]" text
    son_r = total_r + 2
    ws.row_dimensions[son_r].height = 23.4
    _cert_merge_body(ws,
                     f'W{son_r}:AM{son_r}',
                     value=f'="Son : " & TEXT(AL{total_r},"#,##0.00") & " Bolivianos"',
                     h='center', bold=True, wrap=True)

    # ── Signature block ─────────────────────────────────────────
    sig_top_r = son_r + 2
    sig_bottom_r = sig_top_r + 4
    for rr in (sig_bottom_r, sig_bottom_r + 1):
        ws.row_dimensions[rr].height = 14.4
    _cert_merge_body(ws, f'C{sig_top_r}:M{sig_top_r + 3}', value='', h='center')
    _cert_merge_body(ws, f'O{sig_top_r}:AA{sig_top_r + 3}', value='', h='center')
    _cert_merge_body(ws, f'AC{sig_top_r}:AM{sig_top_r + 3}', value='', h='center')

    _cert_merge_header(ws, f'C{sig_bottom_r}:M{sig_bottom_r + 1}',
                       'REDLINE GENERAL SERVICES', size=16, h='center', wrap=True)
    _cert_merge_header(ws, f'O{sig_bottom_r}:AA{sig_bottom_r + 1}',
                       'FIRMA APROBACION EMBOL', size=16, h='center', wrap=True)
    _cert_merge_header(ws, f'AC{sig_bottom_r}:AM{sig_bottom_r + 1}',
                       'FIRMA APROBACION EMBOL', size=16, h='center', wrap=True)


class CertificadoExportView(APIView):
    """Descarga el Certificado de Pago como .xlsx (replica template.xlsx)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            executive = request.user.employee
        except Exception:
            return Response({'error': 'Perfil no encontrado'}, status=404)
        if not executive.is_executive:
            return Response({'error': 'Acceso no autorizado'}, status=403)

        local_now = _local_now()
        try:
            year  = int(request.query_params.get('year',  local_now.year))
            month = int(request.query_params.get('month', local_now.month))
            if not (1 <= month <= 12):
                raise ValueError
        except (ValueError, TypeError):
            year, month = local_now.year, local_now.month

        from_date = _date(year, month, 1)
        to_date   = _date(year, month, _cal.monthrange(year, month)[1])
        first_dt  = timezone.make_aware(_datetime.combine(from_date, _time(0, 0, 0)))
        last_dt   = timezone.make_aware(_datetime.combine(to_date,   _time(23, 59, 59)))

        employees = list(Employee.objects
                         .filter(is_active=True, is_executive=False)
                         .order_by(models.F('item_number').asc(nulls_last=True), 'full_name'))

        wd_lookup = {}
        for wd in Workday.objects.filter(
            employee__in=employees,
            status=Workday.STATUS_COMPLETED,
            start_time__gte=first_dt, start_time__lte=last_dt,
        ).select_related('employee'):
            ls = timezone.localtime(wd.start_time)
            wd_lookup[(wd.employee_id, ls.date())] = wd

        leave_labels = dict(EmployeeLeave.TYPE_CHOICES)
        leaves_lookup = {}
        for lv in EmployeeLeave.objects.filter(
            employee__in=employees,
            start_date__lte=to_date, end_date__gte=from_date,
        ):
            d = lv.start_date
            while d <= lv.end_date:
                if from_date <= d <= to_date:
                    txt = leave_labels.get(lv.leave_type, lv.leave_type)
                    if lv.note:
                        txt += f' ({lv.note})'
                    leaves_lookup.setdefault((lv.employee_id, d), []).append(txt)
                d += timedelta(days=1)

        note_labels = dict(CalendarNote.TYPE_CHOICES)
        notes_lookup = {}
        for note in CalendarNote.objects.filter(date__gte=from_date, date__lte=to_date):
            lbl = note_labels.get(note.note_type, note.note_type)
            notes_lookup.setdefault(note.date, []).append(f'{lbl}: {note.text}')

        import openpyxl
        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        # Build PL (index 0) and employee sheets
        _build_cert_pl_sheet(wb, employees, year, month, wd_lookup)
        for idx, emp in enumerate(employees, start=1):
            _build_cert_employee_sheet(wb, idx, emp, year, month,
                                       wd_lookup, leaves_lookup, notes_lookup)

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        filename = f'certificado-{year}-{month:02d}.xlsx'
        response = HttpResponse(
            buf.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
