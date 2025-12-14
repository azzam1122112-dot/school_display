from django import forms

from schedule.models import SchoolClass, Teacher
from standby.models import StandbyAssignment


class StandbyAssignmentForm(forms.ModelForm):
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
        labels = {
            "date": "التاريخ",
            "period_index": "رقم الحصة",
            "notes": "ملاحظة",
        }
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        # نتوقع أن الواجهة (view) تمُرّر school=request.user.profile.school
        school = kwargs.pop("school", None)
        super().__init__(*args, **kwargs)

        if school is not None:
            # الفصول الخاصة بمدرسة المستخدم فقط
            self.fields["class_name"].queryset = SchoolClass.objects.filter(
                settings__school=school
            ).order_by("name")

            # المعلم/ـةون الخاصون بنفس المدرسة فقط
            self.fields["teacher_name"].queryset = Teacher.objects.filter(
                school=school
            ).order_by("name")
        else:
            # في حال لم يُمرَّر school (حماية من التسرب بين المدارس)
            self.fields["class_name"].queryset = SchoolClass.objects.none()
            self.fields["teacher_name"].queryset = Teacher.objects.none()
