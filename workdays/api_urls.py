from django.urls import path
from .views import (
    WorkdayStartView, WorkdayEndView, ActiveWorkdayView, LastReportView,
    EmployeeOverviewView, CaptureNowView, EmployeeScreenshotsToggleView,
    EmployeeSkylogToggleView, SendMessageView, PendingMessagesView,
    AcknowledgeMessageView, WorkdayMonthlyView, EmployeeMonthlyView,
    CalendarNotesView, CalendarNoteDetailView, EmployeeLeavesView, EmployeeLeaveDetailView,
    ReporteAPIView, ReporteExportView,
)

urlpatterns = [
    path('workday/start/', WorkdayStartView.as_view()),
    path('workday/end/', WorkdayEndView.as_view()),
    path('workday/active/', ActiveWorkdayView.as_view()),
    path('workday/last-report/', LastReportView.as_view()),
    path('employees/overview/', EmployeeOverviewView.as_view()),
    path('employees/<int:employee_id>/capture/', CaptureNowView.as_view()),
    path('employees/<int:employee_id>/screenshots/', EmployeeScreenshotsToggleView.as_view()),
    path('employees/<int:employee_id>/skylog/', EmployeeSkylogToggleView.as_view()),
    path('employees/<int:employee_id>/message/', SendMessageView.as_view()),
    path('messages/pending/', PendingMessagesView.as_view()),
    path('messages/<int:message_id>/acknowledge/', AcknowledgeMessageView.as_view()),
    path('workday/monthly/', WorkdayMonthlyView.as_view()),
    path('employees/<int:employee_id>/monthly/', EmployeeMonthlyView.as_view()),
    path('calendar/notes/', CalendarNotesView.as_view()),
    path('calendar/notes/<int:note_id>/', CalendarNoteDetailView.as_view()),
    path('employees/<int:employee_id>/leaves/', EmployeeLeavesView.as_view()),
    path('employees/<int:employee_id>/leaves/<int:leave_id>/', EmployeeLeaveDetailView.as_view()),
    path('reporte/', ReporteAPIView.as_view()),
    path('reporte/export/', ReporteExportView.as_view()),
]
