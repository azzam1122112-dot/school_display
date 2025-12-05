import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from schedule.models import SchoolSettings
s = SchoolSettings.objects.first()
if s:
    print(f"Current theme in DB: '{s.theme}'")
else:
    print("No settings found")
