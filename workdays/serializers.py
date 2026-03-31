from rest_framework import serializers
from .models import Workday, DailyReport


class WorkdaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Workday
        fields = ['id', 'start_time', 'end_time', 'duration_minutes', 'status']


class DailyReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyReport
        fields = ['activities_done', 'activities_planned', 'submitted_at']
