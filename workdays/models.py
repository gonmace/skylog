from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from employees.models import Employee


class CaptureConfig(models.Model):
    """Configuración global de capturas (singleton — solo existe una fila)."""
    capture_interval_minutes = models.IntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(480)],
        verbose_name='Intervalo de captura (minutos)',
        help_text='Intervalo por defecto para todos los empleados. Rango: 1–480 min.',
    )

    class Meta:
        verbose_name = 'Configuración de capturas'
        verbose_name_plural = 'Configuración de capturas'

    def __str__(self):
        return f'Intervalo global: {self.capture_interval_minutes} min'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Workday(models.Model):
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_COMPLETED = 'completed'
    STATUS_INCOMPLETE = 'incomplete'
    STATUS_CHOICES = [
        (STATUS_IN_PROGRESS, 'En progreso'),
        (STATUS_COMPLETED, 'Completada'),
        (STATUS_INCOMPLETE, 'Incompleta'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='workdays')
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_IN_PROGRESS)

    def __str__(self):
        return f"{self.employee.full_name} — {self.start_time.strftime('%Y-%m-%d')}"

    class Meta:
        ordering = ['-start_time']
        verbose_name = 'Jornada'
        verbose_name_plural = 'Jornadas'
        indexes = [
            models.Index(fields=['employee', 'status']),
        ]


class InactivityPeriod(models.Model):
    """Período de inactividad detectado dentro de una jornada (agente desconectado)."""
    workday = models.ForeignKey(Workday, on_delete=models.CASCADE, related_name='inactivity_periods')
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField()
    duration_minutes = models.IntegerField()

    class Meta:
        ordering = ['started_at']
        verbose_name = 'Período de inactividad'
        verbose_name_plural = 'Períodos de inactividad'

    def __str__(self):
        return f"{self.workday.employee.full_name} — {self.duration_minutes} min inactivo"


class DailyReport(models.Model):
    workday = models.OneToOneField(Workday, on_delete=models.CASCADE, related_name='daily_report')
    activities_done = models.TextField()
    activities_planned = models.TextField()
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reporte — {self.workday}"

    class Meta:
        verbose_name = 'Reporte diario'
        verbose_name_plural = 'Reportes diarios'


class ExecutiveMessage(models.Model):
    recipient = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='executive_messages')
    sender = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='sent_messages')
    body = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Mensaje de {self.sender.full_name} a {self.recipient.full_name} — {self.sent_at.strftime('%Y-%m-%d %H:%M')}"

    class Meta:
        ordering = ['-sent_at']
        verbose_name = 'Mensaje ejecutivo'
        verbose_name_plural = 'Mensajes ejecutivos'
        indexes = [models.Index(fields=['recipient', 'acknowledged_at'])]
