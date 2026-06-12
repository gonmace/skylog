"""Siembra los proyectos OFICIALES (lista PMP Central) como tags canónicos de
proyecto. Así el clasificador LLM los reutiliza (vía known_tags) y el ejecutivo
puede asociar las variantes extraídas a estos nombres oficiales.

Dry-run por defecto; usar --commit para persistir. Idempotente (por nombre).
Si dos proyectos tienen el MISMO nombre (distinto código), se desambigua el
segundo agregando la regional, ya que los tags deduplican por nombre.
"""
from django.core.management.base import BaseCommand

from core.textutils import normalize
from workdays.models import ActivityTag

REGIONALES = {'LPZ': 'La Paz', 'CBB': 'Cochabamba', 'SCZ': 'Santa Cruz', 'TJA': 'Tarija'}


def regional_of(code):
    for seg in code.split('.'):
        if seg in REGIONALES:
            return REGIONALES[seg]
    return ''


# (código oficial, nombre) — lista PMP Central.
PROJECTS = [
    ('CMT.CBB.ED.0978',     'Taller Central Electromecanico'),
    ('CMT.CBB.MQ.2614A',    'Pozo (Incremento agua cruda)'),
    ('CMT.CBB.MQ.2615',     'Recuperación de Soda Caustica'),
    ('CMT.CBB.MQ.2614B',    'Asfalto (Pavimento Elías Meneses)'),
    ('CMT.LPZ.MQ.2668',     'Tratamiento Efluentes+Montaje'),
    ('CMT.LPZ.MQ.2670',     'Montaje Caldero + piping'),
    ('CMT.LPZ.MQ.2669',     'Subestacion EE LPZ FASE 1'),
    ('CMT.LPZ.ED.0981',     'Módulo liquidación tesorería'),
    ('CMT.LPZ.MQ.2606',     'Montaje de compresor 7 bar'),
    ('CMT.LPZ.MQ.2607',     'Pozo (Incremento agua cruda)'),
    ('CMT.SCZ.MQ.2680',     'Presion positiva'),
    ('CMT.SCZ.MQ.2599',     'Hidrolización Retiro Eq. NH3'),
    ('CMT.TJA.MQ.2740',     'Aux. Montaje de Sistema CIP Fase 3'),
    ('TJA.MQ.2741',         'Restauración integral del compresor de alta presión que alimenta a sopladora de línea OW'),
    ('TJA.MQ.2742',         'Sistema de pre encalado para la planta de agua F1'),
    ('CMT.CBB.MQ.2733',     'Montaje de tanque de jarabe simple y disolutor Fase 2'),
    ('CBB.MQ.2734',         'Actualización del sistema electrónico de la etiquetadora C3-40'),
    ('CMT.CBB.ED.0996',     'Módulo de Servicios'),
    ('CMT.CBB.ED.0995',     'Construcción Nave Gemela Piñami 2'),
    ('CMT.CBB.MQ.2732',     'Montaje de Checkmat K-108 Fase 2'),
    ('CMT.LPZ.MQ.2735',     'Montaje Sub Estación E.E. Fase 2'),
    ('CMT.LPZ.MQ.2736',     'Montaje CIP Central Fase 2'),
    ('CMT.LPZ.MQ.2737',     'Ampliación de Capacidad de Tratamiento de aguas FASE 2'),
    ('CMT.LPZ.MQ.2738',     'Traslado Sopladora Ref. Pet.'),
    ('CMT.LPZ.MQ.2739',     'Implementación Sistema de enfriamiento para jarabe simple'),
    ('CMT.LPZ.MQ.2747',     'Ampliación Capacidad LPZ K140 C380'),
    ('CMT.SCZ.ED.0994',     'Construcción de cámaras refrigeradas para concentrados'),
    ('CMT.SCZ.ED.0993',     'Rehabilitación de pisos en Picking predio PI06'),
    ('CMT.SCZ.MQ.2695',     'Sopladora REF PET'),
    ('SCZ.MQ.2745',         'Reposición de compresor de aire de baja presión'),
    ('SCZ.MQ.2746',         'Actualización del sistema electrónico de la llenadora Sidel'),
    ('SCZ.MQ.2744',         'Automatización portón PI51'),
    ('SCZ.MQ.2743',         'Automatización portón norte PI06'),
    ('OPX.CBB.ED.PISOP4',   'Habilitacion Piñami 4'),
    ('OPX.CBB.ED.PISOAMP3', 'Reposicion Pisos Piñami 3'),
    ('CMT.CBB.ED.0991',     'Ampliacion piso Piñami 1 (280M2)'),
    ('OPX.SCZ.ED.ROFCOM',   'Remodelación de oficinas OFCOM'),
    ('OPX.CBB.ED.SEDE',     'Sede sindical'),
    ('OPX.SCZ.ED.EPI51',    'Enlosetado PI51'),
    ('OPX.CBB.ED.CDSACABA', 'CD Sacaba'),
    ('OPX.SCZ.ED.CDSUR',    'CD SUR'),
    ('CMT.SCZ.MQ.2751',     'Proyecto Vital 3L K128A'),
    ('CMT.SCZ.MQ.2752',     'Proyecto Del Valle Frut 2L S135'),
    ('CMT.SCZ.MQ.2753',     'Proyecto 1500OW CC S135'),
    ('CMT.SCZ.MQ.2748',     'Proyecto 1500OW SABORES S135'),
    ('CMT.SCZ.MQ.2749',     'Proyecto 1000OW K128A SABORES'),
    ('CMT.CBB.MQ.2339',     'CBB MQ CBB - Nuevo CIP + cambio tuberias'),
    ('CMT.SCZ.MQ.2277',     'SCZ MQ proyecto KOMMIT'),
    ('CMT.TJA.ED.0947',     'TJA ED techo de carga y descarga de PT'),
    ('CMT.TJA.ED.0942',     'TJA ED Pisos Parqueo de Camiones'),
    ('CMT.SCZ.ED.0977',     'CMT SCZ ED Muro Perimetral El Mundo'),
    ('CMT.LPZ.MQ.2453',     'CMT LPZ MQ Proy. Continew'),
    ('CMT.LPZ.MQ.2754',     'Efluentes +PEM'),
    ('CMT.LPZ.MQ.2750',     'Aducción Agua pozo #6'),
]


