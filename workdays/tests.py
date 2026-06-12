from datetime import timedelta

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from django.contrib.auth.models import User
from rest_framework.test import APIRequestFactory, force_authenticate

from employees.models import Employee
from workdays.models import Workday, DailyReport, ActivityItem, ActivityCategory, ActivityTag
from workdays.classifier import split_activities, classify, sync_report_items
from workdays.views import (
    EstadisticasAPIView, DoneActivitiesView, ClassifyDoneView,
    TagsListView, TagMergeView, TagIgnoreView, TagUnmergeView,
)


class SplitActivitiesTests(SimpleTestCase):
    def test_newlines(self):
        self.assertEqual(split_activities('Primero\nSegundo\nTercero'), ['Primero', 'Segundo', 'Tercero'])

    def test_pipe_and_semicolon(self):
        self.assertEqual(split_activities('Reunion | Planos ; Informe'), ['Reunion', 'Planos', 'Informe'])

    def test_asterisk_bullets(self):
        self.assertEqual(split_activities('*Reunion *Planos'), ['Reunion', 'Planos'])

    def test_numbered_prefixes(self):
        self.assertEqual(
            split_activities('1.-Reunión | 2.-Informe | 3.- Cronograma'),
            ['Reunión', 'Informe', 'Cronograma'],
        )

    def test_short_fragments_dropped(self):
        # Fragmentos de menos de 4 chars se descartan.
        self.assertEqual(split_activities('ok | a | reunion | xy'), ['reunion'])


class ClassifyTests(SimpleTestCase):
    CASES = [
        ('Reunión semanal revisión técnica',                 'reuniones'),
        ('cordinacion para ejecucion de proyectos',          'reuniones'),
        ('Supervision de la const del taller',               'supervision'),
        ('visita en campo revision de proyecto',             'supervision'),
        ('Actualización de cronogramas',                     'cronogramas'),
        ('Elaboración de plan de trabajo CD Sur',            'cronogramas'),
        ('Seguimiento a PR y Contratos',                     'adquisiciones'),
        ('Cotización de proveedor para orden de compra',     'adquisiciones'),
        ('requerimiento de servicio para adquisicion',       'adquisiciones'),
        ('seguimiento y control del plan de accion',         'seguimiento'),
        ('entrega de RS de prospeccion',                     'adquisiciones'),
        ('Listado de material eléctrico para el pozo',       'adquisiciones'),
        ('estados de situación de proyectos',                'informes'),
        ('revision de proyectos en curso',                   'revision_tecnica'),
        ('Validacion informacion tecnica de plastiforte',    'revision_tecnica'),
        ('análisis de riesgos del proyecto',                 'riesgos'),
        ('carpetas de proyectos en Sharepoint',              'gestion_doc'),
        ('Emisión de reporte ejecutivo semanal',             'informes'),
        ('Realizando planos de detalle de piping',           'diseno'),
        ('ingeneria conceptual TSPP',                        'diseno'),  # typo
        ('diesño transporte de pallets',                     'diseno'),  # typo
        ('Verificacion calculo columna',                     'diseno'),
        ('pliego de especificaciones técnicas',              'pliegos'),
        ('REV-01 corrección de pliego de especificación técnica', 'pliegos'),
        ('actas de constitución de proyectos',               'actas'),
        ('acta de recepción definitiva del proyecto',        'actas'),
        ('conclusión de actas re kick off',                  'actas'),
        ('xyz frase sin keywords zzz',                       'otros'),
    ]

    def test_classify_cases(self):
        for text, expected in self.CASES:
            cat, _kw = classify(text)
            self.assertEqual(cat, expected, msg=f'{text!r} → {cat} (esperado {expected})')


