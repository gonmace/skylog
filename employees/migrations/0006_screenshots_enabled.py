from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('employees', '0005_agent_version'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='screenshots_enabled',
            field=models.BooleanField(
                default=True,
                verbose_name='Capturas habilitadas',
                help_text='Deshabilitar impide que el agente envíe capturas de pantalla para este empleado.',
            ),
        ),
    ]
