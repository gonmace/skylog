from django.urls import path
from .views import WorkdayStartView, WorkdayEndView, ActiveWorkdayView, LastReportView, EmployeeOverviewView, CaptureNowView, EmployeeScreenshotsToggleView, EmployeeSkylogToggleView

urlpatterns = [
    path('workday/start/', WorkdayStartView.as_view()),
    path('workday/end/', WorkdayEndView.as_view()),
    path('workday/active/', ActiveWorkdayView.as_view()),
    path('workday/last-report/', LastReportView.as_view()),
    path('employees/overview/', EmployeeOverviewView.as_view()),
    path('employees/<int:employee_id>/capture/', CaptureNowView.as_view()),
    path('employees/<int:employee_id>/screenshots/', EmployeeScreenshotsToggleView.as_view()),
    path('employees/<int:employee_id>/skylog/', EmployeeSkylogToggleView.as_view()),
]
