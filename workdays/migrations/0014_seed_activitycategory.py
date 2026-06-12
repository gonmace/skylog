from django.db import migrations

# Las 11 categorías base. Colores tomados de CAT_COLOR en
# static/dashboard/js/estadisticas-render.js para mantener consistencia visual.
SEED = [
    ('riesgos',     'Análisis de riesgos',                    '#ef4444'),
    ('reuniones',   'Reuniones y coordinación',               '#38bdf8'),
    ('cronogramas', 'Cronogramas y planificación',            '#f59e0b'),
    ('actas',       'Actas y documentos de proyecto',         '#2dd4bf'),
    ('pliegos',     'Pliegos y especificaciones técnicas',    '#a78bfa'),
    ('diseno',      'Diseño e ingeniería',                    '#6366f1'),
    ('supervision', 'Supervisión de obra y campo',            '#34d399'),
    ('informes',    'Informes y reportes',                    '#fb7185'),
    ('seguimiento', 'Seguimiento y control',                  '#94a3b8'),
    ('gestion_doc', 'Gestión documental y administrativa',    '#c084fc'),
    ('otros',       'Otros',                                  '#64748b'),
]


def seed(apps, schema_editor):
    ActivityCategory = apps.get_model('workdays', 'ActivityCategory')
    for order, (code, label, color) in enumerate(SEED):
        ActivityCategory.objects.update_or_create(
            code=code,
            defaults={'label': label, 'color': color, 'order': order,
                      'is_active': True, 'is_protected': True},
        )


def unseed(apps, schema_editor):
    ActivityCategory = apps.get_model('workdays', 'ActivityCategory')
    ActivityCategory.objects.filter(code__in=[c for c, _, _ in SEED]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('workdays', '0013_activitycategory_activityitem_source_and_more'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
