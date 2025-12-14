import os
import django
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import School
for school in School.objects.all():
    print(f"ID: {school.id}, Name: {school.name}")