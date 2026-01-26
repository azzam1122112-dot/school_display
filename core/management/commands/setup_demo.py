from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from core.models import School, UserProfile, DisplayScreen
from schedule.models import SchoolSettings, DaySchedule, Period
from notices.models import Announcement
from standby.models import StandbyAssignment
from django.db import transaction
from django.db.models.signals import post_save, post_delete
from schedule.models import SchoolSettings, DaySchedule, Period, Break
from notices.models import Announcement, Excellence

# Try to import the signals
# (Removed Firebase signals module integration)

import random
import datetime

class Command(BaseCommand):
    help = 'Sets up or resets the demo account'

    @transaction.atomic
    def handle(self, *args, **kwargs):
        # Disconnect signals to prevent issues during cleanup
        # (Signals were removed)
        self.stdout.write("Starting demo setup...")

        # 1. إعداد المدرسة والمستخدم
        username = "demo_user"
        email = "demo@school.com"
        password = "demo_password_123"
        school_name = "مدرسة التجربة النموذجية"
        school_slug = "demo-school"

        self.stdout.write("Cleaning up old demo data...")
        # حذف القديم إن وجد (للتنظيف)
        User.objects.filter(username=username).delete()
        
        # Force delete by slug to ensure no conflicts
        try:
            with transaction.atomic():
                # Delete schools
                schools_to_delete = School.objects.filter(slug=school_slug) | School.objects.filter(name=school_name)
                for school in schools_to_delete.distinct():
                    self.stdout.write(f"Deleting school: {school.name}")
                    school.delete() # Should work fine now without signals
                
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Cleanup warning: {e}"))

        self.stdout.write("Creating demo school and user...")
        # إنشاء المدرسة
        school = School.objects.create(
            name=school_name,
            slug=school_slug,
            is_active=True
        )

        # إنشاء المستخدم
        user = User.objects.create_user(username=username, email=email, password=password)
        UserProfile.objects.create(user=user, school=school)

        # إعدادات المدرسة
        settings = SchoolSettings.objects.create(
            school=school,
            name=school_name,
            theme="indigo",
            refresh_interval_sec=30,
            timezone_name="Asia/Riyadh"
        )

        # 2. إنشاء شاشة عرض
        DisplayScreen.objects.create(
            school=school,
            name="شاشة المدخل الرئيسي",
            is_active=True
        )

        self.stdout.write("Creating schedule...")
        # 3. إنشاء جدول حصص (مثال ليوم الأحد إلى الخميس)
        # 0=Sunday, 1=Monday, ..., 4=Thursday
        for weekday in range(5):
            day = DaySchedule.objects.create(
                settings=settings,
                weekday=weekday,
                periods_count=7
            )
            
            # الطابور الصباحي 6:45
            start_time = datetime.time(6, 45)
            
            # الحصة الأولى تبدأ 7:00
            current_time = datetime.datetime.combine(datetime.date.today(), datetime.time(7, 0))
            
            for i in range(1, 8):
                end_time = current_time + datetime.timedelta(minutes=45)
                Period.objects.create(
                    day=day,
                    index=i,
                    starts_at=current_time.time(),
                    ends_at=end_time.time()
                )
                
                # فسحة بعد الحصة الثالثة
                if i == 3:
                    current_time = end_time + datetime.timedelta(minutes=15)
                # صلاة بعد الحصة الخامسة
                elif i == 5:
                    current_time = end_time + datetime.timedelta(minutes=20)
                else:
                    current_time = end_time + datetime.timedelta(minutes=5)

        self.stdout.write("Creating announcements...")
        # 4. إضافة إعلانات وهمية
        Announcement.objects.create(
            school=school,
            title="مرحباً بكم في النسخة التجريبية",
            body="يمكنكم تجربة إضافة إعلانات جديدة أو تعديل جدول الحصص. سيتم إعادة ضبط البيانات تلقائياً كل فترة.",
            level="info",
            is_active=True,
            starts_at=timezone.now(),
            expires_at=timezone.now() + datetime.timedelta(days=7)
        )
        
        Announcement.objects.create(
            school=school,
            title="اجتماع مجلس الآباء",
            body="ندعوكم لحضور اجتماع مجلس الآباء والمعلم/ـةين يوم الخميس القادم في مسرح المدرسة.",
            level="warning",
            is_active=True,
            starts_at=timezone.now(),
            expires_at=timezone.now() + datetime.timedelta(days=5)
        )

        Announcement.objects.create(
            school=school,
            title="تهنئة",
            body="تتقدم إدارة المدرسة بالتهنئة للطالب محمد أحمد لحصوله على المركز الأول في مسابقة الرياضيات.",
            level="success",
            is_active=True,
            starts_at=timezone.now(),
            expires_at=timezone.now() + datetime.timedelta(days=3)
        )

        self.stdout.write("Creating standby assignments...")
        # 5. إضافة حصص انتظار وهمية
        teachers = ["أحمد محمد", "خالد العتيبي", "سعيد الغامدي", "فهد الدوسري", "عمر الصالح"]
        today = timezone.localdate()
        
        # إضافة انتظار لليوم
        for _ in range(4):
            StandbyAssignment.objects.create(
                school=school,
                teacher_name=random.choice(teachers),
                period_index=random.randint(1, 7),
                class_name=f"فصل {random.randint(1, 3)}/{random.randint(1, 3)}",
                date=today
            )
            
        # إضافة انتظار للغد
        tomorrow = today + datetime.timedelta(days=1)
        for _ in range(2):
            StandbyAssignment.objects.create(
                school=school,
                teacher_name=random.choice(teachers),
                period_index=random.randint(1, 7),
                class_name=f"فصل {random.randint(1, 3)}/{random.randint(1, 3)}",
                date=tomorrow
            )

        self.stdout.write(self.style.SUCCESS(f'Successfully setup demo account for {school_name}'))
