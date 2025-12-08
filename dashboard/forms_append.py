from django import forms
from core.models import DisplayScreen
class DisplayScreenForm(forms.ModelForm):
    class Meta:
        model = DisplayScreen
        fields = ["name", "is_active"]
