"""Reclasifica determinísticamente los ActivityItem que están en `otros`.

Útil tras agregar categorías nuevas (p.ej. `adquisiciones`) sin re-correr n8n:
el clasificador por palabras clave rescata del cajón `otros` los ítems que ahora
sí matchean una categoría. No toca ítems ya clasificados (no-otros) ni los
`manual_override`. Por defecto es dry-run; usar --commit para aplicar.
"""
from collections import Counter

from django.core.management.base import BaseCommand

from workdays.models import ActivityItem, OTROS_CODE
from workdays.classifier import classify


class Command(BaseCommand):
    help = 'Reclasifica por método determinístico los ítems en categoría "otros".'

    def add_arguments(self, parser):
        parser.add_argument('--commit', action='store_true',
                            help='Aplica los cambios (sin esto solo muestra el preview).')
        parser.add_argument('--kind', choices=['done', 'planned'], default=None,
                            help='Limitar a un kind (por defecto ambos).')

    def handle(self, *args, **opts):
        qs = ActivityItem.objects.filter(category=OTROS_CODE, manual_override=False)
        if opts['kind']:
            qs = qs.filter(kind=opts['kind'])
        qs = qs.select_related('report__workday__employee')

        moves, changed = Counter(), []
        for it in qs:
            cat, kw = classify(it.text)
            if cat != OTROS_CODE:
                moves[cat] += 1
                changed.append((it, cat, kw))

        total = qs.count()
        self.stdout.write(f'Ítems en otros (sin override): {total}')
        self.stdout.write(f'Reclasificables: {len(changed)}  ->  quedan en otros: {total - len(changed)}')
        for cat, n in moves.most_common():
            self.stdout.write(f'  {n:3}  -> {cat}')

        # Muestra de los movimientos
        self.stdout.write('\nDetalle:')
        for it, cat, kw in changed:
            emp = it.report.workday.employee.full_name[:18]
            self.stdout.write(f'  [{cat:13}] ({kw}) {emp:18} | {it.text.strip()[:70]}')

        if not opts['commit']:
            self.stdout.write(self.style.WARNING('\nDRY-RUN. Re-ejecutar con --commit para aplicar.'))
            return

        for it, cat, kw in changed:
            it.category = cat
            it.source = ActivityItem.SOURCE_KEYWORD
            it.matched_keyword = kw
            it.save(update_fields=['category', 'source', 'matched_keyword'])
        self.stdout.write(self.style.SUCCESS(f'\nAplicado: {len(changed)} ítems reclasificados.'))
