from django.db import migrations


def complete_names(apps, schema_editor):
    """Completa User.last_name con los apellidos faltantes (tomados de
    Employee.full_name) y deja full_name derivado de nombre + apellidos."""
    Employee = apps.get_model('employees', 'Employee')
    for emp in Employee.objects.select_related('user'):
        user = emp.user
        if not user:
            continue
        parts = emp.full_name.split()
        if not parts:
            continue

        first = user.first_name.strip() or parts[0].title()
        skip = len(first.split())
        last = ' '.join(p.title() for p in parts[skip:]) or user.last_name.strip()

        changed = []
        if user.first_name != first:
            user.first_name = first
            changed.append('first_name')
        if user.last_name != last:
            user.last_name = last
            changed.append('last_name')
        if changed:
            user.save(update_fields=changed)

        full = f'{first} {last}'.strip()
        if full and emp.full_name != full:
            emp.full_name = full
            emp.save(update_fields=['full_name'])


class Migration(migrations.Migration):

    dependencies = [
        ('employees', '0017_mobile_device_id'),
    ]

    operations = [
        migrations.RunPython(complete_names, migrations.RunPython.noop),
    ]
