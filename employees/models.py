import datetime
from django.db import models
from django.contrib.auth.models import User


class Employee(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='employee')
    nextcloud_username = models.CharField(max_length=150, unique=True)
    full_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    is_executive = models.BooleanField(default=False)
    cargo = models.CharField(max_length=150, blank=True, verbose_name='Cargo')
    haber_basico = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Haber básico',
    )
    hora_entrada = models.TimeField(
        default=datetime.time(8, 0), verbose_name='Hora de entrada',
        help_text='Hora de referencia para calcular atrasos. Default: 08:00',
    )
    capture_interval_minutes = models.IntegerField(
        null=True,
        blank=True,
        verbose_name='Intervalo de captura (minutos)',
        help_text='Si se establece, sobreescribe el intervalo global para este empleado.',
    )
    screenshots_enabled = models.BooleanField(
        default=True,
        verbose_name='Capturas habilitadas',
        help_text='Deshabilitar impide que el agente envíe capturas de pantalla para este empleado.',
    )
    skylog_access = models.BooleanField(
        default=True,
        verbose_name='Acceso a Skylog',
        help_text='Deshabilitar bloquea el acceso al agente y al dashboard de este empleado.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    agent_last_seen = models.DateTimeField(null=True, blank=True)
    agent_version = models.CharField(max_length=20, blank=True, default='')
    agent_online = models.BooleanField(default=False)
    solo_movil = models.BooleanField(
        default=False,
        verbose_name='Solo móvil',
        help_text='Si está activo, el empleado no necesita el agente de escritorio. El dashboard estará completamente habilitado sin requerir que el agente esté instalado o activo.',
    )

    def __str__(self):
        return self.full_name

    class Meta:
        ordering = ['full_name']
        verbose_name = 'Empleado'
        verbose_name_plural = 'Empleados'
