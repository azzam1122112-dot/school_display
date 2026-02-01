#!/usr/bin/env python
"""
سكريبت الإصلاح السريع قبل الإطلاق
Pre-Launch Quick Fix Script

يقوم بـ:
1. إنشاء SchoolSettings لجميع المدارس النشطة
2. فحص حالة جميع الشاشات
3. إنشاء تقرير تفصيلي
"""

import os
import sys
import django

# إعداد Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import School, DisplayScreen
from schedule.models import SchoolSettings
from django.db import transaction


def create_missing_school_settings():
    """إنشاء SchoolSettings للمدارس التي لا تملك إعدادات"""
    print("\n" + "="*60)
    print("1️⃣  فحص وإنشاء إعدادات المدارس")
    print("="*60)
    
    schools = School.objects.filter(is_active=True)
    created_count = 0
    existing_count = 0
    
    for school in schools:
        settings, created = SchoolSettings.objects.get_or_create(
            school=school,
            defaults={
                'theme': 'indigo',
                'featured_panel': 'excellence',
                'refresh_interval_sec': 60,
                'standby_scroll_speed': 0.8,
                'periods_scroll_speed': 0.5,
            }
        )
        
        if created:
            created_count += 1
            print(f"✅ تم إنشاء إعدادات للمدرسة: {school.name}")
        else:
            existing_count += 1
            print(f"ℹ️  المدرسة {school.name} لديها إعدادات بالفعل")
    
    print("\n📊 الملخص:")
    print(f"   - المدارس النشطة: {schools.count()}")
    print(f"   - إعدادات جديدة: {created_count}")
    print(f"   - إعدادات موجودة: {existing_count}")
    
    if created_count > 0:
        print(f"✅ تم إنشاء {created_count} إعدادات جديدة بنجاح!")
    else:
        print("✅ جميع المدارس لديها إعدادات!")


def check_display_screens():
    """فحص حالة جميع شاشات العرض"""
    print("\n" + "="*60)
    print("2️⃣  فحص شاشات العرض")
    print("="*60)
    
    screens = DisplayScreen.objects.select_related('school').all()
    
    active_screens = []
    inactive_screens = []
    auto_disabled_screens = []
    screens_without_school = []
    screens_with_binding = []
    
    for screen in screens:
        if not screen.school:
            screens_without_school.append(screen)
        elif screen.auto_disabled_by_limit:
            auto_disabled_screens.append(screen)
        elif screen.is_active:
            active_screens.append(screen)
            if screen.bound_device_id:
                screens_with_binding.append(screen)
        else:
            inactive_screens.append(screen)
    
    print(f"\n📊 الإحصائيات:")
    print(f"   - إجمالي الشاشات: {screens.count()}")
    print(f"   - شاشات نشطة: {len(active_screens)}")
    print(f"   - شاشات غير نشطة: {len(inactive_screens)}")
    print(f"   - شاشات معطلة تلقائياً: {len(auto_disabled_screens)}")
    print(f"   - شاشات بدون مدرسة: {len(screens_without_school)}")
    print(f"   - شاشات مربوطة بجهاز: {len(screens_with_binding)}")
    
    if inactive_screens:
        print("\n⚠️  شاشات غير نشطة:")
        for screen in inactive_screens:
            school_name = screen.school.name if screen.school else "بدون مدرسة"
            print(f"   - {screen.name} ({school_name})")
            print(f"     Token: {screen.token[:16]}...")
            print(f"     Short Code: {screen.short_code}")
    
    if auto_disabled_screens:
        print("\n⚠️  شاشات معطلة تلقائياً (تجاوز حد الاشتراك):")
        for screen in auto_disabled_screens:
            school_name = screen.school.name if screen.school else "بدون مدرسة"
            print(f"   - {screen.name} ({school_name})")
    
    if screens_without_school:
        print("\n❌ شاشات بدون مدرسة (يجب حذفها):")
        for screen in screens_without_school:
            print(f"   - {screen.name} (ID: {screen.id})")
    
    if active_screens:
        print("\n✅ شاشات نشطة:")
        for screen in active_screens:
            school_name = screen.school.name if screen.school else "بدون مدرسة"
            binding_status = "🔒 مربوطة" if screen.bound_device_id else "🔓 غير مربوطة"
            print(f"   - {screen.name} ({school_name}) {binding_status}")


def check_schools_data():
    """فحص بيانات المدارس"""
    print("\n" + "="*60)
    print("3️⃣  فحص بيانات المدارس")
    print("="*60)
    
    schools = School.objects.all()
    
    for school in schools:
        screen_count = school.screens.count()
        active_screen_count = school.screens.filter(is_active=True).count()
        has_settings = hasattr(school, 'schedule_settings')
        
        status = "✅" if school.is_active else "⚠️"
        print(f"\n{status} {school.name}")
        print(f"   - الحالة: {'نشط' if school.is_active else 'غير نشط'}")
        print(f"   - الشاشات: {active_screen_count}/{screen_count}")
        print(f"   - الإعدادات: {'موجودة ✅' if has_settings else 'غير موجودة ⚠️'}")
        print(f"   - النوع: {school.get_school_type_display() if school.school_type else 'غير محدد'}")
        print(f"   - الشعار: {'موجود ✅' if school.logo else 'غير موجود ⚠️'}")


def generate_test_urls():
    """إنشاء روابط اختبار لجميع الشاشات النشطة"""
    print("\n" + "="*60)
    print("4️⃣  روابط الاختبار")
    print("="*60)
    
    screens = DisplayScreen.objects.filter(
        is_active=True,
        school__is_active=True
    ).select_related('school')
    
    if not screens:
        print("❌ لا توجد شاشات نشطة للاختبار!")
        return
    
    print("\n📋 روابط API للاختبار:")
    print("\nاختبار محلي (localhost:8000):")
    for screen in screens:
        print(f"\n   المدرسة: {screen.school.name}")
        print(f"   الشاشة: {screen.name}")
        print(f"   ----------------------------------------")
        print(f"   Snapshot API:")
        print(f"   curl 'http://localhost:8000/api/display/snapshot/?token={screen.token}'")
        print(f"   ")
        print(f"   Status API:")
        print(f"   curl 'http://localhost:8000/api/display/status/?token={screen.token}'")
    
    print("\n\n📋 روابط صفحات العرض:")
    for screen in screens:
        print(f"\n   {screen.school.name} - {screen.name}:")
        print(f"   http://localhost:8000/display/{screen.short_code}/")


def main():
    """الدالة الرئيسية"""
    print("\n")
    print("="*60)
    print("   🔧 سكريبت الإصلاح السريع قبل الإطلاق")
    print("   Pre-Launch Quick Fix Script")
    print("="*60)
    
    try:
        # 1. إنشاء إعدادات المدارس
        create_missing_school_settings()
        
        # 2. فحص شاشات العرض
        check_display_screens()
        
        # 3. فحص بيانات المدارس
        check_schools_data()
        
        # 4. إنشاء روابط الاختبار
        generate_test_urls()
        
        print("\n" + "="*60)
        print("✅ اكتمل الفحص بنجاح!")
        print("="*60)
        
        print("\n📋 الخطوات التالية:")
        print("   1. اختبر الروابط أعلاه للتأكد من عمل النظام")
        print("   2. راجع ملف docs/PRE_LAUNCH_SYSTEM_AUDIT.md")
        print("   3. طبق التوصيات العاجلة قبل الإطلاق")
        print("   4. تأكد من إعدادات الإنتاج (DEBUG=False, SSL, etc.)")
        
    except Exception as e:
        print(f"\n❌ حدث خطأ: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
