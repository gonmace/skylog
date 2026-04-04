"""
Management command: seed_dev_workdays
Genera jornadas ficticias para el usuario dev_employee en los últimos 2 meses.
Solo disponible en DEBUG=True.

Uso:
    python manage.py seed_dev_workdays           # genera los últimos 60 días
    python manage.py seed_dev_workdays --clear   # borra las existentes primero
    python manage.py seed_dev_workdays --days 30 # solo los últimos 30 días
"""
import random
from datetime import date, timedelta, datetime, time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


ACTIVITIES_DONE = [
    "Revisé tickets pendientes y actualicé el backlog del sprint.",
    "Implementé el endpoint de reportes mensuales y escribí tests unitarios.",
    "Corrección de bug en el módulo de autenticación — token expirado no redirigía correctamente.",
    "Reunión de planificación con el equipo. Definimos las tareas para la semana.",
    "Refactoring del componente de dashboard para mejorar el tiempo de carga.",
    "Configuré el pipeline de CI/CD para los nuevos tests de integración.",
    "Documenté la API de workdays y actualicé el README con los nuevos endpoints.",
    "Revisé y aprobé 3 pull requests del equipo. Detecté un N+1 query en el ORM.",
    "Migración de la base de datos para el nuevo modelo de mensajes ejecutivos.",
    "Investigué opciones para optimizar las capturas de pantalla con menor uso de RAM.",
    "Ajusté los estilos del calendario en el dashboard — colores y responsive.",
    "Despliegue a staging y revisión de logs post-deploy.",
    "Reunión con el cliente para presentar avances del sprint.",
    "Escribí el script de seed de datos para el entorno de desarrollo.",
    "Revisé alertas de Sentry y cerré 5 issues resueltos.",
]

ACTIVITIES_PLANNED = [
    "Continuar con la integración del módulo de reportes.",
    "Revisar tickets críticos asignados para mañana.",
    "Completar los tests del endpoint de mensajes y hacer merge.",
    "Preparar demo para la reunión del viernes.",
    "Optimizar las queries del overview ejecutivo.",
    "Actualizar dependencias del proyecto y revisar CVEs.",
    "Finalizar la documentación técnica del sprint.",
    "Sincronización con diseño para revisar los nuevos wireframes.",
    "Investigar solución al problema de caché en producción.",
    "Hacer code review de los PRs pendientes del equipo.",
]


class Command(BaseCommand):
    help = 'Genera jornadas ficticias para dev_employee (solo DEBUG=True)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=60,
            help='Número de días hacia atrás a cubrir (default: 60)',
        )
        parser.add_argument(
            '--clear', action='store_true',
            help='Elimina las jornadas existentes de dev_employee antes de generar',
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Este comando solo está disponible con DEBUG=True.')

        from employees.models import Employee
        from workdays.models import Workday, DailyReport, InactivityPeriod

        try:
            employee = Employee.objects.get(nextcloud_username='dev_employee')
        except Employee.DoesNotExist:
            raise CommandError(
                'El usuario dev_employee no existe. '
                'Visita http://localhost:8000/dev-login/?role=employee primero.'
            )

        if options['clear']:
            deleted, _ = Workday.objects.filter(employee=employee).delete()
            self.stdout.write(self.style.WARNING(f'Eliminadas {deleted} jornadas existentes.'))

        today = date.today()
        days = options['days']
        created = 0

        for offset in range(days, 0, -1):
            day = today - timedelta(days=offset)

            # Saltar fines de semana
            if day.weekday() >= 5:
                continue

            # ~15% de días laborables sin jornada (vacaciones, enfermedad, etc.)
            if random.random() < 0.15:
                continue

            # Evitar duplicados
            if Workday.objects.filter(
                employee=employee,
                start_time__date=day,
                status=Workday.STATUS_COMPLETED,
            ).exists():
                continue

            # Hora de entrada: entre 8:00 y 9:30
            start_hour = random.randint(8, 9)
            start_min  = random.choice([0, 15, 30, 45])
            start_dt   = timezone.make_aware(
                datetime.combine(day, time(start_hour, start_min))
            )

            # Duración: entre 6h y 9.5h, con algo de variabilidad
            duration_minutes = random.randint(360, 570)

            # ~20% de días con período de inactividad (pausa larga)
            inactivity_minutes = 0
            if random.random() < 0.20:
                inactivity_minutes = random.randint(20, 75)

            end_dt = start_dt + timedelta(minutes=duration_minutes)

            workday = Workday.objects.create(
                employee=employee,
                start_time=start_dt,
                end_time=end_dt,
                duration_minutes=duration_minutes,
                status=Workday.STATUS_COMPLETED,
            )

            DailyReport.objects.create(
                workday=workday,
                activities_done=random.choice(ACTIVITIES_DONE),
                activities_planned=random.choice(ACTIVITIES_PLANNED),
            )

            if inactivity_minutes:
                # La inactividad ocurre a mitad de jornada
                mid = start_dt + timedelta(minutes=duration_minutes // 2)
                InactivityPeriod.objects.create(
                    workday=workday,
                    started_at=mid,
                    ended_at=mid + timedelta(minutes=inactivity_minutes),
                    duration_minutes=inactivity_minutes,
                )

            created += 1

        self.stdout.write(self.style.SUCCESS(
            f'Generadas {created} jornadas para {employee.full_name} '
            f'(últimos {days} días, excluyendo fines de semana y días aleatorios).'
        ))
