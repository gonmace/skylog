import datetime
import re
from django.db import models
from django.contrib.auth.models import User


class Employee(models.Model):
    ROLE_SUPERVISOR      = 'supervisor'
    ROLE_PROJECT_MANAGER = 'project_manager'
    ROLE_OTRO            = 'otro'
    ROLE_LABELS = {
        ROLE_SUPERVISOR:      'Supervisores',
        ROLE_PROJECT_MANAGER: 'Project Managers',
        ROLE_OTRO:            'Otros',
    }

    CIUDAD_NONE = 'NONE'
    CIUDAD_LPZ  = 'LPZ'
    CIUDAD_CBA  = 'CBA'
    CIUDAD_SCZ  = 'SCZ'
    CIUDAD_CHOICES = [
        (CIUDAD_NONE, 'Sin catering'),
        (CIUDAD_LPZ,  'La Paz'),
        (CIUDAD_CBA,  'Cochabamba'),
        (CIUDAD_SCZ,  'Santa Cruz'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='employee')
    nextcloud_username = models.CharField(max_length=150, unique=True)
    full_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    is_executive = models.BooleanField(default=False)
    cargo = models.CharField(max_length=150, blank=True, verbose_name='Cargo')
    haber_basico = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Haber básico',
    )
    ciudad = models.CharField(
        max_length=4, choices=CIUDAD_CHOICES, default=CIUDAD_NONE,
        verbose_name='Ciudad (catering)',
        help_text='Ciudad donde recibe catering en el certificado de pago. Si no aplica, dejar en "Sin catering".',
    )
    item_number = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name='N° Ítem',
        help_text='Orden del empleado en el Certificado de Pago (1, 2, 3…). Empleados sin número aparecen al final ordenados por nombre.',
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
    can_message_leads = models.BooleanField(
        default=False,
        verbose_name='Puede enviar mensajes a Sup/PM',
        help_text='Habilita un botón para enviar un mensaje a todos los Supervisores y/o Project Managers.',
    )
    can_view_stats = models.BooleanField(
        default=False,
        verbose_name='Puede ver estadísticas globales',
        help_text='Habilita el acceso a las estadísticas de todos los empleados (las que ven los ejecutivos).',
    )
    can_edit_tags = models.BooleanField(
        default=False,
        verbose_name='Puede editar etiquetas',
        help_text='Habilita el acceso a la gestión de etiquetas (proyectos, sedes, entregables).',
    )
    can_view_report = models.BooleanField(
        default=False,
        verbose_name='Puede ver registro de asistencia',
        help_text='Habilita el acceso al registro de asistencia (las que ven los ejecutivos).',
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

    MOBILE_TYPE_GPS    = 'gps'
    MOBILE_TYPE_REPORT = 'report'
    MOBILE_TYPE_CHOICES = [
        (MOBILE_TYPE_GPS,    'Solo coordenadas'),
        (MOBILE_TYPE_REPORT, 'Reporte diario'),
    ]
    mobile_type = models.CharField(
        max_length=10,
        choices=MOBILE_TYPE_CHOICES,
        null=True,
        blank=True,
        verbose_name='Tipo móvil',
        help_text='Solo coordenadas: captura GPS al iniciar y finalizar. Reporte diario: debe completar reporte al finalizar.',
    )
    mobile_device_id = models.CharField(
        max_length=64,
        blank=True,
        default='',
        verbose_name='ID de dispositivo móvil',
        help_text='Se asigna automáticamente al primer login. Borrar para permitir vincular un nuevo dispositivo.',
    )

    def __str__(self):
        return self.full_name

    @property
    def role(self):
        """Rol derivado del cargo: supervisor / project_manager / otro."""
        from core.textutils import normalize
        c = normalize(self.cargo)
        if 'supervisor' in c:
            return self.ROLE_SUPERVISOR
        if 'project manager' in c or re.search(r'\bpm\b', c):
            return self.ROLE_PROJECT_MANAGER
        return self.ROLE_OTRO

    @property
    def role_label(self):
        return self.ROLE_LABELS[self.role]

    class Meta:
        ordering = ['full_name']
        verbose_name = 'Empleado'
        verbose_name_plural = 'Empleados'


from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=User)
def sync_employee_full_name(sender, instance, **kwargs):
    """full_name se deriva de nombre + apellidos del User (editados en el admin)."""
    full = f'{instance.first_name} {instance.last_name}'.strip().upper()
    if not full:
        return
    Employee.objects.filter(user=instance).exclude(full_name=full).update(full_name=full)
