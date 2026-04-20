"""
Management command: seed_dev_data
Crea 3 empleados de prueba y llena el mes actual con jornadas (lunes a viernes).
Solo disponible en DEBUG=True.

Uso:
    python manage.py seed_dev_data           # crea empleados + jornadas del mes actual
    python manage.py seed_dev_data --clear   # borra empleados de prueba y sus datos primero
"""
import random
from datetime import date, timedelta, datetime, time
from calendar import monthrange

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


SEED_EMPLOYEES = [
    {
        'username': 'seed_ana_garcia',
        'full_name': 'Ana García López',
        'cargo':'Desarrollo',
        'password': 'seed1234',
        'email': 'ana.garcia@empresa.dev',
    },
    {
        'username': 'seed_carlos_mendez',
        'full_name': 'Carlos Méndez Ruiz',
        'cargo':'Operaciones',
        'password': 'seed1234',
        'email': 'carlos.mendez@empresa.dev',
    },
    {
        'username': 'seed_laura_torres',
        'full_name': 'Laura Torres Vega',
        'cargo':'Marketing',
        'password': 'seed1234',
        'email': 'laura.torres@empresa.dev',
    },
]

ACTIVITIES_DONE = [
    "Revisé tickets pendientes y actualicé el backlog del sprint.",
    "Implementé el endpoint de reportes mensuales y escribí tests unitarios.",
    "Corrección de bug en el módulo de autenticación — token expirado no redirigía.",
    "Reunión de planificación con el equipo. Definimos las tareas para la semana.",
    "Refactoring del componente de dashboard para mejorar el tiempo de carga.",
    "Configuré el pipeline de CI/CD para los nuevos tests de integración.",
    "Documenté la API y actualicé el README con los nuevos endpoints.",
    "Revisé y aprobé 3 pull requests. Detecté un N+1 query en el ORM.",
    "Migración de la base de datos para el nuevo modelo.",
    "Investigué opciones para optimizar el rendimiento de las queries.",
    "Ajusté los estilos del dashboard — colores y responsive.",
    "Despliegue a staging y revisión de logs post-deploy.",
    "Reunión con el cliente para presentar avances del sprint.",
    "Coordiné con el equipo de diseño los nuevos wireframes.",
    "Revisé alertas y cerré 5 issues resueltos.",
    "Análisis de métricas y preparación del informe semanal.",
    "Actualicé dependencias del proyecto y revisé CVEs pendientes.",
    "Preparé la presentación para la reunión ejecutiva del lunes.",
    "Onboarding de nuevo integrante del equipo — walkthrough del proyecto.",
    "Investigué y documenté la causa raíz de un error reportado en producción.",
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
    help = 'Crea 3 empleados de prueba y llena el mes actual con jornadas (solo DEBUG=True)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear', action='store_true',
            help='Elimina los empleados seed y sus datos antes de regenerar',
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Este comando solo está disponible con DEBUG=True.')

        from employees.models import Employee
        from workdays.models import Workday, DailyReport, InactivityPeriod

        if options['clear']:
            usernames = [e['username'] for e in SEED_EMPLOYEES]
            deleted_users = User.objects.filter(username__in=usernames).delete()
            self.stdout.write(self.style.WARNING(
                f'Eliminados {deleted_users[0]} registros de empleados seed.'
            ))

        today = date.today()
        year, month = today.year, today.month
        _, last_day = monthrange(year, month)

        employees = []
        for data in SEED_EMPLOYEES:
            user, created = User.objects.get_or_create(
                username=data['username'],
                defaults={
                    'email': data['email'],
                    'first_name': data['full_name'].split()[0],
                    'last_name': ' '.join(data['full_name'].split()[1:]),
                },
            )
            if created:
                user.set_password(data['password'])
                user.save()

            employee, emp_created = Employee.objects.get_or_create(
                nextcloud_username=data['username'],
                defaults={
                    'user': user,
                    'full_name': data['full_name'],
                    'cargo': data['cargo'],
                    'is_active': True,
                    'solo_movil': True,
                },
            )
            if not emp_created:
                employee.user = user
                employee.save()

            status = 'creado' if emp_created else 'ya existía'
            self.stdout.write(f'  Empleado {employee.full_name} ({status})')
            employees.append(employee)

        self.stdout.write(self.style.SUCCESS(f'\n3 empleados listos. Generando jornadas para {month}/{year}...\n'))

        total_created = 0

        for employee in employees:
            created_count = 0
            for day_num in range(1, last_day + 1):
                day = date(year, month, day_num)

                if day.weekday() >= 5:
                    continue

                if day > today:
                    continue

                if Workday.objects.filter(
                    employee=employee,
                    start_time__date=day,
                    status=Workday.STATUS_COMPLETED,
                ).exists():
                    continue

                start_hour = random.randint(8, 9)
                start_min = random.choice([0, 15, 30, 45])
                start_dt = timezone.make_aware(
                    datetime.combine(day, time(start_hour, start_min))
                )

                duration_minutes = random.randint(360, 570)

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
                    mid = start_dt + timedelta(minutes=duration_minutes // 2)
                    InactivityPeriod.objects.create(
                        workday=workday,
                        started_at=mid,
                        ended_at=mid + timedelta(minutes=inactivity_minutes),
                        duration_minutes=inactivity_minutes,
                    )

                created_count += 1

            self.stdout.write(f'  {employee.full_name}: {created_count} jornadas creadas')
            total_created += created_count

        self.stdout.write(self.style.SUCCESS(
            f'\nTotal: {total_created} jornadas generadas para {len(employees)} empleados '
            f'(mes {month}/{year}, lunes a viernes).'
        ))
