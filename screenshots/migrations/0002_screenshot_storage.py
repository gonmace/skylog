from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('screenshots', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='screenshot',
            name='storage',
            field=models.CharField(
                choices=[('local', 'Local'), ('nextcloud', 'Nextcloud')],
                default='local',
                max_length=20,
            ),
        ),
    ]
