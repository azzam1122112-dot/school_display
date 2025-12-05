from django.db import models
import secrets

class DisplayScreen(models.Model):
    name = models.CharField(max_length=100, verbose_name="اسم الشاشة")
    token = models.CharField(max_length=64, unique=True, editable=False, verbose_name="رمز الوصول")
    is_active = models.BooleanField(default=True, verbose_name="نشط")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(null=True, blank=True, verbose_name="آخر ظهور")

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_hex(32)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "شاشة عرض"
        verbose_name_plural = "شاشات العرض"
