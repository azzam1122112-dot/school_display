
class DisplayScreenForm(forms.ModelForm):
    class Meta:
        model = DisplayScreen
        fields = ["name", "is_active"]
