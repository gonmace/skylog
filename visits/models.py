from django.db import models
from django.contrib.auth.models import User


class Visitor(models.Model):
    """Usuario externo con acceso únicamente a las estadísticas (rol "visita").

    No es un Employee: se reutiliza el User de Django para JWT/sesión, pero el
    visitante no tiene acceso al dashboard ni al resto del sistema. La contraseña
    vive en el User; `user.has_usable_password()` distingue la primera vez (crear
    contraseña) de las siguientes (solo ingresarla).
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='visitor')
    full_name = models.CharField(max_length=255, verbose_name='Nombre completo')
    email = models.EmailField(unique=True, verbose_name='Correo')
    is_active = models.BooleanField(default=True, verbose_name='Activo')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Visita'
        verbose_name_plural = 'Visitas'
        ordering = ['full_name']

    def __str__(self):
        return f'{self.full_name} <{self.email}>'

    @property
    def login_count(self):
        return self.logins.count()

    @property
    def last_login_at(self):
        last = self.logins.order_by('-logged_at').first()
        return last.logged_at if last else None

    @property
    def has_password(self):
        return self.user.has_usable_password()


class VisitLog(models.Model):
    """Bitácora: un registro por cada ingreso del visitante."""
    visitor = models.ForeignKey(Visitor, on_delete=models.CASCADE, related_name='logins')
    logged_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='IP')

    class Meta:
        verbose_name = 'Ingreso de visita'
        verbose_name_plural = 'Ingresos de visitas'
        ordering = ['-logged_at']

    def __str__(self):
        return f'{self.visitor.full_name} — {self.logged_at:%d/%m/%Y %H:%M}'
