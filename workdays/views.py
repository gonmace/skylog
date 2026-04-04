import calendar as _cal
from datetime import timedelta, datetime as _datetime, time as _time, date as _date
from django.db import models
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
