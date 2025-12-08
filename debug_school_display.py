"""
Script: debug_school_display.py
وظيفة السكريبت: فحص إعدادات المدرسة والشاشة والجدول وعرض المشاكل المحتملة.
"""

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from core.models import School, DisplayScreen
from schedule.models import SchoolSettings, DaySchedule, Period, Break, Classroom, WeeklySchedule

print("--- فحص إعدادات School Display ---\n")

# 1. المدارس
schools = School.objects.filter(is_active=True)
if not schools:
    print("❌ لا توجد مدارس مفعلة.")
else:
    print(f"✅ عدد المدارس المفعلة: {schools.count()}")
    for school in schools:
        print(f"- {school.name}")

# 2. إعدادات المدرسة
for school in schools:
    settings = SchoolSettings.objects.filter(school=school).first()
    if not settings:
        print(f"❌ المدرسة '{school.name}' ليس لديها إعدادات SchoolSettings.")
        continue
    print(f"✅ إعدادات المدرسة '{school.name}' موجودة.")
    # 3. جدول اليوم الحالي
    from datetime import datetime
    today = datetime.now()
    weekday = (today.weekday() + 1) % 7  # Sunday=0
    day_schedule = DaySchedule.objects.filter(settings=settings, weekday=weekday).first()
    if not day_schedule:
        print(f"❌ لا يوجد جدول ليوم اليوم ({day_schedule.get_weekday_display() if day_schedule else weekday}) للمدرسة '{school.name}'.")
        continue
    if not day_schedule.is_active:
        print(f"❌ جدول اليوم '{day_schedule.get_weekday_display()}' غير مفعل.")
    else:
        print(f"✅ جدول اليوم '{day_schedule.get_weekday_display()}' مفعل.")
    # 4. الحصص والفسح
    periods = Period.objects.filter(day=day_schedule)
    breaks = Break.objects.filter(day=day_schedule)
    print(f"- عدد الحصص: {periods.count()} | عدد الفسح: {breaks.count()}")
    if not periods:
        print(f"❌ لا توجد حصص لهذا اليوم.")
    # 5. الفصول وجداول الحصص
    classrooms = Classroom.objects.filter(school=school)
    print(f"- عدد الفصول: {classrooms.count()}")
    for cls in classrooms:
        schedules = WeeklySchedule.objects.filter(classroom=cls, day_of_week=weekday)
        print(f"  فصل: {cls.name} | جداول اليوم: {schedules.count()}")
        if not schedules:
            print(f"  ❌ لا يوجد جدول حصص لهذا الفصل اليوم.")
    # 6. شاشة العرض
    screens = DisplayScreen.objects.filter(school=school, is_active=True)
    print(f"- عدد شاشات العرض المفعلة: {screens.count()}")
    for screen in screens:
        print(f"  شاشة: {screen.name} | Token: {screen.token}")

print("\n--- انتهى الفحص ---")
