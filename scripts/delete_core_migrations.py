from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("DELETE FROM django_migrations WHERE app='core';")
print('Deleted all migration records for app=core from django_migrations.')
