# dashboard/forms.py
from __future__ import annotations

from datetime import datetime, timedelta
import os
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
    DutyAssignment,
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
from subscriptions.models import SchoolSubscription, SubscriptionScreenAddon, SubscriptionRequest
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
            "featured_panel",
            "theme",
            "standby_scroll_speed",
            "periods_scroll_speed",
            "display_accent_color",
            "test_mode_weekday_override",
        ]
        widgets = {
            "featured_panel": forms.Select(),
            "theme": forms.Select(),

            # ✅ حد أدنى 0.5 + خطوة 0.1 (قيم عملية للعرض)
            "standby_scroll_speed": forms.NumberInput(attrs={"min": 0.5, "max": 5.0, "step": 0.1}),
            "periods_scroll_speed": forms.NumberInput(attrs={"min": 0.5, "max": 5.0, "step": 0.1}),

            # اختيار لون HEX (يفضل عبر color picker)
            "display_accent_color": forms.TextInput(
                attrs={
                    "type": "color",
                    "title": "اختر لون شاشة العرض",
                }
            ),
            
            "test_mode_weekday_override": forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        # استخراج المستخدم إذا تم تمريره (من الـ view)
        self.request_user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        # تأكيد attrs حتى لو تغيّرت الـ widgets أو تم override من مكان آخر
        for fname in ["standby_scroll_speed", "periods_scroll_speed"]:
            if fname in self.fields:
                self.fields[fname].widget.attrs.update({"min": "0.5", "max": "5.0", "step": "0.1"})
                # تنبيه قيم مفيدة للمستخدم
                if fname == "standby_scroll_speed":
                    self.fields[fname].help_text = "الحد الأدنى 0.5. قيم مقترحة: 0.5 – 1.2. كلما زادت القيمة زادت السرعة."
                else:
                    self.fields[fname].help_text = "الحد الأدنى 0.5. قيم مقترحة: 0.5 – 1.0. كلما زادت القيمة زادت السرعة."

        if "display_accent_color" in self.fields:
            self.fields["display_accent_color"].help_text = (
                "اختياري: اختر لونًا رئيسياً لشاشة العرض. اتركه فارغًا لاستخدام ألوان الثيم."
            )
        
        # ✅ وضع الاختبار: للسوبر أدمن فقط
        if "test_mode_weekday_override" in self.fields:
            # إذا لم يكن سوبر أدمن، أخفِ الحقل
            if self.request_user and not self.request_user.is_superuser:
                del self.fields["test_mode_weekday_override"]
            else:
                self.fields["test_mode_weekday_override"].help_text = (
                    "<strong style='color: #d97706;'>⚠️ للسوبر أدمن فقط:</strong> "
                    "لتشغيل الشاشة في يوم إجازة للاختبار، حدد اليوم المراد محاكاته "
                    "(مثلاً: لو اليوم خميس وتريد اختبار جدول الأحد، اختر 'الأحد'). "
                    "<br><strong>لا تنسَ إلغاء التفعيل بعد الاختبار!</strong>"
                )
                self.fields["test_mode_weekday_override"].label = "🧪 وضع الاختبار: محاكاة يوم"
                self.fields["test_mode_weekday_override"].required = False

    # =========================
    # ✅ Server-side validation
    # =========================
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
        widgets = {
            "periods_count": forms.NumberInput(attrs={
                "class": "form-input w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500 text-slate-800 font-bold bg-white text-center",
                "min": "0"
            })
        }

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
            "index": forms.NumberInput(attrs={
                "class": "form-input w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500 text-slate-800 font-bold bg-white text-center placeholder-slate-400",
                "placeholder": "#"
            }),
            "starts_at": forms.TimeInput(attrs={
                "type": "time", 
                "step": 60,
                "class": "form-input w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500 text-slate-800 font-medium bg-white ltr:text-right"
            }),
            "ends_at": forms.TimeInput(attrs={
                "type": "time", 
                "step": 60,
                "class": "form-input w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500 text-slate-800 font-medium bg-white ltr:text-right"
            }),
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

        # When the row is valid, the inline formset performs cross-validation
        # against the submitted periods + breaks. Skipping model-level DB overlap
        # checks prevents false failures against still-old rows during save.
        if not getattr(self, "_is_blank_row", False) and not getattr(self, "_is_marked_delete", False):
            if not self.errors:
                self.instance._skip_cross_validation = True

        return cleaned


class BreakForm(forms.ModelForm):
    class Meta:
        model = Break
        fields = ["label", "starts_at", "duration_min"]
        widgets = {
            "label": forms.TextInput(attrs={
                "class": "form-input w-full rounded-lg border-slate-300 focus:border-purple-500 focus:ring-purple-500 text-slate-800 font-medium bg-white placeholder-slate-400",
                "placeholder": "مثار: فسحة الصلاة"
            }),
            "starts_at": forms.TimeInput(attrs={
                "type": "time", 
                "step": 60,
                "class": "form-input w-full rounded-lg border-slate-300 focus:border-purple-500 focus:ring-purple-500 text-slate-800 font-medium bg-white ltr:text-right"
            }),
            "duration_min": forms.NumberInput(attrs={
                "class": "form-input w-full rounded-lg border-slate-300 focus:border-purple-500 focus:ring-purple-500 text-slate-800 font-medium bg-white text-center",
                "min": "1"
            }),
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

        # Same rationale as PeriodForm.clean(): the dashboard validates overlaps
        # using the POSTed rows, so skip DB overlap checks during batch save.
        if not getattr(self, "_is_blank_row", False) and not getattr(self, "_is_marked_delete", False):
            if not self.errors:
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
        if "teacher_name" in self.fields:
            self.fields["teacher_name"].label = "اسم المتميز/ة"
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
    class_name = forms.ModelChoiceField(
        queryset=SchoolClass.objects.none(),
        label="الفصل",
        required=True,
        empty_label="— اختر الفصل —"
    )
    # ✅ تحويل teacher_name من CharField إلى ModelChoiceField (dropdown)
    teacher = forms.ModelChoiceField(
        queryset=Teacher.objects.none(),
        label="اسم المعلم/ـة",
        required=True,
        empty_label="— اختر المعلم/ـة —",
        help_text="اختر المعلم/ـة من القائمة",
        widget=forms.Select(attrs={
            'class': 'form-select',
            'data-placeholder': 'اختر المعلم/ـة'
        })
    )

    class Meta:
        model = StandbyAssignment
        # ✅ استبعاد teacher_name من fields لأننا نستخدم حقل مخصص "teacher"
        fields = ["date", "period_index", "class_name", "notes"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        school = kwargs.pop("school", None)
        super().__init__(*args, **kwargs)
        self._school = school

        if school is not None:
            self.fields["class_name"].queryset = SchoolClass.objects.filter(
                settings__school=school
            ).order_by("name")
            # ✅ تحميل قائمة المعلمين من نفس المدرسة
            self.fields["teacher"].queryset = Teacher.objects.filter(
                school=school
            ).order_by("name")
        else:
            self.fields["class_name"].queryset = SchoolClass.objects.none()
            self.fields["teacher"].queryset = Teacher.objects.none()

        # ✅ عند التعديل، نحمل المعلم الحالي من teacher_name
        if self.instance and self.instance.pk and self.instance.teacher_name:
            try:
                existing_teacher = Teacher.objects.filter(
                    school=school,
                    name=self.instance.teacher_name
                ).first()
                if existing_teacher:
                    self.initial['teacher'] = existing_teacher.pk
            except Exception:
                pass

    def save(self, commit=True):
        instance = super().save(commit=False)
        class_obj = self.cleaned_data["class_name"]
        instance.class_name = class_obj.name
        
        # ✅ تحويل Teacher object إلى teacher_name string
        teacher_obj = self.cleaned_data.get("teacher")
        if teacher_obj:
            instance.teacher_name = teacher_obj.name
        else:
            instance.teacher_name = ""
            
        if getattr(self, "_school", None) is not None:
            instance.school = self._school
        if commit:
            instance.save()
        return instance


# ========================
# الإشراف والمناوبة
# ========================

class DutyAssignmentForm(forms.ModelForm):
    teacher = forms.ModelChoiceField(
        queryset=Teacher.objects.none(),
        label="اسم المعلم/ـة",
        empty_label="— اختر المعلم/ـة —",
        help_text="اختر المعلم/ـة من القائمة",
        widget=forms.Select(attrs={
            'class': 'form-select',
            'data-placeholder': 'اختر المعلم/ـة'
        }),
        required=False  # لأن teacher_name في Model هو CharField
    )
    
    def __init__(self, *args, **kwargs):
        self._school = kwargs.pop("school", None)
        super().__init__(*args, **kwargs)

        # تحميل المعلمين الخاصين بالمدرسة
        if self._school:
            self.fields["teacher"].queryset = Teacher.objects.filter(
                school=self._school
            ).order_by("name")
        else:
            self.fields["teacher"].queryset = Teacher.objects.none()
        
        # إذا كان هناك قيمة موجودة في teacher_name، نحاول إيجاد المعلم
        if self.instance and self.instance.pk and self.instance.teacher_name:
            try:
                teacher = Teacher.objects.get(
                    school=self._school,
                    name=self.instance.teacher_name
                )
                self.initial['teacher'] = teacher
            except (Teacher.DoesNotExist, Teacher.MultipleObjectsReturned):
                pass
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        # نحوّل Teacher object إلى اسم نصي
        teacher = self.cleaned_data.get('teacher')
        if teacher:
            instance.teacher_name = teacher.name
        if commit:
            instance.save()
        return instance

    class Meta:
        model = DutyAssignment
        fields = [
            "date",
            "teacher",  # نستخدم teacher بدلاً من teacher_name في Form
            "duty_type",
            "location",
            "priority",
            "is_active",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "location": forms.TextInput(attrs={"maxlength": 120, "class": "form-control"}),
            "priority": forms.NumberInput(attrs={"class": "form-control"}),
        }


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

    payment_method = forms.ChoiceField(
        label="طريقة الدفع",
        required=False,
        choices=[
            ("", "— اختر —"),
            ("bank_transfer", "تحويل"),
            ("payment_link", "رابط دفع"),
            ("tamara", "تمارا"),
        ],
        widget=forms.Select(),
        help_text="يُطلب فقط عند إنشاء اشتراك مدفوع (غير مجاني).",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["school"].queryset = School.objects.all().order_by("name")
        self.fields["plan"].queryset = SubscriptionPlan.objects.all().order_by("name")

        # عند تعديل اشتراك سابق: عبّئ طريقة الدفع من آخر عملية دفع (إن وجدت)
        try:
            if getattr(self.instance, "pk", None) and "payment_method" in self.fields:
                from subscriptions.models import SubscriptionPaymentOperation

                op = (
                    SubscriptionPaymentOperation.objects.filter(
                        school=getattr(self.instance, "school", None),
                        subscription=self.instance,
                    )
                    .order_by("-created_at", "-id")
                    .first()
                )
                if op is not None and getattr(op, "method", None):
                    self.fields["payment_method"].initial = op.method
        except Exception:
            pass

        # المطلوب: منع إدخال/تعديل تاريخ النهاية (يُحسب تلقائيًا من مدة الباقة).
        if "ends_at" in self.fields:
            self.fields["ends_at"].required = False
            self.fields["ends_at"].disabled = True
            self.fields["ends_at"].help_text = (
                "يتم حساب تاريخ النهاية تلقائيًا من مدة الباقة عند الحفظ."
            )
            self.fields["ends_at"].widget.attrs.update(
                {
                    "readonly": "readonly",
                    "disabled": "disabled",
                    "aria-disabled": "true",
                }
            )

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("starts_at")
        end = cleaned.get("ends_at")
        if start and end and end < start:
            raise ValidationError("تاريخ النهاية يجب أن يكون بعد تاريخ البداية.")

        # في إضافة اشتراك يدويًا: نطلب طريقة الدفع للخطط المدفوعة فقط.
        plan = cleaned.get("plan")
        payment_method = (cleaned.get("payment_method") or "").strip()
        is_create = not getattr(self.instance, "pk", None)
        try:
            plan_price = getattr(plan, "price", 0) or 0
        except Exception:
            plan_price = 0

        # الباقة المجانية (السعر 0) لا نطلب طريقة دفع.
        if is_create and plan is not None:
            try:
                if float(plan_price) > 0 and not payment_method:
                    raise ValidationError("الرجاء تحديد طريقة الدفع للاشتراك المدفوع.")
            except Exception:
                # إذا تعذر تحويل السعر لرقم، لا نكسر النموذج
                pass

        return cleaned


class SubscriptionScreenAddonForm(forms.ModelForm):
    class Meta:
        model = SubscriptionScreenAddon
        fields = [
            "subscription",
            "screens_added",
            "pricing_cycle",
            "validity_days",
            "pricing_strategy",
            "bundle_price",
            "unit_price",
            "starts_at",
            "ends_at",
            "status",
            "notes",
        ]
        labels = {
            "subscription": "الاشتراك",
            "screens_added": "عدد الشاشات المضافة",
            "pricing_cycle": "دورة تسعير الإضافة",
            "validity_days": "مدة الصلاحية (أيام)",
            "pricing_strategy": "طريقة التسعير",
            "bundle_price": "سعر الإضافة للفترة",
            "unit_price": "سعر للشاشة",
            "starts_at": "بداية الإضافة",
            "ends_at": "نهاية الإضافة",
            "status": "الحالة",
            "notes": "ملاحظات",
        }
        widgets = {
            "starts_at": forms.DateInput(attrs={"type": "date"}),
            "ends_at": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subscription"].queryset = (
            SchoolSubscription.objects.select_related("school", "plan")
            .order_by("-starts_at", "-id")
        )


# =========================
# طلبات الاشتراك/التجديد (مستخدم المدرسة)
# =========================

class _ReceiptImageValidationMixin:
    receipt_max_size_bytes = 5 * 1024 * 1024
    receipt_allowed_exts = {".jpg", ".jpeg", ".png", ".webp"}

    def _validate_receipt_image(self, file_obj):
        if not file_obj:
            raise ValidationError("الرجاء إرفاق صورة الإيصال.")

        # content-type (best-effort)
        content_type = getattr(file_obj, "content_type", "") or ""
        if content_type and not content_type.lower().startswith("image/"):
            raise ValidationError("الملف المرفوع يجب أن يكون صورة فقط.")

        # extension
        ext = os.path.splitext(getattr(file_obj, "name", "") or "")[1].lower()
        if ext and ext not in self.receipt_allowed_exts:
            raise ValidationError("صيغة الإيصال غير مدعومة. الصيغ المسموحة: JPG, PNG, WEBP")

        # size
        size = getattr(file_obj, "size", None)
        if size is not None and int(size) > self.receipt_max_size_bytes:
            raise ValidationError("حجم الصورة كبير جدًا. الحد الأقصى 5MB.")

        return file_obj


class SubscriptionRenewalRequestForm(forms.Form, _ReceiptImageValidationMixin):
    receipt_image = forms.ImageField(
        label="إيصال التحويل (صورة)",
        widget=forms.ClearableFileInput(
            attrs={"class": "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"}
        ),
    )
    transfer_note = forms.CharField(
        label="ملاحظة (اختياري)",
        required=False,
        max_length=255,
        widget=forms.TextInput(
            attrs={"class": "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"}
        ),
    )

    def clean_receipt_image(self):
        return self._validate_receipt_image(self.cleaned_data.get("receipt_image"))


class SubscriptionNewRequestForm(forms.Form, _ReceiptImageValidationMixin):
    plan = forms.ModelChoiceField(
        queryset=SubscriptionPlan.objects.filter(is_active=True).order_by("sort_order", "name"),
        label="اختر الخطة",
        widget=forms.Select(
            attrs={"class": "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"}
        ),
    )
    receipt_image = forms.ImageField(
        label="إيصال التحويل (صورة)",
        widget=forms.ClearableFileInput(
            attrs={"class": "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"}
        ),
    )
    transfer_note = forms.CharField(
        label="ملاحظة (اختياري)",
        required=False,
        max_length=255,
        widget=forms.TextInput(
            attrs={"class": "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"}
        ),
    )

    def clean_receipt_image(self):
        return self._validate_receipt_image(self.cleaned_data.get("receipt_image"))


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


class SystemEmployeeCreateForm(UserCreationForm):
    """إنشاء موظف نظام (بدون ربط بمدارس)."""

    ROLE_SUPPORT = "support"
    ROLE_SUPERUSER = "superuser"

    role = forms.ChoiceField(
        label="نوع الموظف",
        choices=[
            (ROLE_SUPPORT, "موظف دعم"),
        ],
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
            "role",
        ]
        labels = {
            "username": "اسم المستخدم",
            "email": "البريد الإلكتروني",
            "first_name": "الاسم الأول",
            "last_name": "اسم العائلة",
            "is_active": "حساب نشط",
        }

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)

        # الموظف يجب أن يكون staff دائمًا
        user.is_staff = True

        role = self.cleaned_data.get("role")
        user.is_superuser = bool(role == self.ROLE_SUPERUSER)

        if commit:
            user.save()

        # ربط/إنشاء بروفايل بدون مدارس
        profile = _get_profile(user)
        profile.schools.clear()
        profile.active_school = None
        profile.mobile = self.cleaned_data.get("mobile")
        profile.save()

        # ربط مجموعة Support حسب الدور
        try:
            from django.contrib.auth.models import Group

            support_group, _ = Group.objects.get_or_create(name="Support")
            if role == self.ROLE_SUPPORT:
                user.groups.add(support_group)
            else:
                user.groups.remove(support_group)
        except Exception:
            pass

        return user


from core.models import SupportTicket

class SubscriptionPlanForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # المطلوب حسب الطلب: كل خطة جديدة يجب تحديد عدد الأيام
        if "duration_days" in self.fields:
            self.fields["duration_days"].required = True

    class Meta:
        model = SubscriptionPlan
        fields = "__all__"
        widgets = {
            "name": forms.TextInput(attrs={"class": "w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500"}),
            "code": forms.TextInput(attrs={"class": "w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500"}),
            "price": forms.NumberInput(attrs={"class": "w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500"}),
            "duration_days": forms.NumberInput(attrs={"class": "w-full rounded-lg border-slate-300 focus:border-blue-500 focus:ring-blue-500"}),
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