class EmployeeRoleTests(TestCase):
    CARGOS = [
        ('Supervisor Civil Regional LPZ',  Employee.ROLE_SUPERVISOR),
        ('Supervisor Eléctrico Regional',  Employee.ROLE_SUPERVISOR),
        ('Project Manager Regional CBA',   Employee.ROLE_PROJECT_MANAGER),
        ('Project Manager Central',        Employee.ROLE_PROJECT_MANAGER),
        ('Encargado de Almacén',           Employee.ROLE_OTRO),
    ]

    def _emp(self, cargo, idx):
        u = User.objects.create(username=f'u{idx}')
        return Employee.objects.create(user=u, nextcloud_username=f'nc{idx}', full_name=f'E {idx}', cargo=cargo)

    def test_role_derivation(self):
        for i, (cargo, expected) in enumerate(self.CARGOS):
            emp = self._emp(cargo, i)
            self.assertEqual(emp.role, expected, msg=f'{cargo!r} → {emp.role}')


class SyncReportItemsTests(TestCase):
    def setUp(self):
        u = User.objects.create(username='sup')
        self.emp = Employee.objects.create(user=u, nextcloud_username='sup', full_name='SUP', cargo='Supervisor X')
        wd = Workday.objects.create(employee=self.emp, start_time=timezone.now(), status=Workday.STATUS_COMPLETED)
        self.report = DailyReport.objects.create(
            workday=wd,
            activities_done='Reunión semanal | Planos de detalle | análisis de riesgos',
            activities_planned='Cronograma del proyecto',
        )

    def test_creates_items(self):
        sync_report_items(self.report)
        done = self.report.activity_items.filter(kind=ActivityItem.KIND_DONE)
        self.assertEqual(done.count(), 3)
        cats = set(done.values_list('category', flat=True))
        self.assertEqual(cats, {'reuniones', 'diseno', 'riesgos'})

    def test_idempotent(self):
        sync_report_items(self.report)
        n1 = self.report.activity_items.count()
        sync_report_items(self.report)
        self.assertEqual(self.report.activity_items.count(), n1)

    def test_manual_override_preserved(self):
        sync_report_items(self.report)
        item = self.report.activity_items.filter(kind=ActivityItem.KIND_DONE).first()
        item.category = 'otros'
        item.manual_override = True
        item.save()
        sync_report_items(self.report)
        item.refresh_from_db()
        self.assertEqual(item.category, 'otros')
        self.assertTrue(item.manual_override)


class EstadisticasAPITests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        eu = User.objects.create(username='exec')
        self.exec_emp = Employee.objects.create(user=eu, nextcloud_username='exec', full_name='EXEC', is_executive=True)
        nu = User.objects.create(username='noexec')
        self.noexec = Employee.objects.create(user=nu, nextcloud_username='noexec', full_name='NOEXEC', cargo='Supervisor Y')

    def test_forbidden_for_non_executive(self):
        req = self.factory.get('/api/estadisticas/')
        force_authenticate(req, user=self.noexec.user)
        resp = EstadisticasAPIView.as_view()(req)
        self.assertEqual(resp.status_code, 403)

    def test_shape_for_executive(self):
        req = self.factory.get('/api/estadisticas/', {'mode': 'month'})
        force_authenticate(req, user=self.exec_emp.user)
        resp = EstadisticasAPIView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        for key in ('label', 'kind', 'total_items', 'categories', 'by_role', 'monthly', 'employees'):
            self.assertIn(key, resp.data)
        # La API sirve labels y colores dinámicos de las categorías.
        self.assertIn('category_labels', resp.data)
        self.assertIn('category_colors', resp.data)


