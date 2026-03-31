from django.db import models
from django.conf import settings
from django.urls import reverse
from employees.models import Employee
from workdays.models import Workday


class Screenshot(models.Model):
    STORAGE_LOCAL = 'local'
    STORAGE_NEXTCLOUD = 'nextcloud'
    STORAGE_CHOICES = [
        (STORAGE_LOCAL, 'Local'),
        (STORAGE_NEXTCLOUD, 'Nextcloud'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='screenshots')
    workday = models.ForeignKey(Workday, on_delete=models.CASCADE, related_name='screenshots')
    file_path = models.CharField(max_length=512)
    storage = models.CharField(max_length=20, choices=STORAGE_CHOICES, default=STORAGE_LOCAL)
    captured_at = models.DateTimeField(auto_now_add=True)

    def get_absolute_url(self):
        if self.storage == self.STORAGE_NEXTCLOUD:
            return reverse('screenshot-image', kwargs={'pk': self.pk})
        return f"{settings.MEDIA_URL}{self.file_path}"

    def __str__(self):
        return f"Screenshot {self.employee.nextcloud_username} — {self.captured_at.strftime('%Y-%m-%d %H:%M')}"

    class Meta:
        ordering = ['-captured_at']
        verbose_name = 'Captura de pantalla'
        verbose_name_plural = 'Capturas de pantalla'
