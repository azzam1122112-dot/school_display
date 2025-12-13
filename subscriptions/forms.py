from django import forms

from .models import SchoolSubscription
from core.models import School, SubscriptionPlan


class SchoolSubscriptionForm(forms.ModelForm):
    class Meta:
        model = SchoolSubscription
        fields = ["school", "plan", "starts_at", "ends_at", "status", "notes"]
        widgets = {
            "starts_at": forms.DateInput(attrs={"type": "date", "class": "form-input"}),
            "ends_at": forms.DateInput(attrs={"type": "date", "class": "form-input"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "form-textarea"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["school"].queryset = School.objects.order_by("name")
        self.fields["plan"].queryset = SubscriptionPlan.objects.order_by("name")
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-input")

    def clean(self):
        cleaned = super().clean()
        starts_at = cleaned.get("starts_at")
        ends_at = cleaned.get("ends_at")

        if starts_at and ends_at and ends_at < starts_at:
            raise forms.ValidationError(
                "تاريخ نهاية الاشتراك يجب أن يكون بعد تاريخ البداية."
            )

        return cleaned
