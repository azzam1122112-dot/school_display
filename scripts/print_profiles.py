# سكريبت طباعة بيانات المستخدمين والمدارس النشطة
from core.models import UserProfile
for profile in UserProfile.objects.all():
    print(f"user: {profile.user.username}")
    print(f"  active_school_id: {profile.active_school_id}")
    print(f"  schools: {[s.id for s in profile.schools.all()]}")
    if profile.active_school:
        print(f"  active_school name: {profile.active_school.name}")
    else:
        print("  active_school: None")
    print("-"*30)
