from django.db import models
from django.contrib.auth.models import User


class Employee(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='employee')
    nextcloud_username = models.CharField(max_length=150, unique=True)
    full_name = models.CharField(max_length=255)
    department = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    is_executive = models.BooleanField(default=False)
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
