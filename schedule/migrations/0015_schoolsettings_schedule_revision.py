from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("schedule", "0014_duty_assignment_and_featured_panel"),
    ]

    operations = [
        migrations.AddField(
            model_name="schoolsettings",
            name="schedule_revision",
            field=models.PositiveIntegerField(
                default=1,
                help_text="يزداد تلقائياً عند أي تعديل على الجدول لإجبار شاشات العرض على جلب بيانات جديدة فوراً.",
                verbose_name="إصدار الجدول",
            ),
        ),
    ]
