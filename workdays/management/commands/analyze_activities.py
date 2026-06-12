"""Analiza (dry-run) o persiste (--commit) la clasificación de actividades.

Sin --commit NO escribe en la base de datos: solo imprime la distribución por
categoría, la matriz rol×categoría, muestras de OTROS, ítems multi-match y los
keywords más frecuentes — para afinar el clasificador antes de persistir.
"""
import datetime as _dt
import random
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand
from django.utils import timezone

from employees.models import Employee
from workdays.models import ActivityItem, DailyReport, ActivityCategory, OTROS_CODE
from workdays.classifier import split_activities, classify, classify_all, sync_report_items

_KIND_FIELD = {
    ActivityItem.KIND_DONE:    'activities_done',
    ActivityItem.KIND_PLANNED: 'activities_planned',
}


class Command(BaseCommand):
    help = 'Analiza (dry-run) o persiste (--commit) la clasificación de actividades.'

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='date_from', help='Fecha inicio YYYY-MM-DD (start_time de la jornada)')
        parser.add_argument('--to', dest='date_to', help='Fecha fin YYYY-MM-DD')
        parser.add_argument('--kind', choices=['done', 'planned', 'both'], default='both',
                            help='Qué actividades analizar (default: both)')
        parser.add_argument('--samples', type=int, default=15, help='Muestras por sección (default: 15)')
        parser.add_argument('--commit', action='store_true', help='Persiste ActivityItem en la DB (idempotente)')

    def handle(self, *args, **opts):
        kinds = [ActivityItem.KIND_DONE, ActivityItem.KIND_PLANNED] if opts['kind'] == 'both' else [opts['kind']]
        samples = opts['samples']

        reports = DailyReport.objects.select_related('workday__employee').order_by('workday__start_time')
        # Excluir empleados que no son supervisores ni PMs (ej. Encargado de Almacén):
        # las estadísticas son sobre Supervisores vs Project Managers.
        excluded_ids = [
            e.id for e in Employee.objects.all()
            if e.role == Employee.ROLE_OTRO
        ]
        reports = reports.exclude(workday__employee_id__in=excluded_ids)
        if opts['date_from']:
            d = _dt.date.fromisoformat(opts['date_from'])
            reports = reports.filter(workday__start_time__gte=timezone.make_aware(_dt.datetime.combine(d, _dt.time.min)))
        if opts['date_to']:
            d = _dt.date.fromisoformat(opts['date_to'])
            reports = reports.filter(workday__start_time__lte=timezone.make_aware(_dt.datetime.combine(d, _dt.time.max)))

        if opts['commit']:
            return self._commit(reports, kinds)

        self._dry_run(reports, kinds, samples)

    # ── Persistencia ────────────────────────────────────────────────────────
    def _commit(self, reports, kinds):
        total_created = total_kept = n_reports = 0
        for report in reports.iterator():
            res = sync_report_items(report, kinds=tuple(kinds))
            total_created += res['created']
            total_kept += res['kept_override']
            n_reports += 1
        self.stdout.write(self.style.SUCCESS(
            f'Persistido: {n_reports} reportes, {total_created} ítems creados, '
            f'{total_kept} overrides preservados.'))

    # ── Análisis (dry-run) ──────────────────────────────────────────────────
    def _dry_run(self, reports, kinds, samples):
        labels = {c.code: c.label for c in ActivityCategory.objects.all()}
        cat_counter = Counter()
        role_cat = defaultdict(Counter)          # role -> Counter(category)
        emp_cat = defaultdict(Counter)           # emp_name -> Counter(category)
        emp_role = {}
        kw_counter = Counter()
        otros_samples = []
        multimatch_samples = []
        n_reports = 0
        n_items = 0

        for report in reports.iterator():
            n_reports += 1
            emp = report.workday.employee
            role = emp.role
            emp_role[emp.full_name] = role
            for kind in kinds:
                for frag in split_activities(getattr(report, _KIND_FIELD[kind])):
                    n_items += 1
                    cat, kw = classify(frag)
                    cat_counter[cat] += 1
                    role_cat[role][cat] += 1
                    emp_cat[emp.full_name][cat] += 1
                    if kw:
                        kw_counter[kw] += 1
                    if cat == OTROS_CODE:
                        otros_samples.append(frag)
                    else:
                        matches = classify_all(frag)
                        if len(matches) >= 2:
                            multimatch_samples.append((frag, matches))

        w = self.stdout.write
        bar = '═' * 64

        # 1. Totales
        w(f'\n{bar}\n  ANÁLISIS DE ACTIVIDADES (dry-run, sin escribir DB)\n{bar}')
        w(f'  Reportes procesados : {n_reports}')
        w(f'  Ítems extraídos     : {n_items}')
        w(f'  Promedio ítems/rep  : {n_items / n_reports:.1f}' if n_reports else '  (sin datos)')
        w(f'  Kinds analizados    : {", ".join(kinds)}')

        # 2. Distribución por categoría
        w(f'\n── Distribución por categoría ──')
        for cat, cnt in cat_counter.most_common():
            pct = 100 * cnt / n_items if n_items else 0
            flag = '  ⚠' if cat == OTROS_CODE and pct > 20 else ''
            w(f'  {labels.get(cat, cat):38s} {cnt:5d}  {pct:5.1f}%{flag}')

        # 3. Matriz rol × categoría
        w(f'\n── Rol × categoría ──')
        cats_order = [c for c, _ in cat_counter.most_common()]
        for role in (Employee.ROLE_SUPERVISOR, Employee.ROLE_PROJECT_MANAGER, Employee.ROLE_OTRO):
            counter = role_cat.get(role)
            if not counter:
                continue
            tot = sum(counter.values())
            w(f'  {Employee.ROLE_LABELS[role]} (total {tot}):')
            for cat in cats_order:
                if counter[cat]:
                    pct = 100 * counter[cat] / tot
                    w(f'      {labels.get(cat, cat):36s} {counter[cat]:4d}  {pct:5.1f}%')

        # 4. Por empleado (top categoría)
        w(f'\n── Por empleado ──')
        for name in sorted(emp_cat):
            counter = emp_cat[name]
            tot = sum(counter.values())
            top_cat, top_cnt = counter.most_common(1)[0]
            w(f'  {name:32s} [{Employee.ROLE_LABELS[emp_role[name]][:12]:12s}] '
              f'{tot:4d} ít.  top: {labels.get(top_cat, top_cat)} ({top_cnt})')

        # 5. Top keywords
        w(f'\n── Top keywords matcheados ──')
        for kw, cnt in kw_counter.most_common(20):
            w(f'  {cnt:5d}  {kw}')

        # 6. Muestras OTROS (objetivo de tuning)
        w(f'\n── Muestras OTROS (sin clasificar) — {len(otros_samples)} total ──')
        for frag in random.sample(otros_samples, min(samples, len(otros_samples))):
            w(f'  · {frag[:90]}')

        # 7. Multi-match (afinar prioridad)
        w(f'\n── Ítems multi-match — {len(multimatch_samples)} total ──')
        for frag, matches in random.sample(multimatch_samples, min(samples, len(multimatch_samples))):
            cats = ' + '.join(f'{labels.get(c, c)}<{kw}>' for c, kw in matches)
            w(f'  · {frag[:60]}')
            w(f'      → {cats}')

        w(f'\n{bar}\n  Sin --commit no se escribió nada. Revisar y afinar workdays/classifier.py\n{bar}\n')
