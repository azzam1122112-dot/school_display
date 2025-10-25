# schedule/forms.py
from datetime import time, datetime
from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet
from .models import Period

def _fmt(t: time) -> str:
    return t.strftime("%H:%M:%S") if t else "—"

class PeriodForm(forms.ModelForm):
    class Meta:
        model = Period
        fields = ["day", "order", "title", "start_time", "end_time", "is_break"]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "اسم الحصة/الفسحة"}),
        }

    def clean(self):
        cleaned = super().clean()
        st = cleaned.get("start_time")
        en = cleaned.get("end_time")

        # حماية None
        if st is None:
            self.add_error("start_time", "هذا الحقل مطلوب.")
        if en is None:
            self.add_error("end_time", "هذا الحقل مطلوب.")
        if st and en and not (st < en):
            self.add_error("end_time", f"وقت النهاية يجب أن يكون بعد البداية. ({_fmt(st)} < {_fmt(en)})")

        return cleaned


class PeriodInlineFormSet(BaseInlineFormSet):
    """
    تحقّق جماعي داخل نفس اليوم:
    - منع تكرار order
    - منع التداخل بين العناصر (يشمل العناصر الجديدة قبل الحفظ)
    - منع وجود فترة يوم كاملة مع غيرها
    """
    def clean(self):
        super().clean()
        items = []
        orders = set()
        full_day_exists = False

        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if form.cleaned_data.get("DELETE", False):
                continue

            st = form.cleaned_data.get("start_time")
            en = form.cleaned_data.get("end_time")
            order = form.cleaned_data.get("order")
            title = form.cleaned_data.get("title") or "حصة"
            is_break = form.cleaned_data.get("is_break", False)

            if st is None or en is None:
                # الأخطاء الحقلية ستُظهر الرسالة
                continue

            # يوم كامل؟
            if st == time(0, 0, 0) and en >= time(23, 59, 59):
                if items:
                    raise ValidationError("لا يمكن إضافة فترة تمتد اليوم كله مع فترات أخرى في نفس اليوم.")
                full_day_exists = True

            # تكرار الترتيب
            if order in orders:
                raise ValidationError("حصة بهذا Day و الترتيب (1..ن) موجود سلفاً.")
            orders.add(order)

            items.append((st, en, title, is_break, order))

        if full_day_exists and len(items) > 1:
            # لو مرّت السابقة لأي سبب
            raise ValidationError("لا يمكن الجمع بين فترة اليوم الكامل وفترات أخرى.")

        # فحص التداخلات داخل المجموعة نفسها
        # مرتبة بالبدء يمنع رسائل زائدة ويجعلها دقيقة
        items.sort(key=lambda x: x[0])  # sort by start_time
        for i in range(len(items)):
            st1, en1, title1, is_break1, order1 = items[i]
            for j in range(i + 1, len(items)):
                st2, en2, title2, is_break2, order2 = items[j]
                if max(st1, st2) < min(en1, en2):
                    # رسالة مخصصة حسب النوع
                    if is_break1 or is_break2:
                        raise ValidationError(
                            f"تداخل وقت الفسحة مع '{title1 if is_break1 else title2}' "
                            f"({_fmt(st1)}-{_fmt(en1)}) / ({_fmt(st2)}-{_fmt(en2)})."
                        )
                    else:
                        # اذكر رقمي الحصتين
                        raise ValidationError(
                            f"تداخل وقت الحصة مع الحصة #{order1 if order1 < order2 else order2} "
                            f"({_fmt(st1)}-{_fmt(en1)}) / ({_fmt(st2)}-{_fmt(en2)})."
                        )
