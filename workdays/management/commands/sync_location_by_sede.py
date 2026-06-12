"""Setea la UBICACIÓN de cada actividad 'done' = SEDE del empleado que reportó
(employee.ciudad: SCZ/LPZ/CBA/TJA), reemplazando las ubicaciones que había extraído
el LLM del texto. Así un empleado de SCZ que reportó trabajo en La Paz queda con
ubicación = SCZ.

Dry-run por defecto; --commit para aplicar. Idempotente.
"""
from collections import Counter

from django.core.management.base import BaseCommand

from workdays.models import ActivityItem, ActivityTag, SEDE_NAMES

VALID = set(SEDE_NAMES)


class Command(BaseCommand):
    help = "Ubicación de cada 'done' = sede del empleado (employee.ciudad)."

    def add_arguments(self, parser):
        parser.add_argument('--commit', action='store_true', help='Aplica (sin esto, dry-run).')

    def handle(self, *args, **opts):
        commit = opts['commit']
        sede_tag = {}
        stats = Counter()
        items = (ActivityItem.objects.filter(kind='done')
                 .select_related('report__workday__employee'))
        n = 0
        for item in items.iterator():
            sede = (item.report.workday.employee.ciudad or '').strip().upper()
            if sede not in VALID:
                stats['sin_sede'] += 1
                continue
            stats[sede] += 1
            n += 1
            if commit:
                if sede not in sede_tag:
                    sede_tag[sede] = ActivityTag.resolve(
                        ActivityTag.KIND_LOCATION, SEDE_NAMES.get(sede, sede))
                loc = sede_tag[sede]
                cur = list(item.tags.filter(kind=ActivityTag.KIND_LOCATION))
                if cur:
                    item.tags.remove(*cur)
                if loc:
                    item.tags.add(loc)

        self.stdout.write(f'  done con sede asignable: {n}')
        self.stdout.write(f'  distribución: {dict(stats)}')
        if commit:
            self.stdout.write(self.style.SUCCESS('  → APLICADO'))
        else:
            self.stdout.write(self.style.WARNING('  → DRY-RUN (usar --commit para aplicar)'))
