from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'احذف جدول core_displayscreen من قاعدة البيانات إذا كان موجوداً'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS core_displayscreen;")
        self.stdout.write(self.style.SUCCESS('تم حذف جدول core_displayscreen بنجاح.'))
