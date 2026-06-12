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
    auto_closed = models.BooleanField(default=False)
    start_latitude  = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    start_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    end_latitude    = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    end_longitude   = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

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


# Código de la categoría "cajón de sastre". El clasificador determinístico la
# usa como fallback y el LLM la usa cuando ninguna categoría aplica.
OTROS_CODE = 'otros'

# Sede del empleado (employee.ciudad) → nombre completo, usado como ubicación.
SEDE_NAMES = {'SCZ': 'Santa Cruz', 'LPZ': 'La Paz', 'CBA': 'Cochabamba', 'TJA': 'Tarija'}


class ActivityCategory(models.Model):
    """Categoría de actividad administrable desde el admin.

    Las 11 categorías iniciales se siembran por data migration (is_protected=True).
    Se pueden agregar/editar nuevas desde el admin; el clasificador LLM (n8n) y las
    estadísticas usan siempre esta lista dinámica.
    """
    code        = models.SlugField(max_length=20, unique=True)
    label       = models.CharField(max_length=80)
    color       = models.CharField(max_length=20, default='#64748b',
                                   help_text='Color (hex) para gráficos del dashboard.')
    order       = models.PositiveSmallIntegerField(default=0)
    is_active   = models.BooleanField(default=True,
                                      help_text='Si está activa se ofrece al clasificador LLM.')
    is_protected = models.BooleanField(default=False,
                                       help_text='Categoría base: no se puede borrar ni cambiar su código.')

    class Meta:
        ordering = ['order', 'label']
        verbose_name = 'Categoría de actividad'
        verbose_name_plural = 'Categorías de actividad'

    def __str__(self):
        return f'{self.label} ({self.code})'


class ActivityTag(models.Model):
    """Etiqueta libre extraída por el LLM de `activities_done`: proyecto, ubicación
    o entregable. Se autogeneran al clasificar. Como un mismo proyecto/lugar se
    nombra de varias formas, el ejecutivo fusiona variantes en una sola apuntando
    `canonical` al tag elegido (fusión NO destructiva: el reporting agrupa por root)."""
    KIND_PROJECT     = 'project'
    KIND_LOCATION    = 'location'
    KIND_DELIVERABLE = 'deliverable'
    KIND_CHOICES = [
        (KIND_PROJECT,     'Proyecto'),
        (KIND_LOCATION,    'Ubicación'),
        (KIND_DELIVERABLE, 'Entregable'),
    ]

    kind       = models.CharField(max_length=12, choices=KIND_CHOICES)
    name       = models.CharField(max_length=120)            # display (como se extrajo / editado)
    code       = models.CharField(max_length=40, blank=True, default='')  # código oficial (ej. CMT.LPZ.MQ.2668)
    color      = models.CharField(max_length=20, blank=True, default='')   # color hex para gráficos (opcional)
    key        = models.CharField(max_length=120)            # normalize(name) para dedup
    canonical  = models.ForeignKey('self', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='aliases')
    # Descartado por el ejecutivo (extracción errónea): no se ofrece, no cuenta y el
    # clasificador no vuelve a asociarlo aunque el LLM lo extraiga de nuevo.
    ignored    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['kind', 'name']
        verbose_name = 'Etiqueta de actividad'
        verbose_name_plural = 'Etiquetas de actividad'
        constraints = [
            models.UniqueConstraint(fields=['kind', 'key'], name='uniq_tag_kind_key'),
        ]
        indexes = [models.Index(fields=['kind']), models.Index(fields=['canonical'])]

    def __str__(self):
        return f'{self.get_kind_display()}: {self.name}'

    def root(self):
        """Tag canónico: sí mismo si no es alias, o su canonical."""
        return self.canonical or self

    @classmethod
    def resolve(cls, kind, name):
        """get_or_create por (kind, key normalizada) y devuelve el tag canónico."""
        from core.textutils import normalize
        name = (name or '').strip()
        key = normalize(name)[:120]
        if not key:
            return None
        tag, _ = cls.objects.get_or_create(kind=kind, key=key, defaults={'name': name})
        root = tag.root()
        if tag.ignored or root.ignored:
            return None        # descartado por el ejecutivo: no asociar
        return root


