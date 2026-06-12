"""Clasificador de actividades por palabras clave.

Divide el texto libre de un DailyReport en ítems individuales y asigna a cada
uno una ActivityCategory mediante un mapa de stems normalizados (sin acentos,
tolerante a typos). Etiqueta única por ítem (first-match en orden de prioridad).
"""
import re

from django.db import transaction

from core.textutils import normalize
from .models import OTROS_CODE, ActivityItem


# ── División de texto en ítems ──────────────────────────────────────────────
# Separadores intra-línea: | ; * • y bullets.
_INTRA_SEP = re.compile(r'[|;*•·]+')
# Prefijos de enumeración a remover: "1.-", "2)", "3.", "- ", "• "
_ENUM_PREFIX = re.compile(r'^\s*(?:\d{1,2}\s*[.\-)]+|[-–—•·])\s*')

_MIN_LEN = 4


def split_activities(raw):
    """Divide texto libre en una lista de ítems de actividad limpios."""
    items = []
    for line in (raw or '').splitlines():
        for frag in _INTRA_SEP.split(line):
            frag = _ENUM_PREFIX.sub('', frag).strip()
            # Un segundo pase por si quedó "1.- 2.-" pegado tras el split.
            frag = _ENUM_PREFIX.sub('', frag).strip()
            if len(frag) >= _MIN_LEN:
                items.append(frag)
    return items


# ── Mapa de palabras clave (orden = prioridad, más específico primero) ───────
# Cada stem se compila como substring de texto normalizado. Usar \b para
# abreviaturas cortas que generarían falsos positivos.
# Las keys son `code` de ActivityCategory (las built-in seedeadas por migration).
# Categorías nuevas creadas en el admin no tienen keywords: solo el LLM las asigna.
_KEYWORD_MAP_RAW = [
    ('riesgos', [
        r'riesg', r'\briegos\b', r'riezg', r'reisg',  # typos comunes de "riesgos"
    ]),
    ('reuniones', [
        r'reuni', r'c?oordin', r'cordin', r'\bjunta', r'comite', r'\bllamada',
        r'videollamada', r'capacitacion', r'\bcomite',
    ]),
    ('cronogramas', [
        r'cronogram', r'planificacion', r'programacion', r'\bgantt', r'\bhito',
        r'plan de trabajo', r'plan maestro', r'planes de trabajo',
    ]),
    ('actas', [
        r'\bactas?\b', r'constitucion', r'kick\s*off', r'recepcion definitiva',
        r'acta de entrega', r'acta de recepcion',
    ]),
    ('pliegos', [
        r'pliego', r'especificacion tecnic', r'especificaciones tecnic',
        r'\betp\b', r'memoria tecnica',
    ]),
    ('diseno', [
        r'plano', r'disen', r'diesn', r'ingenier', r'ingener', r'calculo',
        r'piping', r'isometric', r'autocad', r'\brevit', r'\bcad\b', r'memoria de calculo',
        r'diagrama', r'tablero', r'\bbim\b', r'\bp&id\b', r'\b3d\b',
        r'\brs-?\d', r'isometr', r'cuadro de computo',
    ]),
    ('supervision', [
        r'superv', r'\bobra\b', r'\bcampo\b', r'visita', r'relevamiento',
        r'inspeccion', r'fiscaliz', r'\btaller', r'\bconst\b', r'construccion',
        r'replanteo', r'montaje', r'instalacion', r'recorrido', r'\bplanta\b',
    ]),
    ('informes', [
        r'\binforme', r'report', r'presentacion', r'estados? de situacion', r'\bres\b',
    ]),
    ('adquisiciones', [
        r'adquisicion', r'requerimiento de servicio', r'requerimiento', r'requisicion',
        r'\bpr\b', r'\bprs\b', r'\bpr\d', r'orden de compra', r'\boc\b', r'\bcompra',
        r'cotizacion', r'proveedor', r'licitacion', r'abastecimiento', r'contrat',
        r'precio unitario', r'\bpu\b', r'validacion tecnic', r'boletas? de garantia',
        r'\brs\b', r'listado de material', r'solicitud de loto',  # RS suelto (no numerado)
    ]),
    ('seguimiento', [
        r'seguim', r'\bcontrol', r'plan de accion', r'action log', r'monitoreo',
    ]),
    ('gestion_doc', [
        r'document', r'ducument', r'documenacion', r'carpeta', r'sharepoint',
        r'archivo', r'expediente', r'administrativ', r'correo', r'\bmail\b',
        r'respaldo', r'backup', r'bandeja de entrada', r'planilla',
    ]),
    # Última prioridad: revisión/validación técnica genérica de proyectos, lo que
    # antes caía en "otros" por no matchear ninguna categoría específica.
    ('revision_tecnica', [
        r'informacion tecnica', r'revision de proyecto', r'revision proyecto',
        r'revision tecnica', r'revision de la informacion',
    ]),
]


def _compile(stems):
    return [re.compile(s) for s in stems]


_KEYWORD_MAP = [(cat, _compile(stems)) for cat, stems in _KEYWORD_MAP_RAW]


def classify(text):
    """Devuelve (category, matched_keyword) — first-match por prioridad."""
    norm = normalize(text)
    for cat, patterns in _KEYWORD_MAP:
        for pat in patterns:
            if pat.search(norm):
                return cat, pat.pattern
    return OTROS_CODE, ''


def classify_all(text):
    """Devuelve [(category, matched_keyword), ...] con TODOS los matches.

    Solo para el reporte de ambigüedad del comando de análisis.
    """
    norm = normalize(text)
    out = []
    for cat, patterns in _KEYWORD_MAP:
        for pat in patterns:
            if pat.search(norm):
                out.append((cat, pat.pattern))
                break  # un match por categoría basta
    return out


@transaction.atomic
def sync_report_items(report, kinds=(ActivityItem.KIND_DONE, ActivityItem.KIND_PLANNED)):
    """Persiste idempotentemente los ActivityItem de un DailyReport.

    Respeta ítems con manual_override=True: no los borra ni recategoriza.
    Para los demás, reemplaza el conjunto completo por kind.
    Devuelve dict con conteos {created, kept_override}.
    """
    field_for_kind = {
        ActivityItem.KIND_DONE:    report.activities_done,
        ActivityItem.KIND_PLANNED: report.activities_planned,
    }

    created = 0
    kept_override = 0

    for kind in kinds:
        existing = list(report.activity_items.filter(kind=kind))
        overrides = [it for it in existing if it.manual_override]
        kept_override += len(overrides)
        # Borrar solo los no-override.
        report.activity_items.filter(kind=kind, manual_override=False).delete()

        # Posiciones ya ocupadas por overrides (para no chocar el UniqueConstraint).
        taken = {it.position for it in overrides}
        override_texts = {normalize(it.text) for it in overrides}

        new_items = []
        pos = 0
        for frag in split_activities(field_for_kind[kind]):
            if normalize(frag) in override_texts:
                continue  # ya existe como override, no duplicar
            while pos in taken:
                pos += 1
            cat, kw = classify(frag)
            new_items.append(ActivityItem(
                report=report, kind=kind, position=pos,
                text=frag, category=cat, matched_keyword=kw,
            ))
            pos += 1

        ActivityItem.objects.bulk_create(new_items)
        created += len(new_items)

    return {'created': created, 'kept_override': kept_override}
