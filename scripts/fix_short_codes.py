from core.models import DisplayScreen

def fix_short_codes():
    fixed = 0
    for screen in DisplayScreen.objects.filter(short_code__isnull=True):
        screen.save()  # سيولد short_code تلقائياً
        fixed += 1
    print(f"تم إصلاح {fixed} شاشة.")

if __name__ == "__main__":
    fix_short_codes()
