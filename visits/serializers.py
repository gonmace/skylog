from rest_framework import serializers
from .models import Visitor


class VisitorSerializer(serializers.ModelSerializer):
    login_count = serializers.IntegerField(read_only=True)
    last_login_at = serializers.DateTimeField(read_only=True)
    has_password = serializers.BooleanField(read_only=True)

    class Meta:
        model = Visitor
        fields = ['id', 'full_name', 'email', 'is_active', 'login_count', 'last_login_at', 'has_password', 'created_at']
