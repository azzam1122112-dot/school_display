# إصلاح بيانات المدارس النشطة للمستخدمين
# يشغّل عبر: python manage.py shell < scripts/fix_active_school.py

from core.models import UserProfile, School
from django.db import transaction

fixed = 0
with transaction.atomic():
    for profile in UserProfile.objects.all():
        schools = list(profile.schools.all())
        # إذا لم يكن لديه مدارس، اجعل النشطة None
        if not schools:
            if profile.active_school_id is not None:
                profile.active_school = None
                profile.save(update_fields=["active_school"])
                fixed += 1
            continue
        # إذا active_school غير موجودة أو غير مرتبطة
        if (profile.active_school_id is None) or (profile.active_school_id not in [s.id for s in schools]):
            profile.active_school = schools[0]
            profile.save(update_fields=["active_school"])
            fixed += 1
print(f"تم إصلاح {fixed} حساب/حسابات.")
