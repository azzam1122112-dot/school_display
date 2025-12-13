from django.db import models
from django.conf import settings



class School(models.Model):
    name = models.CharField(max_length=255)
    city = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class SchoolMembership(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='members')
    role = models.CharField(max_length=50, default='teacher')  # teacher, admin, manager...

    def __str__(self):
        return f"{self.user} - {self.school}"