@override_settings(INTERNAL_API_TOKEN='secret-token')
class InternalClassifyEndpointsTests(TestCase):
    """Endpoints internos para el cron LLM de n8n (done-activities / classify-done)."""

    def setUp(self):
        self.factory = APIRequestFactory()
        u = User.objects.create(username='emp1')
        self.emp = Employee.objects.create(
            user=u, nextcloud_username='emp1', full_name='EMP', cargo='Supervisor Z',
            ciudad='CBA')  # la location se deriva de la sede del empleado, no del LLM
        self.wd = Workday.objects.create(
            employee=self.emp, start_time=timezone.now(), status=Workday.STATUS_COMPLETED)
        self.report = DailyReport.objects.create(
            workday=self.wd,
            activities_done='Reunión semanal | Planos de detalle',
            activities_planned='Cronograma del proyecto',
        )
        sync_report_items(self.report)
        self.day = timezone.localtime(self.wd.start_time).date().isoformat()

    def test_done_activities_requires_token(self):
        req = self.factory.get('/api/internal/done-activities/')
        resp = DoneActivitiesView.as_view()(req)
        self.assertIn(resp.status_code, (401, 403))

    def test_done_activities_returns_items_and_dynamic_categories(self):
        req = self.factory.get('/api/internal/done-activities/', {'date': self.day},
                               HTTP_X_INTERNAL_TOKEN='secret-token')
        resp = DoneActivitiesView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['date'], self.day)
        self.assertTrue(any(c['code'] == 'diseno' for c in resp.data['categories']))
        self.assertEqual(len(resp.data['employees']), 1)
        self.assertEqual(len(resp.data['employees'][0]['items']), 2)

    def test_done_activities_includes_new_admin_category(self):
        ActivityCategory.objects.create(code='nueva', label='Categoría nueva', order=99)
        req = self.factory.get('/api/internal/done-activities/', {'date': self.day},
                               HTTP_X_INTERNAL_TOKEN='secret-token')
        resp = DoneActivitiesView.as_view()(req)
        self.assertTrue(any(c['code'] == 'nueva' for c in resp.data['categories']))

    def test_classify_done_updates_and_validates(self):
        ActivityCategory.objects.create(code='nueva', label='Categoría nueva', order=99)
        item = self.report.activity_items.filter(kind=ActivityItem.KIND_DONE).first()
        req = self.factory.post(
            '/api/internal/classify-done/',
            {'results': [{'id': item.id, 'category': 'nueva'},
                         {'id': item.id, 'category': 'inexistente'},
                         {'id': 999999, 'category': 'diseno'}]},
            format='json', HTTP_X_INTERNAL_TOKEN='secret-token')
        resp = ClassifyDoneView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['updated'], 1)
        self.assertEqual(resp.data['skipped'], 2)
        item.refresh_from_db()
        self.assertEqual(item.category, 'nueva')
        self.assertEqual(item.source, ActivityItem.SOURCE_LLM)

    def test_classify_done_respects_manual_override(self):
        item = self.report.activity_items.filter(kind=ActivityItem.KIND_DONE).first()
        item.manual_override = True
        item.category = 'otros'
        item.save()
        req = self.factory.post(
            '/api/internal/classify-done/',
            {'results': [{'id': item.id, 'category': 'diseno'}]},
            format='json', HTTP_X_INTERNAL_TOKEN='secret-token')
        resp = ClassifyDoneView.as_view()(req)
        self.assertEqual(resp.data['updated'], 0)
        item.refresh_from_db()
        self.assertEqual(item.category, 'otros')

    def test_classify_done_creates_and_assigns_tags(self):
        item = self.report.activity_items.filter(kind=ActivityItem.KIND_DONE).first()
        req = self.factory.post(
            '/api/internal/classify-done/',
            {'results': [{'id': item.id, 'category': 'diseno',
                          'projects': ['Piñami 2'], 'locations': ['Cochabamba'],
                          'deliverables': ['plano', 'cronograma']}]},
            format='json', HTTP_X_INTERNAL_TOKEN='secret-token')
        resp = ClassifyDoneView.as_view()(req)
        self.assertEqual(resp.data['updated'], 1)
        item.refresh_from_db()
        kinds = sorted(item.tags.values_list('kind', flat=True))
        self.assertEqual(kinds, ['deliverable', 'deliverable', 'location', 'project'])
        self.assertTrue(ActivityTag.objects.filter(kind='project', name='Piñami 2').exists())

    def test_classify_done_routes_variant_to_merged_canonical(self):
        item = self.report.activity_items.filter(kind=ActivityItem.KIND_DONE).first()
        canon = ActivityTag.objects.create(kind='project', name='Piñami 2', key='pinami 2')
        alias = ActivityTag.objects.create(kind='project', name='Piñami2', key='pinami2',
                                           canonical=canon)
        # El LLM devuelve la variante "PIÑAMI2" (misma key que el alias) → debe rutear al canónico.
        req = self.factory.post(
            '/api/internal/classify-done/',
            {'results': [{'id': item.id, 'category': 'diseno', 'projects': ['PIÑAMI2']}]},
            format='json', HTTP_X_INTERNAL_TOKEN='secret-token')
        ClassifyDoneView.as_view()(req)
        item.refresh_from_db()
        self.assertEqual(
            list(item.tags.filter(kind='project').values_list('id', flat=True)), [canon.id])


