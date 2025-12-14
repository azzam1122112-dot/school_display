from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'احذف جميع جداول core من قاعدة البيانات مع تعطيل قيود العلاقات مؤقتًا (SQLite فقط)'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA foreign_keys = OFF;")
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'core_%';")
            tables = [row[0] for row in cursor.fetchall()]
            for table in tables:
                cursor.execute(f"DROP TABLE IF EXISTS {table};")
                self.stdout.write(self.style.SUCCESS(f'تم حذف الجدول: {table}'))
            cursor.execute("PRAGMA foreign_keys = ON;")
        self.stdout.write(self.style.SUCCESS('تم حذف جميع جداول core بنجاح مع تعطيل قيود العلاقات مؤقتًا.'))
