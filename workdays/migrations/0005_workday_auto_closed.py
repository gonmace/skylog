from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('workdays', '0004_executivemessage'),
    ]
    operations = [
        migrations.AddField(
            model_name='workday',
            name='auto_closed',
            field=models.BooleanField(default=False),
        ),
    ]
