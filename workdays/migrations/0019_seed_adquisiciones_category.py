from django.db import migrations

# Nueva categoría base: agrupa requerimientos de servicio (RS), validaciones de PR,
# cotizaciones, órdenes de compra y gestión de adquisiciones en general. Se ubica
# antes de "Otros". Idempotente: se siembra en cualquier base nueva.
CODE  = 'adquisiciones'
LABEL = 'Adquisiciones y requerimientos'
COLOR = '#f97316'   # orange-500, distinto de los colores ya usados


def seed(apps, schema_editor):
    ActivityCategory = apps.get_model('workdays', 'ActivityCategory')
    ActivityCategory.objects.update_or_create(
        code=CODE,
        defaults={'label': LABEL, 'color': COLOR, 'order': 10,
                  'is_active': True, 'is_protected': True},
    )
    # "Otros" siempre al final.
    ActivityCategory.objects.filter(code='otros').update(order=11)


def unseed(apps, schema_editor):
    ActivityCategory = apps.get_model('workdays', 'ActivityCategory')
    ActivityCategory.objects.filter(code=CODE).delete()
    ActivityCategory.objects.filter(code='otros').update(order=10)


class Migration(migrations.Migration):

    dependencies = [
        ('workdays', '0018_activitytag_color'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
