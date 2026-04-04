from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('employees', '0008_agent_online'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='is_mobile',
            field=models.BooleanField(default=False, verbose_name='Usuario móvil'),
        ),
    ]
