import os
import sys
from pathlib import Path

# Ensure project root is on sys.path (script lives under scripts/)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()  # noqa: E402

from django.test import Client  # noqa: E402
from core.models import School, DisplayScreen  # noqa: E402


def main() -> None:
    # Create a test school + screen
    school, _ = School.objects.get_or_create(
        slug="bind-test-school",
        defaults={"name": "Bind Test School"},
    )

    screen = DisplayScreen.objects.create(school=school, name="Bind Screen", is_active=True)
    token = screen.token
    url = f"/api/display/snapshot/{token}/"

    c1 = Client()
    c1.cookies["sd_device"] = "DEVICE_A"

    c2 = Client()
    c2.cookies["sd_device"] = "DEVICE_B"

    # 1) First device should bind (and should not error due to binding)
    r1 = c1.get(url, HTTP_HOST="127.0.0.1", HTTP_X_DISPLAY_TOKEN=token)
    screen.refresh_from_db()
    bound_after_r1 = screen.bound_device_id

    # 2) Second device should be blocked and MUST NOT change binding
    r2 = c2.get(url, HTTP_HOST="127.0.0.1", HTTP_X_DISPLAY_TOKEN=token)
    screen.refresh_from_db()
    bound_after_r2 = screen.bound_device_id

    # 3) First device should still work (not impacted by device B attempt)
    r3 = c1.get(url, HTTP_HOST="127.0.0.1", HTTP_X_DISPLAY_TOKEN=token)
    screen.refresh_from_db()
    bound_after_r3 = screen.bound_device_id

    print("URL:", url)
    print("r1.status_code:", r1.status_code)
    print("bound_after_r1:", bound_after_r1)
    print("r2.status_code:", r2.status_code)
    try:
        print("r2.json:", r2.json())
    except Exception:
        print("r2.body:", getattr(r2, "content", b"")[:300])
    print("bound_after_r2:", bound_after_r2)
    print("r3.status_code:", r3.status_code)
    print("bound_after_r3:", bound_after_r3)

    assert bound_after_r1 == "DEVICE_A", "Expected binding to DEVICE_A after first request"
    assert r2.status_code == 403, "Expected second device to be blocked"
    assert bound_after_r2 == "DEVICE_A", "Expected binding to remain DEVICE_A after blocked attempt"
    assert bound_after_r3 == "DEVICE_A", "Expected binding to remain DEVICE_A after subsequent first-device request"

    print("OK: Primary device not affected; second device blocked.")


if __name__ == "__main__":
    main()
