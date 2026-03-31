import secrets
from django.db import models
from django.utils import timezone
from datetime import timedelta


class AgentRegistration(models.Model):
    device_token = models.CharField(max_length=64, unique=True)
    jwt_access = models.TextField(blank=True)
    jwt_refresh = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Registro de agente'
        verbose_name_plural = 'Registros de agente'

    def is_ready(self):
        return bool(self.jwt_access)


class AgentActivationToken(models.Model):
    employee = models.ForeignKey('employees.Employee', on_delete=models.CASCADE, related_name='activation_tokens')
    token = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Token de activación de agente'
        verbose_name_plural = 'Tokens de activación de agente'

    @classmethod
    def create_for_employee(cls, employee):
        # Invalida tokens anteriores no usados del mismo empleado
        cls.objects.filter(employee=employee, used=False).delete()
        return cls.objects.create(
            employee=employee,
            token=secrets.token_urlsafe(32),
            expires_at=timezone.now() + timedelta(hours=24),
        )

    def is_valid(self):
        return not self.used and timezone.now() < self.expires_at
