from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import secrets


class School(models.Model):
    name = models.CharField("اسم المدرسة", max_length=150)
    slug = models.SlugField(
        "رابط المدرسة",
        unique=True,
        help_text="يستخدم في الرابط، مثلا: school-1",
    )
    logo = models.ImageField(
        "الشعار",
        upload_to="schools/logos/",
        blank=True,
        null=True,
    )
    is_active = models.BooleanField(
        "اشتراك نشط",
        default=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "مدرسة"
        verbose_name_plural = "المدارس"

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="المستخدم",
    )
    schools = models.ManyToManyField(
        School,
        related_name="users",
        verbose_name="المدارس المتاحة",
        blank=True,
    )
    active_school = models.ForeignKey(
        School,
        on_delete=models.SET_NULL,
        related_name="active_users",
        verbose_name="المدرسة النشطة",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "ملف المستخدم"
        verbose_name_plural = "ملفات المستخدمين"

    def __str__(self):
        return f"{self.user.username} - {self.active_school.name if self.active_school else 'No Active School'}"


class DisplayScreen(models.Model):
    short_code = models.CharField(
        max_length=8,
        unique=True,
        editable=False,
        verbose_name="رابط مختصر",
        null=True,
        blank=True,
    )
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="screens",
        verbose_name="المدرسة",
        null=True,
        blank=True,
    )
    name = models.CharField(
        max_length=100,
        verbose_name="اسم الشاشة",
    )
    token = models.CharField(
        max_length=64,
        unique=True,
        editable=False,
        verbose_name="رمز الوصول",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="نشط",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="آخر ظهور",
    )

    class Meta:
        verbose_name = "شاشة عرض"
        verbose_name_plural = "شاشات العرض"

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_hex(32)
        if not self.short_code:
            # Generate a unique short code (alphanumeric, 6 chars)
            import string, random
            for _ in range(10):
                code = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
                if not DisplayScreen.objects.filter(short_code=code).exists():
                    self.short_code = code
                    break
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.school.name} - {self.name}" if self.school else self.name


class SubscriptionPlan(models.Model):
    code = models.SlugField(
        "رمز الخطة",
        unique=True,
        max_length=50,
        help_text="يُستخدم داخليًا، مثل: basic, pro, enterprise",
    )
    name = models.CharField("اسم الخطة", max_length=150)
    price_monthly = models.DecimalField(
        "السعر الشهري (ر.س)",
        max_digits=8,
        decimal_places=2,
        default=0,
    )
    max_users = models.PositiveIntegerField(
        "الحد الأقصى للمستخدمين",
        null=True,
        blank=True,
        help_text="اتركه فارغًا لعدد غير محدود.",
    )
    max_screens = models.PositiveIntegerField(
        "الحد الأقصى لشاشات العرض",
        null=True,
        blank=True,
        help_text="اتركه فارغًا لعدد غير محدود.",
    )
    max_schools = models.PositiveIntegerField(
        "الحد الأقصى للمدارس",
        default=1,
        help_text="العدد المسموح به من المدارس في هذه الخطة.",
    )
    is_active = models.BooleanField(
        "متاحة للاشتراك",
        default=True,
    )
    sort_order = models.PositiveIntegerField(
        "ترتيب العرض",
        default=1,
    )

    class Meta:
        verbose_name = "خطة اشتراك"
        verbose_name_plural = "خطط الاشتراك"
        ordering = ("sort_order", "price_monthly")

    def __str__(self) -> str:
        return self.name



# ملاحظة: لا نضيف imports جديدة غير لازمة هنا
# لأن هذا الموديل أصبح Legacy ولا يجب أن يتداخل مع subscriptions


class SchoolSubscription(models.Model):
    """
    ⚠️ Legacy Model (للتوافق الخلفي فقط)

    هذا الموديل كان موجودًا سابقًا داخل core.
    الآن مصدر الحقيقة للاشتراك هو: subscriptions.SchoolSubscription

    ✅ مهم:
    - هذا الموديل لا يُحدّث School.is_active إطلاقًا (لتجنب التعارض).
    - لا تعتمد عليه في منطق صلاحيات/اشتراكات الداشبورد.
    """

    school = models.ForeignKey(
        "core.School",
        on_delete=models.CASCADE,
        related_name="+",  # منع School.subscriptions من هذا الموديل
        verbose_name="المدرسة",
    )
    plan = models.ForeignKey(
        "core.SubscriptionPlan",
        on_delete=models.PROTECT,
        related_name="+",  # منع SubscriptionPlan.subscriptions من هذا الموديل
        verbose_name="الخطة",
    )
    start_date = models.DateField("تاريخ البداية")
    end_date = models.DateField(
        "تاريخ الانتهاء",
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(
        "نشط",
        default=True,
    )
    notes = models.CharField(
        "ملاحظات",
        max_length=250,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "اشتراك مدرسة (قديم)"
        verbose_name_plural = "اشتراكات المدارس (قديمة)"
        ordering = ("-start_date", "-created_at")

    def __str__(self) -> str:
        school_name = getattr(self.school, "name", str(self.school))
        plan_name = getattr(self.plan, "name", str(self.plan))
        return f"{school_name} — {plan_name}"

    @property
    def is_expired(self) -> bool:
        if self.end_date:
            return self.end_date < timezone.localdate()
        return False

    @property
    def status(self) -> str:
        if not self.is_active:
            return "موقوف"
        if self.is_expired:
            return "منتهي"
        return "نشط"

    def save(self, *args, **kwargs):
        """
        ✅ لا نقوم هنا بتحديث school.is_active
        لأن هذا كان سبب التعارض مع subscriptions.SchoolSubscription.
        """
        return super().save(*args, **kwargs)
