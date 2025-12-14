from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("DELETE FROM django_migrations WHERE app = 'core';")
print("تم حذف سجلات مهاجرات core من قاعدة البيانات بنجاح.")
