from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0002_agentactivationtoken'),
    ]

    operations = [
        migrations.AddField(
            model_name='agentregistration',
            name='jwt_refresh',
            field=models.TextField(blank=True),
        ),
    ]
