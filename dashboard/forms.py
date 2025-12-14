from __future__ import annotations

from datetime import datetime, timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.contrib.auth.forms import UserCreationForm

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
from core.models import (
    DisplayScreen,
    School,
    UserProfile,
    SubscriptionPlan,
)
from subscriptions.models import SchoolSubscription  # ✅ الموديل الجديد الصحيح

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
            "refresh_interval_sec": forms.NumberInput(attrs={"min": 5, "step": 5}),
            "standby_scroll_speed": forms.NumberInput(
                attrs={"min": 0.05, "max": 5.0, "step": 0.05}
            ),
            "periods_scroll_speed": forms.NumberInput(
                attrs={"min": 0.05, "max": 5.0, "step": 0.05}
            ),
        }

    def save(self, commit=True):
        """
        نحفظ الإعدادات، ولو تم رفع شعار جديد نحدّث school.logo بأمان.
        """
        instance: SchoolSettings = super().save(commit=False)
        logo_file = self.cleaned_data.get("logo")
        if logo_file and instance.school:
            instance.school.logo = logo_file
            instance.school.save()
        if commit:
            instance.save()
        return instance


# ========================
# اليوم والجدول الزمني
# ========================


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
            self.add_error(
                "duration_min", "مدة الفسحة يجب أن تكون رقمًا موجبًا بالدقائق."
            )

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
        target_count = int(parent.periods_count or 0)

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

            if getattr(form, "_is_blank_row", False) or _is_blank_period_fields(
                idx, st, en
            ):
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
            periods.append(
                {"label": f"الحصة {idx}", "start": st, "end": en, "form": form}
            )

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
                end = (
                    datetime.combine(datetime.today(), st)
                    + timedelta(minutes=dur)
                ).time()
                breaks.append(
                    {
                        "label": f"الفسحة ({label})",
                        "start": st,
                        "end": end,
                    }
                )

        # التحقق من العدد الأقصى
        count_periods = len(periods)
        if target_count > 0 and count_periods > target_count:
            raise ValidationError(
                f"عدد الحصص المدخلة ({count_periods}) أكبر من القيمة المحددة لليوم ({target_count}). "
                f"رجاءً احذف/عدّل الحصص الزائدة."
            )

        # ترتيب كل العناصر زمنيًا وفحص التداخل
        items = [{"kind": "p", **p} for p in periods] + [
            {"kind": "b", **b} for b in breaks
        ]
        items.sort(key=lambda x: x["start"])

        for i in range(1, len(items)):
            prev, cur = items[i - 1], items[i]
            if cur["start"] < prev["end"]:
                msg_cur = f"تداخل مع {prev['label']} ({prev['start']}-{prev['end']})."
                msg_prev = (
                    f"يتداخل مع {cur['label']} ({cur['start']}-{cur['end']})."
                )
                if cur["kind"] == "p":
                    cur["form"].add_error("starts_at", msg_cur)
                    cur["form"].instance._skip_cross_validation = True
                    errors_added += 1
                if prev["kind"] == "p":
                    prev["form"].add_error("ends_at", msg_prev)
                    prev["form"].instance._skip_cross_validation = True
                    errors_added += 1

        if errors_added > 0:
            raise ValidationError(
                "تحقّق من الأوقات: يوجد حقول ناقصة/مكررة أو تداخلات زمنية."
            )


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


# ========================
# حصص الانتظار
# ========================


class StandbyForm(forms.ModelForm):
    class_name = forms.ModelChoiceField(
        queryset=SchoolClass.objects.none(),
        label="الفصل",
    )
    teacher_name = forms.ModelChoiceField(
        queryset=Teacher.objects.none(),
        label="اسم المعلم/ـة",
    )

    class Meta:
        model = StandbyAssignment
        fields = ["date", "period_index", "class_name", "teacher_name", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
        }

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
        widgets = {
            "logo": forms.ClearableFileInput(),
        }