class TagMergeEndpointsTests(TestCase):
    """Endpoints ejecutivos de tags: listado y fusión no destructiva."""

    def setUp(self):
        self.factory = APIRequestFactory()
        eu = User.objects.create(username='exec2')
        self.exec_emp = Employee.objects.create(
            user=eu, nextcloud_username='exec2', full_name='EXEC2', is_executive=True)
        nu = User.objects.create(username='noexec2')
        self.noexec = Employee.objects.create(
            user=nu, nextcloud_username='noexec2', full_name='NOEXEC2', cargo='Supervisor Y')
        self.a = ActivityTag.objects.create(kind='project', name='Piñami 2', key='pinami 2')
        self.b = ActivityTag.objects.create(kind='project', name='Piñami2', key='pinami2')

    def test_tags_list_executive_only(self):
        req = self.factory.get('/api/tags/', {'kind': 'project'})
        force_authenticate(req, user=self.noexec.user)
        resp = TagsListView.as_view()(req)
        self.assertEqual(resp.status_code, 403)

    def test_merge_sets_canonical_non_destructive(self):
        req = self.factory.post('/api/tags/merge/',
                                {'into': self.a.id, 'from': [self.b.id]}, format='json')
        force_authenticate(req, user=self.exec_emp.user)
        resp = TagMergeView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['merged'], 1)
        self.b.refresh_from_db()
        self.assertEqual(self.b.canonical_id, self.a.id)
        self.assertEqual(self.b.root().id, self.a.id)   # alias rutea al canónico
        self.assertTrue(ActivityTag.objects.filter(id=self.b.id).exists())  # no destructivo

    def test_unmerge_restores_canonical(self):
        self.b.canonical = self.a
        self.b.save()
        req = self.factory.post('/api/tags/unmerge/', {'ids': [self.b.id]}, format='json')
        force_authenticate(req, user=self.exec_emp.user)
        resp = TagUnmergeView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['unmerged'], 1)
        self.b.refresh_from_db()
        self.assertIsNone(self.b.canonical_id)   # vuelve a ser canónico independiente

    def test_merge_requires_executive(self):
        req = self.factory.post('/api/tags/merge/',
                                {'into': self.a.id, 'from': [self.b.id]}, format='json')
        force_authenticate(req, user=self.noexec.user)
        resp = TagMergeView.as_view()(req)
        self.assertEqual(resp.status_code, 403)

    def test_ignore_marks_and_blocks_reextraction(self):
        bad = ActivityTag.objects.create(kind='project', name='PMI Arellano', key='pmi arellano')
        req = self.factory.post('/api/tags/ignore/', {'ids': [bad.id]}, format='json')
        force_authenticate(req, user=self.exec_emp.user)
        resp = TagIgnoreView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        bad.refresh_from_db()
        self.assertTrue(bad.ignored)
        # una nueva extracción de la misma variante no vuelve a asociarla
        self.assertIsNone(ActivityTag.resolve('project', 'PMI Arellano'))
        # y no aparece en el listado
        lreq = self.factory.get('/api/tags/', {'kind': 'project'})
        force_authenticate(lreq, user=self.exec_emp.user)
        lresp = TagsListView.as_view()(lreq)
        self.assertFalse(any(t['name'] == 'PMI Arellano' for t in lresp.data['tags']))
