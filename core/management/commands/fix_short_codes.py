from django.core.management.base import BaseCommand
from core.models import DisplayScreen

class Command(BaseCommand):
    help = 'Assign short_code to all DisplayScreen objects missing it.'

    def handle(self, *args, **options):
        fixed = 0
        for screen in DisplayScreen.objects.filter(short_code__isnull=True):
            screen.save()  # سيولد short_code تلقائياً
            fixed += 1
        self.stdout.write(self.style.SUCCESS(f'تم إصلاح {fixed} شاشة.'))
