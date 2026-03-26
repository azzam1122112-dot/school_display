from pathlib import Path

from django.test import TestCase


class DisplayTemplateContractTests(TestCase):
    def test_display_template_contains_critical_dom_ids(self):
        """
        Smoke test: protect IDs that display.js binds to at runtime.
        This prevents accidental template refactors from silently breaking the screen.
        """
        template_path = Path(__file__).resolve().parent.parent / "templates" / "website" / "display.html"
        html = template_path.read_text(encoding="utf-8")

        required_ids = [
            "schoolLogo",
            "schoolName",
            "dateGregorian",
            "dateHijri",
            "clock",
            "alertContainer",
            "alertTitle",
            "alertDetails",
            "badgeKind",
            "heroRange",
            "heroTitle",
            "currentScheduleList",
            "countdown",
            "progressBar",
            "exCard",
            "dutyCard",
            "periodClassesTrack",
            "standbyTrack",
            "blocker",
            "blockerTitle",
            "blockerDetails",
            "blockerLink",
        ]

        for dom_id in required_ids:
            self.assertIn(f'id="{dom_id}"', html, msg=f"Missing required DOM id in display template: {dom_id}")

        self.assertTrue(
            ('id="fitStage"' in html) or ('id="fitRoot"' in html),
            msg="Display template must provide fitStage or fitRoot for auto-fit logic.",
        )
