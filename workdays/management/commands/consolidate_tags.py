"""Consolida automáticamente las variantes de tags por similitud de nombre.

Dos pasadas (conservadoras):
  1) Cada variante (sin código) se asocia al PROYECTO OFICIAL (con código) más
     parecido, si la similitud supera el umbral.
  2) Las variantes restantes muy parecidas entre sí se agrupan en la de más ítems.

Dry-run por defecto; --commit para aplicar. Es heurístico: revisar el plan y,
si algo quedó mal, desagrupar desde /etiquetas/.
"""
import difflib
import re
from django.core.management.base import BaseCommand

from core.textutils import normalize
from workdays.models import ActivityTag

STOP = {'de', 'del', 'la', 'el', 'los', 'las', 'y', 'para', 'en', 'con',
        'un', 'una', 'proyecto', 'proyectos', 'proy', 'a', 'al'}
# Tokens demasiado genéricos: una variante formada SOLO por estos no se fusiona.
GENERIC = {'pozo', 'modulo', 'sistema', 'planta', 'obra', 'area', 'nacional',
           'varios', 'otros', 'fase', 'montaje', 'ampliacion', 'subestacion'}


def toks(s):
    return {w for w in normalize(s).split() if w not in STOP and len(w) > 1}


def nums(s):
    return set(re.findall(r'\d+', s))


def too_generic(name):
    ts = toks(name)
    return (not ts) or ts <= GENERIC


def sim(a, b):
    # Guard de números: si ambos nombres tienen dígitos y NO coinciden, son
    # proyectos distintos (Piñami 2 vs 3, pozo 8 vs 9, Fase 1 vs 2) → no fusionar.
    na_, nb_ = nums(a), nums(b)
    if na_ and nb_ and na_ != nb_:
        return 0.0
    na, nb = normalize(a), normalize(b)
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    ta, tb = toks(a), toks(b)
    jac = (len(ta & tb) / len(ta | tb)) if (ta | tb) else 0.0
    return max(ratio, jac)


class Command(BaseCommand):
    help = 'Consolida variantes de tags por similitud (hacia oficiales y entre duplicados).'

    def add_arguments(self, parser):
        parser.add_argument('--kind', default='project', help='project | location | deliverable')
        parser.add_argument('--to-official', type=float, default=0.66,
                            help='Umbral para asociar variante → oficial (default 0.66).')
        parser.add_argument('--dedupe', type=float, default=0.86,
                            help='Umbral para agrupar variantes entre sí (default 0.86).')
        parser.add_argument('--commit', action='store_true', help='Aplica (sin esto, dry-run).')

    def handle(self, *args, **o):
        kind, th_off, th_dup, commit = o['kind'], o['to_official'], o['dedupe'], o['commit']
        tags = list(ActivityTag.objects.filter(kind=kind, canonical__isnull=True, ignored=False))
        cnt = {t.id: t.items.count() for t in tags}
        officials = [t for t in tags if t.code]
        variants = [t for t in tags if not t.code]

        plan = []          # (variant, target, score, motivo)
        consumed = set()   # ids ya planificados para mover

        # Pasada 1: variante → oficial más parecido.
        for v in variants:
            if too_generic(v.name):
                continue
            best, bs = None, 0.0
            for t in officials:
                if not (toks(v.name) & toks(t.name)):   # debe compartir un token significativo
                    continue
                s = sim(v.name, t.name)
                if s > bs:
                    bs, best = s, t
            if best and bs >= th_off:
                plan.append((v, best, bs, 'oficial'))
                consumed.add(v.id)

        # Pasada 2: variantes restantes muy parecidas entre sí → la de más ítems.
        rest = [v for v in variants if v.id not in consumed]
        rest.sort(key=lambda t: (-cnt.get(t.id, 0), t.name.lower()))
        for i, v in enumerate(rest):
            if v.id in consumed or too_generic(v.name):
                continue
            for w in rest[:i]:                       # comparar con anclas (más ítems)
                if w.id in consumed or not (toks(v.name) & toks(w.name)):
                    continue
                if sim(v.name, w.name) >= th_dup:
                    plan.append((v, w, sim(v.name, w.name), 'duplicado'))
                    consumed.add(v.id)
                    break

        # Reporte
        plan.sort(key=lambda x: (x[3], -x[2]))
        for v, t, s, motivo in plan:
            tgt = f'{t.name}' + (f' [{t.code}]' if t.code else '')
            self.stdout.write(f'  {motivo:9s} {s:.2f}  «{v.name}»  →  «{tgt}»')
            if commit:
                v.canonical = t
                v.save(update_fields=['canonical'])

        n_off = sum(1 for p in plan if p[3] == 'oficial')
        n_dup = sum(1 for p in plan if p[3] == 'duplicado')
        msg = (f'\n{kind}: {len(variants)} variantes · {n_off} → oficial · '
               f'{n_dup} → duplicado · {len(variants) - len(plan)} sin tocar')
        if commit:
            self.stdout.write(self.style.SUCCESS(msg + '  → APLICADO'))
        else:
            self.stdout.write(self.style.WARNING(msg + '  → DRY-RUN (usar --commit para aplicar)'))
