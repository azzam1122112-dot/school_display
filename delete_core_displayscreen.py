from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("DROP TABLE IF EXISTS core_displayscreen;")
print("تم حذف جدول core_displayscreen بنجاح.")
