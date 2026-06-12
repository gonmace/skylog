from django.db import migrations

# Nueva categoría base: revisión/validación técnica genérica de proyectos
# (revisión de proyectos en curso, validación de información técnica, etc.).
# Se ubica antes de "Otros". Idempotente: se siembra en cualquier base nueva.
CODE  = 'revision_tecnica'
LABEL = 'Revisión técnica'
COLOR = '#d946ef'   # fuchsia-500, distinto de los colores ya usados


def seed(apps, schema_editor):
    ActivityCategory = apps.get_model('workdays', 'ActivityCategory')
    ActivityCategory.objects.update_or_create(
        code=CODE,
        defaults={'label': LABEL, 'color': COLOR, 'order': 11,
                  'is_active': True, 'is_protected': True},
    )
    # "Otros" siempre al final.
    ActivityCategory.objects.filter(code='otros').update(order=12)


def unseed(apps, schema_editor):
    ActivityCategory = apps.get_model('workdays', 'ActivityCategory')
    ActivityCategory.objects.filter(code=CODE).delete()
    ActivityCategory.objects.filter(code='otros').update(order=11)


class Migration(migrations.Migration):

    dependencies = [
        ('workdays', '0019_seed_adquisiciones_category'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