class Command(BaseCommand):
    help = 'Siembra los proyectos oficiales (PMP Central) como tags canónicos de proyecto.'

    def add_arguments(self, parser):
        parser.add_argument('--commit', action='store_true',
                            help='Persiste en la DB. Sin esto, solo muestra qué haría (dry-run).')

    def handle(self, *args, **opts):
        commit = opts['commit']
        created = updated = 0
        seen = {}  # key -> code (para desambiguar nombres repetidos)
        for code, name in PROJECTS:
            name = name.strip()
            key = normalize(name)[:120]
            if seen.get(key, code) != code:
                reg = regional_of(code)
                if reg:
                    name = f'{name} ({reg})'
                    key = normalize(name)[:120]
            seen[key] = code

            tag = ActivityTag.objects.filter(kind='project', key=key).first()
            if tag:
                action = 'update'
                if commit:
                    tag.name = name
                    tag.code = code
                    tag.ignored = False
                    tag.save(update_fields=['name', 'code', 'ignored'])
                updated += 1
            else:
                action = 'create'
                if commit:
                    ActivityTag.objects.create(kind='project', name=name, code=code, key=key)
                created += 1
            self.stdout.write(f'  [{action}] {code:18s} {name}')

        msg = f'\n{len(PROJECTS)} proyectos · crear {created} · actualizar {updated}'
        if commit:
            self.stdout.write(self.style.SUCCESS(msg + '  → PERSISTIDO'))
        else:
            self.stdout.write(self.style.WARNING(msg + '  → DRY-RUN (usar --commit para persistir)'))
