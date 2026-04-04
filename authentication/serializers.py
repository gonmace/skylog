from rest_framework import serializers
from employees.models import Employee

# Mantenido por compatibilidad con imports existentes en workdays/views.py
AGENT_ACTIVE_THRESHOLD_MINUTES = 35


class EmployeeSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', read_only=True)
    agent_is_active = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = ['id', 'nextcloud_username', 'full_name', 'department', 'is_active', 'is_executive', 'is_mobile', 'solo_movil', 'email', 'agent_version', 'agent_is_active', 'agent_last_seen', 'skylog_access']

    def get_agent_is_active(self, obj):
        return obj.agent_online
