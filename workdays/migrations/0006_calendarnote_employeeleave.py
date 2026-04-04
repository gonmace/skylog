from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('employees', '0001_initial'),
        ('workdays', '0005_workday_auto_closed'),
    ]
    operations = [
        migrations.CreateModel(
            name='CalendarNote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('text', models.CharField(max_length=200)),
                ('note_type', models.CharField(choices=[('feriado', 'Feriado'), ('evento', 'Evento'), ('otro', 'Otro')], default='feriado', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='calendar_notes', to='employees.employee')),
            ],
            options={'verbose_name': 'Nota de calendario', 'verbose_name_plural': 'Notas de calendario', 'ordering': ['date']},
        ),
        migrations.AddIndex(
            model_name='calendarnote',
            index=models.Index(fields=['date'], name='workdays_ca_date_idx'),
        ),
        migrations.CreateModel(
            name='EmployeeLeave',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_date', models.DateField()),
                ('end_date', models.DateField()),
                ('leave_type', models.CharField(choices=[('vacacion', 'Vacación'), ('licencia', 'Licencia'), ('permiso', 'Permiso')], max_length=20)),
                ('note', models.CharField(blank=True, max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_leaves', to='employees.employee')),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='leaves', to='employees.employee')),
            ],
            options={'verbose_name': 'Ausencia', 'verbose_name_plural': 'Ausencias', 'ordering': ['-start_date']},
        ),
        migrations.AddIndex(
            model_name='employeeleave',
            index=models.Index(fields=['employee', 'start_date', 'end_date'], name='workdays_em_emp_dates_idx'),
        ),
    ]
