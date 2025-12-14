from django.core.management.base import BaseCommand
from core.models import UserProfile, School

class Command(BaseCommand):
    help = 'إصلاح جميع المستخدمين غير المرتبطين بمدرسة نشطة أو قائمة مدارس.'

    def handle(self, *args, **options):
        first_school = School.objects.first()
        if not first_school:
            self.stdout.write(self.style.ERROR('لا توجد مدارس في النظام!'))
            return
        count = 0
        for profile in UserProfile.objects.all():
            if not profile.active_school or not profile.schools.exists():
                profile.schools.add(first_school)
                profile.active_school = first_school
                profile.save()
                self.stdout.write(self.style.SUCCESS(f'تم إصلاح المستخدم: {profile.user.username}'))
                count += 1
        self.stdout.write(self.style.SUCCESS(f'تم إصلاح {count} مستخدم.'))
