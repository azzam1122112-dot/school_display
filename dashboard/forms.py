# dashboard/forms.py
from __future__ import annotations

from datetime import datetime, timedelta
import logging

from django import forms
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms import BaseInlineFormSet, inlineformset_factory

from schedule.models import (
    SchoolSettings,
    DaySchedule,
    Period,
    Break,
    ClassLesson,
    WEEKDAYS,
    SchoolClass,
    Teacher,
    Subject,
)
from notices.models import Announcement, Excellence
from standby.models import StandbyAssignment
from core.models import DisplayScreen, School, UserProfile, SubscriptionPlan
from subscriptions.models import SchoolSubscription
logger = logging.getLogger(__name__)

UserModel = get_user_model()


# ========================
# دوال مساعدة داخلية
# ========================

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


def _get_profile(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


# ========================
# إعدادات المدرسة
# ========================

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

            # ✅ حد أدنى 15 ثانية + خطوة 1 (أوضح للمستخدم)
            "refresh_interval_sec": forms.NumberInput(attrs={"min": 15, "step": 1}),

            # ✅ حد أدنى 0.5 + خطوة 0.1 (قيم عملية للعرض)
            "standby_scroll_speed": forms.NumberInput(attrs={"min": 0.5, "max": 5.0, "step": 0.1}),
            "periods_scroll_speed": forms.NumberInput(attrs={"min": 0.5, "max": 5.0, "step": 0.1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # تأكيد attrs حتى لو تغيّرت الـ widgets أو تم override من مكان آخر
        if "refresh_interval_sec" in self.fields:
            self.fields["refresh_interval_sec"].widget.attrs.update({"min": "15", "step": "1"})
            self.fields["refresh_interval_sec"].help_text = (
                "الحد الأدنى 15 ثانية. (موصى به 20–30 لتجربة ثابتة وتقليل الضغط)"
            )

        for fname in ["standby_scroll_speed", "periods_scroll_speed"]:
            if fname in self.fields:
                self.fields[fname].widget.attrs.update({"min": "0.5", "max": "5.0", "step": "0.1"})
                # تنبيه قيم مفيدة للمستخدم
                if fname == "standby_scroll_speed":
                    self.fields[fname].help_text = "الحد الأدنى 0.5. قيم مقترحة: 0.5 – 1.2"
                else:
                    self.fields[fname].help_text = "الحد الأدنى 0.5. قيم مقترحة: 0.5 – 1.0"

    # =========================
    # ✅ Server-side validation
    # =========================
    def clean_refresh_interval_sec(self):
        v = self.cleaned_data.get("refresh_interval_sec")
        if v is None:
            return v
        try:
            v_int = int(v)
        except (TypeError, ValueError):
            raise forms.ValidationError("الرجاء إدخال رقم صحيح لفاصل التحديث.")
        if v_int < 15:
            raise forms.ValidationError("الحد الأدنى لفاصل تحديث الشاشة هو 15 ثانية.")
        return v_int

    def clean_standby_scroll_speed(self):
        v = self.cleaned_data.get("standby_scroll_speed")
        if v is None:
            return v
        try:
            v_f = float(v)
        except (TypeError, ValueError):
            raise forms.ValidationError("الرجاء إدخال رقم صحيح لسرعة تمرير الانتظار.")
        if v_f < 0.5:
            raise forms.ValidationError("الحد الأدنى لسرعة تمرير الانتظار هو 0.5.")
        return v_f

    def clean_periods_scroll_speed(self):
        v = self.cleaned_data.get("periods_scroll_speed")
        if v is None:
            return v
        try:
            v_f = float(v)
        except (TypeError, ValueError):
            raise forms.ValidationError("الرجاء إدخال رقم صحيح لسرعة تمرير جدول الحصص.")
        if v_f < 0.5:
            raise forms.ValidationError("الحد الأدنى لسرعة تمرير جدول الحصص هو 0.5.")
        return v_f

    def save(self, commit=True):
        """
        نحفظ الإعدادات، ولو تم رفع شعار جديد نحدّث school.logo بأمان.
        """
        instance: SchoolSettings = super().save(commit=False)
        logo_file = self.cleaned_data.get("logo")

        if logo_file and getattr(instance, "school_id", None):
            try:
                # تحديث شعار المدرسة المرتبطة
                instance.school.logo = logo_file
                instance.school.save(update_fields=["logo"])
            except Exception as exc:
                # لا نكسر الحفظ لو فشل تحديث الشعار لأي سبب
                logger.exception("Failed to update school logo for school_id=%s: %s", instance.school_id, exc)

        if commit:
            instance.save()
            # إذا كان عندك many-to-many في الفورم مستقبلًا
            self.save_m2m()

        return instance


# ========================
# اليوم والجدول الزمني
# ========================

class DayScheduleForm(forms.ModelForm):
    class Meta:
        model = DaySchedule
        fields = ["periods_count"]

    def clean_periods_count(self):
        v = self.cleaned_data.get("periods_count")
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

        # حذف الصف
        if _is_checked(self.data.get(f"{self.prefix}-DELETE")):
            self._is_marked_delete = True
            self.instance._skip_cross_validation = True
            return cleaned

        st = cleaned.get("starts_at")
        en = cleaned.get("ends_at")
        idx = cleaned.get("index")

        # صف فارغ
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
    """
    يتحقق من:
    - عدد الحصص لا يتجاوز العدد المحدد في اليوم.
    - عدم تكرار أرقام الحصص.
    - عدم وجود تداخل زمني بين الحصص والفسح.
    """

    def clean(self):
        super().clean()

        parent: DaySchedule = self.instance
        target_count = int(getattr(parent, "periods_count", 0) or 0)

        errors_added = 0
        periods = []
        seen_indexes: dict[int, forms.ModelForm] = {}

        # جمع الحصص
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

        # جمع الفسح من بيانات POST (فورم آخر)
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

        # التحقق من العدد الأقصى
        count_periods = len(periods)
        if target_count > 0 and count_periods > target_count:
            raise ValidationError(
                f"عدد الحصص المدخلة ({count_periods}) أكبر من القيمة المحددة لليوم ({target_count}). "
                f"رجاءً احذف/عدّل الحصص الزائدة."
            )

        # ترتيب كل العناصر زمنيًا وفحص التداخل
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
            raise ValidationError("تحقّق من الأوقات: يوجد حقول ناقصة/مكررة أو تداخلات زمنية.")


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


# ========================
# الإعلانات والتميز
# ========================

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
        fields = [
            "teacher_name",
            "reason",
            "photo",
            "photo_url",
            "start_at",
            "end_at",
            "priority",
        ]
        widgets = {
            "teacher_name": forms.TextInput(attrs={"maxlength": 100}),
            "reason": forms.TextInput(attrs={"maxlength": 200}),
            "start_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "end_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "photo" in self.fields and hasattr(self.fields["photo"].widget, "attrs"):
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


# ========================
# حصص الانتظار
# ========================

class StandbyForm(forms.ModelForm):
    class_name = forms.ModelChoiceField(queryset=SchoolClass.objects.none(), label="الفصل")
    teacher_name = forms.ModelChoiceField(queryset=Teacher.objects.none(), label="اسم المعلم/ـة")

    class Meta:
        model = StandbyAssignment
        fields = ["date", "period_index", "class_name", "teacher_name", "notes"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        school = kwargs.pop("school", None)
        super().__init__(*args, **kwargs)
        self._school = school

        if school is not None:
            self.fields["class_name"].queryset = SchoolClass.objects.filter(
                settings__school=school
            ).order_by("name")
            self.fields["teacher_name"].queryset = Teacher.objects.filter(
                school=school
            ).order_by("name")
        else:
            self.fields["class_name"].queryset = SchoolClass.objects.none()
            self.fields["teacher_name"].queryset = Teacher.objects.none()

    def save(self, commit=True):
        instance = super().save(commit=False)
        class_obj = self.cleaned_data["class_name"]
        teacher_obj = self.cleaned_data["teacher_name"]
        instance.class_name = class_obj.name
        instance.teacher_name = teacher_obj.name
        if getattr(self, "_school", None) is not None:
            instance.school = self._school
        if commit:
            instance.save()
        return instance


# ========================
# شاشات العرض والحصص
# ========================

class DisplayScreenForm(forms.ModelForm):
    class Meta:
        model = DisplayScreen
        fields = ["name", "is_active"]


class LessonForm(forms.ModelForm):
    class Meta:
        model = ClassLesson
        fields = [
            "school_class",
            "weekday",
            "period_index",
            "subject",
            "teacher",
            "is_active",
        ]
        widgets = {
            "weekday": forms.Select(choices=WEEKDAYS),
        }

    def __init__(self, *args, **kwargs):
        school = kwargs.pop("school", None)
        super().__init__(*args, **kwargs)

        if school is not None:
            self.fields["school_class"].queryset = SchoolClass.objects.filter(
                settings__school=school
            ).order_by("name")
            self.fields["subject"].queryset = Subject.objects.filter(
                school=school
            ).order_by("name")
            self.fields["teacher"].queryset = Teacher.objects.filter(
                school=school
            ).order_by("name")
        else:
            self.fields["school_class"].queryset = SchoolClass.objects.none()
            self.fields["subject"].queryset = Subject.objects.none()
            self.fields["teacher"].queryset = Teacher.objects.none()


# =========================
# نماذج لوحة إدارة النظام (SaaS Admin)
# =========================

class SchoolForm(forms.ModelForm):
    class Meta:
        model = School
        fields = ["name", "slug", "logo", "is_active"]
        labels = {
            "name": "اسم المدرسة",
            "slug": "الرابط (slug)",
            "logo": "شعار المدرسة",
            "is_active": "مدرسة مفعّلة",
        }
        widgets = {"logo": forms.ClearableFileInput()}


class SchoolSubscriptionForm(forms.ModelForm):
    """
    إدارة اشتراك المدرسة بناءً على موديل SchoolSubscription:
    fields = [school, plan, starts_at, ends_at, status, notes]
    """

    class Meta:
        model = SchoolSubscription
        fields = ["school", "plan", "starts_at", "ends_at", "status", "notes"]
        labels = {
            "school": "المدرسة",
            "plan": "الخطة",
            "starts_at": "تاريخ بداية الاشتراك",
            "ends_at": "تاريخ نهاية الاشتراك",
            "status": "حالة الاشتراك",
            "notes": "ملاحظات",
        }
        widgets = {
            "starts_at": forms.DateInput(attrs={"type": "date"}),
            "ends_at": forms.DateInput(attrs={"type": "date"}),
            "status": forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["school"].queryset = School.objects.all().order_by("name")
        self.fields["plan"].queryset = SubscriptionPlan.objects.all().order_by("name")

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("starts_at")
        end = cleaned.get("ends_at")
        if start and end and end < start:
            raise ValidationError("تاريخ النهاية يجب أن يكون بعد تاريخ البداية.")
        return cleaned


# =========================
# نماذج المستخدمين (ربط المستخدم بالمدارس + active_school)
# =========================

class SystemUserCreateForm(UserCreationForm):
    """
    إنشاء مستخدم جديد + ربطه بالمدارس وتعيين مدرسة نشطة.
    يعتمد UserCreationForm للاستفادة من تحققات كلمة المرور.
    """
    schools = forms.ModelMultipleChoiceField(
        queryset=School.objects.all().order_by("name"),
        required=True,
        label="المدارس",
        help_text="المدارس التي يرتبط بها هذا المستخدم.",
        widget=forms.SelectMultiple(
            attrs={"class": "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"}
        ),
    )
    active_school = forms.ModelChoiceField(
        queryset=School.objects.all().order_by("name"),
        required=False,
        label="المدرسة النشطة",
        help_text="اختياري: لو لم تحدد سيتم اختيار أول مدرسة مرتبطة.",
        widget=forms.Select(
            attrs={"class": "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"}
        ),
    )
    mobile = forms.CharField(
        label="رقم الجوال",
        required=False,
        max_length=20,
        widget=forms.TextInput(
            attrs={"class": "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"}
        ),
    )

    class Meta(UserCreationForm.Meta):
        model = UserModel
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "mobile",
            "is_active",
            "is_staff",
            "is_superuser",
        ]
        labels = {
            "username": "اسم المستخدم",
            "email": "البريد الإلكتروني",
            "first_name": "الاسم الأول",
            "last_name": "اسم العائلة",
            "is_active": "حساب نشط",
            "is_staff": "صلاحيات موظف (staff)",
            "is_superuser": "مدير نظام (superuser)",
        }

    def clean(self):
        cleaned = super().clean()
        schools = cleaned.get("schools")
        active_school = cleaned.get("active_school")
        if active_school and schools and active_school not in schools:
            raise ValidationError("المدرسة النشطة يجب أن تكون ضمن المدارس المرتبطة.")
        return cleaned

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=commit)
        profile = _get_profile(user)

        schools = self.cleaned_data.get("schools")
        profile.schools.set(schools)

        active_school = self.cleaned_data.get("active_school")
        if active_school:
            profile.active_school = active_school
        else:
            profile.active_school = profile.schools.order_by("id").first()

        profile.mobile = self.cleaned_data.get("mobile")
        profile.save()
        return user


class SystemUserUpdateForm(forms.ModelForm):
    """
    تعديل بيانات المستخدم + إدارة المدارس + تعيين active_school + تغيير كلمة المرور اختياريًا.
    """
    schools = forms.ModelMultipleChoiceField(
        queryset=School.objects.all().order_by("name"),
        required=False,
        label="المدارس",
        help_text="المدارس المرتبط بها المستخدم.",
        widget=forms.SelectMultiple(
            attrs={"class": "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"}
        ),
    )
    active_school = forms.ModelChoiceField(
        queryset=School.objects.all().order_by("name"),
        required=False,
        label="المدرسة النشطة",
        help_text="اختياري: لو لم تحدد سيتم اختيار أول مدرسة مرتبطة.",
        widget=forms.Select(
            attrs={"class": "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"}
        ),
    )
    mobile = forms.CharField(
        label="رقم الجوال",
        required=False,
        max_length=20,
        widget=forms.TextInput(
            attrs={"class": "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"}
        ),
    )

    new_password1 = forms.CharField(
        label="كلمة المرور الجديدة",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        required=False,
        help_text="اترك الحقلين فارغين إذا لا تريد تغيير كلمة المرور."
    )
    new_password2 = forms.CharField(
        label="تأكيد كلمة المرور الجديدة",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        required=False,
    )

    class Meta:
        model = UserModel
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "mobile",
            "is_active",
            "is_staff",
            "is_superuser",
        ]
        labels = {
            "username": "اسم المستخدم",
            "email": "البريد الإلكتروني",
            "first_name": "الاسم الأول",
            "last_name": "اسم العائلة",
            "is_active": "حساب نشط",
            "is_staff": "صلاحيات موظف (staff)",
            "is_superuser": "مدير نظام (superuser)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if getattr(self.instance, "pk", None):
            profile = UserProfile.objects.filter(user=self.instance).first()
            if profile:
                self.fields["schools"].initial = list(profile.schools.all())
                self.fields["active_school"].initial = profile.active_school_id
                self.fields["mobile"].initial = profile.mobile

    def clean(self):
        cleaned = super().clean()

        schools = cleaned.get("schools")
        active_school = cleaned.get("active_school")
        if active_school and schools and active_school not in schools:
            raise ValidationError("المدرسة النشطة يجب أن تكون ضمن المدارس المرتبطة.")

        p1 = cleaned.get("new_password1")
        p2 = cleaned.get("new_password2")
        if p1 or p2:
            if not p1 or not p2:
                raise ValidationError("لابد من إدخال كلمة المرور الجديدة وتأكيدها.")
            if p1 != p2:
                raise ValidationError("كلمتا المرور غير متطابقتين.")
            if len(p1) < 8:
                raise ValidationError("يجب أن تكون كلمة المرور ٨ أحرف على الأقل.")

        return cleaned

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)

        new_password = self.cleaned_data.get("new_password1")
        if new_password:
            user.set_password(new_password)

        if commit:
            user.save()

        profile = _get_profile(user)

        schools = self.cleaned_data.get("schools")
        if schools is not None:
            profile.schools.set(schools)

        active_school = self.cleaned_data.get("active_school")
        if active_school:
            profile.active_school = active_school
        else:
            profile.active_school = profile.schools.order_by("id").first()

        profile.mobile = self.cleaned_data.get("mobile")

        # ضمان: لو active_school ليست ضمن المدارس بعد التعديل
        if profile.active_school_id and profile.schools.filter(id=profile.active_school_id).exists() is False:
            profile.active_school = profile.schools.order_by("id").first()

        profile.save()
        return user


from core.models import SupportTicket

class SubscriptionPlanForm(forms.ModelForm):
    class Meta:
        model = SubscriptionPlan
        fields = "__all__"
        widgets = {
            "name": forms.TextInput(attrs={"class": "w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500"}),
            "code": forms.TextInput(attrs={"class": "w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500"}),
            "price": forms.NumberInput(attrs={"class": "w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500"}),
            "max_users": forms.NumberInput(attrs={"class": "w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500"}),
            "max_screens": forms.NumberInput(attrs={"class": "w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500"}),
            "max_schools": forms.NumberInput(attrs={"class": "w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500"}),
            "sort_order": forms.NumberInput(attrs={"class": "w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500"}),
            "is_active": forms.CheckboxInput(attrs={"class": "rounded border-slate-300 text-blue-600 focus:ring-blue-500"}),
        }

from core.models import SupportTicket, TicketComment

class TicketCommentForm(forms.ModelForm):
    class Meta:
        model = TicketComment
        fields = ["message"]
        widgets = {
            "message": forms.Textarea(attrs={"rows": 3, "class": "w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500", "placeholder": "أضف ردك هنا..."}),
        }

class SupportTicketForm(forms.ModelForm):
    class Meta:
        model = SupportTicket
        fields = ["subject", "message", "priority"]
        widgets = {
            "subject": forms.TextInput(attrs={"class": "w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500"}),
            "message": forms.Textarea(attrs={"class": "w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500", "rows": 4}),
            "priority": forms.Select(attrs={"class": "w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500"}),
        }


class CustomerSupportTicketForm(forms.ModelForm):
    school_name = forms.CharField(
        label="اسم المدرسة",
        required=False,
        widget=forms.TextInput(attrs={"class": "w-full rounded-lg border-slate-300 bg-slate-100 text-slate-500", "readonly": "readonly"})
    )
    admin_name = forms.CharField(
        label="اسم المسؤول",
        required=False,
        widget=forms.TextInput(attrs={"class": "w-full rounded-lg border-slate-300 bg-slate-100 text-slate-500", "readonly": "readonly"})
    )
    mobile_number = forms.CharField(
        label="رقم الجوال",
        required=False,
        widget=forms.TextInput(attrs={"class": "w-full rounded-lg border-slate-300 bg-slate-100 text-slate-500", "readonly": "readonly"})
    )

    class Meta:
        model = SupportTicket
        fields = ["subject", "message"]
        widgets = {
            "subject": forms.TextInput(attrs={"class": "w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500"}),
            "message": forms.Textarea(attrs={"class": "w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500", "rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            profile = getattr(user, 'profile', None)
            if profile and profile.active_school:
                self.fields['school_name'].initial = profile.active_school.name
            
            self.fields['admin_name'].initial = user.get_full_name() or user.username
            
            if profile and profile.mobile:
                self.fields['mobile_number'].initial = profile.mobile
