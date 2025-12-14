from core.models import UserProfile, School

def fix_user_profiles():
    first_school = School.objects.first()
    if not first_school:
        print('لا توجد مدارس في النظام.')
        return
    count = 0
    for profile in UserProfile.objects.all():
        if not profile.active_school or not profile.schools.exists():
            profile.schools.add(first_school)
            profile.active_school = first_school
            profile.save()
            print(f'تم إصلاح المستخدم: {profile.user.username}')
            count += 1
    print(f'تم إصلاح {count} مستخدم.')

if __name__ == "__main__":
    fix_user_profiles()
