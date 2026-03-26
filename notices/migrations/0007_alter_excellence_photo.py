from django.db import migrations, models

import notices.models


class Migration(migrations.Migration):

    dependencies = [
        ("notices", "0006_announcement_ann_school_active_idx_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="excellence",
            name="photo",
            field=models.ImageField(
                blank=True,
                help_text="الصيغ المدعومة: JPG / JPEG / PNG / WEBP.",
                null=True,
                upload_to=notices.models._excellence_upload_to,
                validators=[notices.models._validate_excellence_photo_extension],
                verbose_name="صورة (رفع ملف)",
            ),
        ),
    ]