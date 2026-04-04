from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('employees', '0009_employee_is_mobile'),
        ('workdays', '0006_calendarnote_employeeleave'),
    ]

    operations = [
        migrations.AddField(
            model_name='workday',
            name='start_latitude',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
        ),
        migrations.AddField(
            model_name='workday',
            name='start_longitude',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
        ),
        migrations.AddField(
            model_name='workday',
            name='end_latitude',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
        ),
        migrations.AddField(
            model_name='workday',
            name='end_longitude',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
        ),
    ]