class AdminUserForm(forms.ModelForm):
    """
    نموذج إنشاء/تعديل مستخدم من لوحة النظام مع إمكانية تعيين كلمة مرور
    وربط المستخدم بمدرسة عبر UserProfile.
    """

    password1 = forms.CharField(
        label="كلمة المرور",
        widget=forms.PasswordInput,
        required=False,
        help_text="اتركها فارغة إن لم ترغب في تغيير كلمة المرور (أو للمستخدم الحالي).",
    )
    password2 = forms.CharField(
        label="تأكيد كلمة المرور",
        widget=forms.PasswordInput,
        required=False,
    )
    schools = forms.ModelMultipleChoiceField(
        queryset=School.objects.all().order_by("name"),
        required=False,
        label="المدارس",
        help_text="يمكن ربط المستخدم بعدة مدارس.",
        widget=forms.SelectMultiple(attrs={"class": "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"}),
    )

    class Meta:
        model = UserModel
        fields = ["username", "first_name", "last_name", "email", "is_active", "is_staff", "is_superuser"]
        labels = {
            "username": "اسم المستخدم",
            "first_name": "الاسم الأول",
            "last_name": "اسم العائلة",
            "email": "البريد الإلكتروني",
            "is_active": "نشط",
            "is_staff": "صلاحيات Staff",
            "is_superuser": "صلاحيات Superuser",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # تعبئة المدارس الحالية من UserProfile إن وجدت
        if self.instance.pk:
            try:
                profile = self.instance.userprofile
            except UserProfile.DoesNotExist:
                profile = None
            except AttributeError:
                profile = getattr(self.instance, "profile", None)

            if profile:
                self.fields["schools"].initial = profile.schools.all()
    def save(self, commit=True):
        user = super().save(commit)
        # تحديث المدارس المرتبطة بالبروفايل
        profile, _ = UserProfile.objects.get_or_create(user=user)
        schools = self.cleaned_data.get("schools")
        if schools is not None:
            profile.schools.set(schools)
        profile.save()
        return user

        # تحسين التنسيق
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({"class": "h-4 w-4 text-indigo-600"})
            else:
                field.widget.attrs.update(
                    {
                        "class": "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm "
                        "focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                    }
                )

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")

        # مستخدم جديد
        if not self.instance.pk:
            if not p1:
                raise ValidationError("يجب إدخال كلمة المرور للمستخدم الجديد.")
            if p1 != p2:
                raise ValidationError("كلمتا المرور غير متطابقتين.")
        else:
            # مستخدم موجود: تغيير كلمة المرور اختياري
            if p1 or p2:
                if p1 != p2:
                    raise ValidationError("كلمتا المرور غير متطابقتين.")

        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password1")

        if password:
            user.set_password(password)

        if commit:
            user.save()

        school = self.cleaned_data.get("school")
        try:
            profile, _ = UserProfile.objects.get_or_create(user=user)
        except Exception:
            profile = getattr(user, "profile", None)
            if profile is None:
                profile = UserProfile(user=user)

        profile.school = school
        if commit:
            profile.save()

        return user


class SchoolSubscriptionForm(forms.ModelForm):
    """
    نموذج إدارة اشتراك المدرسة بناءً على موديل SchoolSubscription الجديد:
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


UserModel = get_user_model()


class SystemUserCreateForm(UserCreationForm):
    """
    إنشاء مستخدم جديد + ربطه بالمدرسة.
    يعتمد UserCreationForm حتى نستفيد من تحققات كلمة المرور.
    """
    schools = forms.ModelMultipleChoiceField(
        queryset=School.objects.all(),
        required=True,
        label="المدارس",
        help_text="المدارس التي يرتبط بها هذا المستخدم.",
        widget=forms.SelectMultiple(attrs={"class": "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"}),
    )

    class Meta(UserCreationForm.Meta):
        model = UserModel
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
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

    def save(self, commit=True):
        user = super().save(commit=False)
        if commit:
            user.save()
            schools = self.cleaned_data.get("schools")
            profile, _ = UserProfile.objects.get_or_create(user=user)
            if schools is not None:
                profile.schools.set(schools)
                # تعيين أول مدرسة كمدرسة نشطة افتراضيًا إذا لم تكن موجودة
                if not profile.active_school and schools:
                    profile.active_school = schools[0]
            profile.save()
        return user


class SystemUserUpdateForm(forms.ModelForm):
    """
    تعديل بيانات المستخدم + إمكانية تغيير كلمة المرور اختيارياً.
    إذا تُركت حقول كلمة المرور فارغة لن تتغير كلمة المرور.
    """
    schools = forms.ModelMultipleChoiceField(
        queryset=School.objects.all(),
        required=False,
        label="المدارس",
        help_text="المدارس المرتبط بها المستخدم.",
        widget=forms.SelectMultiple(attrs={"class": "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"}),
    )

    new_password1 = forms.CharField(
        label="كلمة المرور الجديدة",
        widget=forms.PasswordInput,
        required=False,
        help_text="اترك الحقلين فارغين إذا لا تريد تغيير كلمة المرور."
    )
    new_password2 = forms.CharField(
        label="تأكيد كلمة المرور الجديدة",
        widget=forms.PasswordInput,
        required=False,
    )

    class Meta:
        model = UserModel
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
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
        # تعبئة المدارس الحالية من البروفايل إن وجدت
        if self.instance.pk:
            try:
                profile = self.instance.profile
                self.fields["schools"].initial = profile.schools.all()
            except UserProfile.DoesNotExist:
                pass
    def save(self, commit=True):
        user = super().save(commit=False)
        # تغيير كلمة المرور إذا تم إدخالها
        new_password = self.cleaned_data.get("new_password1")
        if new_password:
            user.set_password(new_password)
        if commit:
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            schools = self.cleaned_data.get("schools")
            if schools is not None:
                profile.schools.set(schools)
            profile.save()
        return user

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("new_password1")
        p2 = cleaned.get("new_password2")

        if p1 or p2:
            # لو واحد منهم فقط ممتلئ
            if not p1 or not p2:
                raise forms.ValidationError("لابد من إدخال كلمة المرور الجديدة وتأكيدها.")
            if p1 != p2:
                raise forms.ValidationError("كلمتا المرور غير متطابقتين.")
            if len(p1) < 8:
                raise forms.ValidationError("يجب أن تكون كلمة المرور ٨ أحرف على الأقل.")
        return cleaned

    # تم حذف الدالة الزائدة التي تكتب فوق set للمدارس
        return user
