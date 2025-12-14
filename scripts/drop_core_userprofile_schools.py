import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("DROP TABLE IF EXISTS core_userprofile_schools;")
print("تم حذف الجدول core_userprofile_schools بنجاح.")