class ActivityItem(models.Model):
    """Actividad individual extraída de un DailyReport y clasificada en una categoría."""
    KIND_DONE    = 'done'
    KIND_PLANNED = 'planned'
    KIND_CHOICES = [
        (KIND_DONE,    'Realizada'),
        (KIND_PLANNED, 'Planificada'),
    ]

    # Origen de la categoría asignada.
    SOURCE_KEYWORD = 'keyword'
    SOURCE_LLM     = 'llm'
    SOURCE_CHOICES = [
        (SOURCE_KEYWORD, 'Palabras clave'),
        (SOURCE_LLM,     'LLM'),
    ]

    report   = models.ForeignKey(DailyReport, on_delete=models.CASCADE, related_name='activity_items')
    kind     = models.CharField(max_length=10, choices=KIND_CHOICES)
    position = models.PositiveSmallIntegerField(default=0)
    text     = models.TextField()
    # Guarda el `code` de una ActivityCategory (no es FK: los códigos se usan como
    # llaves en la agregación de estadísticas). Se valida contra la tabla al escribir.
    category = models.CharField(max_length=20, default=OTROS_CODE)
    source   = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_KEYWORD)
    matched_keyword = models.CharField(max_length=60, blank=True, default='')
    # Etiquetas libres extraídas por el LLM (proyecto / ubicación / entregable).
    tags     = models.ManyToManyField(ActivityTag, blank=True, related_name='items')
    manual_override = models.BooleanField(
        default=False,
        help_text='Categoría asignada manualmente; el clasificador no la sobreescribe.',
    )
    classified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['report_id', 'kind', 'position']
        verbose_name = 'Ítem de actividad'
        verbose_name_plural = 'Ítems de actividad'
        constraints = [
            models.UniqueConstraint(
                fields=['report', 'kind', 'position'],
                name='uniq_item_per_report_kind_pos',
            ),
        ]
        indexes = [
            models.Index(fields=['category']),
            models.Index(fields=['kind', 'category']),
        ]

    def __str__(self):
        return f'[{self.category}] {self.text[:50]}'


class ExecutiveMessage(models.Model):
    recipient = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='executive_messages')
    # sender nullable: los avisos automáticos (jornada no cerrada) los genera el bot del
    # sistema "skyBot", sin un ejecutivo en sesión.
    sender = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='sent_messages', null=True, blank=True)
    body = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    day_closed = models.BooleanField(default=False)
    # El empleado descarta (oculta) el mensaje con la ✕ después de confirmarlo (Listo).
    dismissed = models.BooleanField(default=False)

    def __str__(self):
        sender_name = self.sender.full_name if self.sender else 'skyBot'
        return f"Mensaje de {sender_name} a {self.recipient.full_name} — {self.sent_at.strftime('%Y-%m-%d %H:%M')}"

    class Meta:
        ordering = ['-sent_at']
        verbose_name = 'Mensaje ejecutivo'
        verbose_name_plural = 'Mensajes ejecutivos'
        indexes = [models.Index(fields=['recipient', 'acknowledged_at'])]


class CalendarNote(models.Model):
    """Nota global en el calendario (feriado, evento). Visible para todos los empleados."""
    TYPE_FERIADO = 'feriado'
    TYPE_EVENTO  = 'evento'
    TYPE_OTRO    = 'otro'
    TYPE_CHOICES = [
        (TYPE_FERIADO, 'Feriado'),
        (TYPE_EVENTO,  'Evento'),
        (TYPE_OTRO,    'Otro'),
    ]
    date       = models.DateField()
    text       = models.CharField(max_length=200)
    note_type  = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_FERIADO)
    created_by = models.ForeignKey(
        'employees.Employee', on_delete=models.SET_NULL,
        null=True, related_name='calendar_notes',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date']
        verbose_name = 'Nota de calendario'
        verbose_name_plural = 'Notas de calendario'
        indexes = [models.Index(fields=['date'])]

    def __str__(self):
        return f"{self.date} — {self.text}"


class EmployeeLeave(models.Model):
    """Ausencia registrada para un empleado (vacación, licencia, permiso)."""
    TYPE_VACACION = 'vacacion'
    TYPE_LICENCIA = 'licencia'
    TYPE_PERMISO  = 'permiso'
    TYPE_CHOICES  = [
        (TYPE_VACACION, 'Vacación'),
        (TYPE_LICENCIA, 'Licencia'),
        (TYPE_PERMISO,  'Permiso'),
    ]
    employee   = models.ForeignKey(
        'employees.Employee', on_delete=models.CASCADE, related_name='leaves',
    )
    start_date = models.DateField()
    end_date   = models.DateField()
    leave_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    note       = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        'employees.Employee', on_delete=models.SET_NULL,
        null=True, related_name='created_leaves',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_date']
        verbose_name = 'Ausencia'
        verbose_name_plural = 'Ausencias'
        indexes = [models.Index(fields=['employee', 'start_date', 'end_date'])]

    def __str__(self):
        return f"{self.employee.full_name} — {self.leave_type} {self.start_date}→{self.end_date}"
