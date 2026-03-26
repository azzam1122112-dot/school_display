# schedule/forms.py
from datetime import time

from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet

from .models import Period


def _fmt(t: time | None) -> str:
    return t.strftime("%H:%M:%S") if t else "-"


class PeriodForm(forms.ModelForm):
    class Meta:
        model = Period
        fields = ["day", "index", "starts_at", "ends_at"]
        widgets = {
            "starts_at": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "ends_at": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }

    def clean(self):
        cleaned = super().clean()
        starts_at = cleaned.get("starts_at")
        ends_at = cleaned.get("ends_at")

        if starts_at is None:
            self.add_error("starts_at", "هذا الحقل مطلوب.")
        if ends_at is None:
            self.add_error("ends_at", "هذا الحقل مطلوب.")
        if starts_at and ends_at and not (starts_at < ends_at):
            self.add_error(
                "ends_at",
                f"وقت النهاية يجب أن يكون بعد البداية. ({_fmt(starts_at)} < {_fmt(ends_at)})",
            )

        return cleaned


class PeriodInlineFormSet(BaseInlineFormSet):
    """تحقق جماعي داخل نفس اليوم: ترتيب فريد ومنع التداخل الزمني."""

    def clean(self):
        super().clean()

        rows: list[tuple[time, time, int]] = []
        used_indexes: set[int] = set()

        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if form.cleaned_data.get("DELETE", False):
                continue

            starts_at = form.cleaned_data.get("starts_at")
            ends_at = form.cleaned_data.get("ends_at")
            index = form.cleaned_data.get("index")

            if index in (None, ""):
                form.add_error("index", "ترتيب الحصة مطلوب.")
                continue

            try:
                idx = int(index)
            except Exception:
                form.add_error("index", "ترتيب الحصة غير صالح.")
                continue

            if idx in used_indexes:
                form.add_error("index", "رقم الحصة مكرر داخل نفس اليوم.")
                continue
            used_indexes.add(idx)

            if starts_at is None or ends_at is None:
                # أخطاء الحقول نفسها ستظهر من PeriodForm.clean
                continue

            if not (starts_at < ends_at):
                form.add_error(
                    "ends_at",
                    f"وقت النهاية يجب أن يكون بعد البداية. ({_fmt(starts_at)} < {_fmt(ends_at)})",
                )
                continue

            rows.append((starts_at, ends_at, idx))

        rows.sort(key=lambda row: row[0])
        for i in range(len(rows)):
            s1, e1, idx1 = rows[i]
            for j in range(i + 1, len(rows)):
                s2, e2, idx2 = rows[j]
                if max(s1, s2) < min(e1, e2):
                    first = idx1 if idx1 < idx2 else idx2
                    second = idx2 if idx1 < idx2 else idx1
                    raise ValidationError(
                        f"تداخل وقتي بين الحصة #{first} ({_fmt(s1)}-{_fmt(e1)}) "
                        f"والحصة #{second} ({_fmt(s2)}-{_fmt(e2)})."
                    )
