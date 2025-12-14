from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'احذف سجلات مهاجرات core من قاعدة البيانات'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM django_migrations WHERE app = 'core';")
        self.stdout.write(self.style.SUCCESS('تم حذف سجلات مهاجرات core من قاعدة البيانات بنجاح.'))
