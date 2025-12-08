from django import forms
from schedule.models import SchoolClass, Teacher
from standby.models import StandbyAssignment

class StandbyAssignmentForm(forms.ModelForm):
    class_name = forms.ModelChoiceField(queryset=SchoolClass.objects.all(), label="الفصل")
    teacher_name = forms.ModelChoiceField(queryset=Teacher.objects.all(), label="اسم المعلم")

    class Meta:
        model = StandbyAssignment
        fields = ['date', 'period_index', 'class_name', 'teacher_name', 'notes']
        labels = {
            'date': 'التاريخ',
            'period_index': 'رقم الحصة',
            'notes': 'ملاحظة',
        }
