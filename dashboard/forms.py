from __future__ import annotations

from datetime import datetime, time, timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory, BaseInlineFormSet

from schedule.models import (
    SchoolSettings,
    DaySchedule,
    Period,
    Break,
    ClassLesson,
    WEEKDAYS,
    SchoolClass,
    Teacher,
)
from notices.models import Announcement, Excellence
from standby.models import StandbyAssignment
from core.models import DisplayScreen


def _parse_hhmm(value: str | None):
    if not value:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


def _is_checked(raw) -> bool:
    return str(raw).lower() in {"1", "true", "on", "yes"}


def _is_blank_period_fields(idx, st, en) -> bool:
    return (idx in (None, "")) and (st is None) and (en is None)


def _is_blank_break_fields(label, st, dur) -> bool:
    return (st is None) and (dur in (None, ""))


class SchoolSettingsForm(forms.ModelForm):
    logo = forms.ImageField(label="شعار المدرسة", required=False)

    class Meta:
        model = SchoolSettings
        fields = [
            "name",
            "theme",
            "refresh_interval_sec",
            "standby_scroll_speed",
            "periods_scroll_speed",
        ]
        widgets = {
            "theme": forms.Select(),
            "refresh_interval_sec": forms.NumberInput(attrs={"min": 5, "step": 5}),
            "standby_scroll_speed": forms.NumberInput(attrs={"min": 0.05, "max": 5.0, "step": 0.05}),
            "periods_scroll_speed": forms.NumberInput(attrs={"min": 0.05, "max": 5.0, "step": 0.05}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        logo_file = self.cleaned_data.get("logo")
        if logo_file and instance.school:
            instance.school.logo = logo_file
            instance.school.save()
        if commit:
            instance.save()
        return instance


class DayScheduleForm(forms.ModelForm):
    class Meta:
        model = DaySchedule
        fields = ["periods_count"]

    def clean_periods_count(self):
        v = self.cleaned_data["periods_count"]
        if v is None or v < 0:
            raise ValidationError("عدد الحصص يجب أن يكون رقمًا غير سالب.")
        return v


class PeriodForm(forms.ModelForm):
    class Meta:
        model = Period
        fields = ["index", "starts_at", "ends_at"]
        widgets = {
            "starts_at": forms.TimeInput(attrs={"type": "time", "step": 60}),
            "ends_at": forms.TimeInput(attrs={"type": "time", "step": 60}),
        }

    def clean(self):
        cleaned = super().clean()

        if _is_checked(self.data.get(f"{self.prefix}-DELETE")):
            self._is_marked_delete = True
            self.instance._skip_cross_validation = True
            return cleaned

        st = cleaned.get("starts_at")
        en = cleaned.get("ends_at")
        idx = cleaned.get("index")

        if _is_blank_period_fields(idx, st, en):
            self._is_blank_row = True
            self.instance._skip_cross_validation = True
            return cleaned

        if st is None:
            self.add_error("starts_at", "هذا الحقل مطلوب.")
        if en is None:
            self.add_error("ends_at", "هذا الحقل مطلوب.")
        if idx in (None, ""):
            self.add_error("index", "هذا الحقل مطلوب.")
        elif isinstance(idx, int) and idx < 1:
            self.add_error("index", "رقم الحصة يجب أن يبدأ من 1.")

        if st is not None and en is not None and en <= st:
            self.add_error("ends_at", "وقت نهاية الحصة يجب أن يكون بعد وقت بدايتها.")

        if self.errors:
            self.instance._skip_cross_validation = True

        return cleaned


class BreakForm(forms.ModelForm):
    class Meta:
        model = Break
        fields = ["label", "starts_at", "duration_min"]
        widgets = {
            "starts_at": forms.TimeInput(attrs={"type": "time", "step": 60}),
        }

    def clean(self):
        cleaned = super().clean()

        if _is_checked(self.data.get(f"{self.prefix}-DELETE")):
            self._is_marked_delete = True
            self.instance._skip_cross_validation = True
            return cleaned

        label = cleaned.get("label")
        st = cleaned.get("starts_at")
        dur = cleaned.get("duration_min")

        if _is_blank_break_fields(label, st, dur):
            self._is_blank_row = True
            self.instance._skip_cross_validation = True
            return cleaned

        if st is None:
            self.add_error("starts_at", "هذا الحقل مطلوب.")
        if dur is None or dur <= 0:
            self.add_error("duration_min", "مدة الفسحة يجب أن تكون رقمًا موجبًا بالدقائق.")

        if self.errors:
            self.instance._skip_cross_validation = True

        return cleaned


class PeriodInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()

        parent: DaySchedule = self.instance
        target_count = int(parent.periods_count or 0)

        errors_added = 0
        periods = []
        seen_indexes: dict[int, forms.ModelForm] = {}

        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            cd = form.cleaned_data

            if cd.get("DELETE") or getattr(form, "_is_marked_delete", False):
                form.instance._skip_cross_validation = True
                continue

            st, en, idx = cd.get("starts_at"), cd.get("ends_at"), cd.get("index")

            if getattr(form, "_is_blank_row", False) or _is_blank_period_fields(idx, st, en):
                form.instance._skip_cross_validation = True
                continue

            if form.errors:
                form.instance._skip_cross_validation = True
                errors_added += sum(len(v) for v in form.errors.values())
                continue

            if idx in seen_indexes:
                form.add_error("index", "رقم الحصة مكرر لهذا اليوم.")
                seen_indexes[idx].add_error("index", "رقم الحصة مكرر لهذا اليوم.")
                form.instance._skip_cross_validation = True
                seen_indexes[idx].instance._skip_cross_validation = True
                errors_added += 2
                continue

            seen_indexes[idx] = form
            periods.append({"label": f"الحصة {idx}", "start": st, "end": en, "form": form})

        breaks = []
        total_b = int(self.data.get("b-TOTAL_FORMS", 0) or 0)
        for i in range(total_b):
            if _is_checked(self.data.get(f"b-{i}-DELETE")):
                continue
            label = (self.data.get(f"b-{i}-label") or "").strip() or "فسحة"
            st = _parse_hhmm(self.data.get(f"b-{i}-starts_at"))
            dur_raw = self.data.get(f"b-{i}-duration_min")
            try:
                dur = int(dur_raw) if dur_raw not in (None, "") else None
            except ValueError:
                dur = None

            if _is_blank_break_fields(label, st, dur):
                continue

            if st and dur and dur > 0:
                end = (datetime.combine(datetime.today(), st) + timedelta(minutes=dur)).time()
                breaks.append({"label": f"الفسحة ({label})", "start": st, "end": end})

        count_periods = len(periods)
        if target_count > 0 and count_periods > target_count:
            raise ValidationError(
                f"عدد الحصص المدخلة ({count_periods}) أكبر من القيمة المحددة لليوم ({target_count}). "
                f"رجاءً احذف/عدّل الحصص الزائدة."
            )

        items = [{"kind": "p", **p} for p in periods] + [{"kind": "b", **b} for b in breaks]
        items.sort(key=lambda x: x["start"])

        for i in range(1, len(items)):
            prev, cur = items[i - 1], items[i]
            if cur["start"] < prev["end"]:
                msg_cur = f"تداخل مع {prev['label']} ({prev['start']}-{prev['end']})."
                msg_prev = f"يتداخل مع {cur['label']} ({cur['start']}-{cur['end']})."
                if cur["kind"] == "p":
                    cur["form"].add_error("starts_at", msg_cur)
                    cur["form"].instance._skip_cross_validation = True
                    errors_added += 1
                if prev["kind"] == "p":
                    prev["form"].add_error("ends_at", msg_prev)
                    prev["form"].instance._skip_cross_validation = True
                    errors_added += 1

        if errors_added > 0:
            raise ValidationError("تحقق من الأوقات: يوجد حقول ناقصة/مكررة أو تداخلات زمنية.")


PeriodFormSet = inlineformset_factory(
    parent_model=DaySchedule,
    model=Period,
    form=PeriodForm,
    formset=PeriodInlineFormSet,
    extra=0,
    can_delete=True,
    min_num=0,
    validate_min=True,
)

BreakFormSet = inlineformset_factory(
    parent_model=DaySchedule,
    model=Break,
    form=BreakForm,
    extra=0,
    can_delete=True,
    min_num=0,
    validate_min=True,
)


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ["title", "body", "level", "starts_at", "expires_at", "is_active"]
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }


class ExcellenceForm(forms.ModelForm):
    MAX_PHOTO_MB = 5

    class Meta:
        model = Excellence
        fields = ["teacher_name", "reason", "photo", "photo_url", "start_at", "end_at", "priority"]
        widgets = {
            "teacher_name": forms.TextInput(attrs={"maxlength": 100}),
            "reason": forms.TextInput(attrs={"maxlength": 200}),
            "start_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "end_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if hasattr(self.fields.get("photo"), "widget"):
            self.fields["photo"].widget.attrs.setdefault("accept", "image/*")

    def clean_photo(self):
        file = self.cleaned_data.get("photo")
        if not file:
            return file
        max_bytes = self.MAX_PHOTO_MB * 1024 * 1024
        size = getattr(file, "size", 0)
        if size and size > max_bytes:
            raise ValidationError(f"حجم الصورة يتجاوز {self.MAX_PHOTO_MB} م.ب.")
        return file

    def clean(self):
        cleaned = super().clean()
        start_at = cleaned.get("start_at")
        end_at = cleaned.get("end_at")
        if start_at and end_at and end_at <= start_at:
            raise ValidationError("وقت الانتهاء يجب أن يكون بعد وقت البداية.")
        return cleaned


class StandbyForm(forms.ModelForm):
    class_name = forms.ModelChoiceField(queryset=SchoolClass.objects.all(), label="الفصل")
    teacher_name = forms.ModelChoiceField(queryset=Teacher.objects.all(), label="اسم المعلم")

    class Meta:
        model = StandbyAssignment
        fields = ["date", "period_index", "class_name", "teacher_name", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.class_name = self.cleaned_data["class_name"].name
        instance.teacher_name = self.cleaned_data["teacher_name"].name
        if commit:
            instance.save()
        return instance


class DisplayScreenForm(forms.ModelForm):
    class Meta:
        model = DisplayScreen
        fields = ["name", "is_active"]


class LessonForm(forms.ModelForm):
    class Meta:
        model = ClassLesson
        fields = ["school_class", "weekday", "period_index", "subject", "teacher", "is_active"]
        widgets = {
            "weekday": forms.Select(choices=WEEKDAYS),
        }
