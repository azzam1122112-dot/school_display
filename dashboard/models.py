from django.db import models

# موديل School الحقيقي موجود في core.models
# هذا السطر فقط للتوافق مع أي استيراد قديم من dashboard.models
from core.models import School  # noqa: F401
