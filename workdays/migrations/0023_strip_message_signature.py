# Limpieza de datos: el envío a Sup/PM pegaba la firma "— NOMBRE" dentro del
# cuerpo del mensaje; ahora el banner la renderiza al pie, así que los mensajes
# antiguos se veían con firma doble. Recorta la firma del final del cuerpo en
# los mensajes enviados por GONZALO MARTINEZ (único emisor afectado).

from django.db import migrations

SENDER_NAME = 'GONZALO MARTINEZ'


def strip_signature(apps, schema_editor):
    ExecutiveMessage = apps.get_model('workdays', 'ExecutiveMessage')
    sig = f'\n\n— {SENDER_NAME}'
    for msg in ExecutiveMessage.objects.filter(sender__full_name=SENDER_NAME, body__endswith=sig):
        msg.body = msg.body[: -len(sig)]
        msg.save(update_fields=['body'])


def restore_signature(apps, schema_editor):
    # No se restaura la firma: la limpieza es intencional y el render nuevo la
    # muestra al pie de todos modos.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('workdays', '0022_alter_employeeleave_leave_type'),
    ]

    operations = [
        migrations.RunPython(strip_signature, restore_signature),
    ]
