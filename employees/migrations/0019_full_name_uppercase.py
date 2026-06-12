from django.db import migrations


def uppercase_full_names(apps, schema_editor):
    Employee = apps.get_model('employees', 'Employee')
    for emp in Employee.objects.all():
        upper = emp.full_name.upper()
        if emp.full_name != upper:
            emp.full_name = upper
            emp.save(update_fields=['full_name'])


class Migration(migrations.Migration):

    dependencies = [
        ('employees', '0018_complete_apellidos'),
    ]

    operations = [
        migrations.RunPython(uppercase_full_names, migrations.RunPython.noop),
    ]
