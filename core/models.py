from django.db import models
from django.contrib.auth.models import User
import secrets

class School(models.Model):
    name = models.CharField("اسم المدرسة", max_length=150)
    slug = models.SlugField("رابط المدرسة", unique=True, help_text="يستخدم في الرابط، مثلا: school-1")
    logo = models.ImageField("الشعار", upload_to="schools/logos/", blank=True, null=True)
    is_active = models.BooleanField("اشتراك نشط", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "مدرسة"
        verbose_name_plural = "المدارس"

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile", verbose_name="المستخدم")
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="users", verbose_name="المدرسة", null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.school.name if self.school else 'No School'}"

    class Meta:
        verbose_name = "ملف المستخدم"
        verbose_name_plural = "ملفات المستخدمين"

class DisplayScreen(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="screens", verbose_name="المدرسة", null=True, blank=True)
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
        return f"{self.school.name} - {self.name}" if self.school else self.name

    class Meta:
        verbose_name = "شاشة عرض"
        verbose_name_plural = "شاشات العرض"
