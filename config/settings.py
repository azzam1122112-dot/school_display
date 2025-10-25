# config/settings.py
# إعدادات Django — نسخة احترافية آمنة ومرنة
# - لغة عربية + منطقة زمنية الرياض
# - قراءة الإعدادات من .env
# - SQLite للتطوير وPostgreSQL للإنتاج (DATABASE_URL)
# - ملفات ثابتة عبر WhiteNoise
# - تشديد الأمان تلقائيًا عند DEBUG=False
# - DRF مفعّل، وتنسيق الاستجابات حسب البيئة
# - تحسينات: تحمّل غياب dj_database_url بأمان، ومسارات static مشروطة

from pathlib import Path
import os
from dotenv import load_dotenv

# محاولة استيراد dj_database_url بشكل آمن
try:
    import dj_database_url  # type: ignore
except Exception:
    dj_database_url = None  # سيتعامل الكود لاحقًا مع غيابها بشكل واضح

# تحميل متغيرات البيئة
load_dotenv()

# المسار الجذري للمشروع
BASE_DIR = Path(__file__).resolve().parent.parent

# ---- أدوات مساعدة ----
def env_bool(key: str, default: str = "False") -> bool:
    return os.getenv(key, default).strip().lower() in {"1", "true", "yes", "on"}

def env_list(key: str, default: str = "") -> list[str]:
    raw = os.getenv(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]

# ----------------- مفاتيح أساسية -----------------
SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-key-change-me")  # غيّرها بالإنتاج
DEBUG = env_bool("DEBUG", "True")  # محليًا True، بالإنتاج False
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "127.0.0.1,localhost")

# موثوقون للـ CSRF (يجب أن تتضمن البروتوكول)
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "")

# ----------------- التطبيقات -----------------
INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # طرف ثالث
    "rest_framework",

    # تطبيقات المشروع
    "core",
    "schedule",
    "standby",
    "notices",
    "website",
    "dashboard",
]

# ----------------- الميدلوير -----------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # خدمة static في الإنتاج
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

# ----------------- القوالب -----------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # تأكد من وجود مجلد templates
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ----------------- WSGI/ASGI -----------------
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ----------------- قاعدة البيانات -----------------
# افتراضيًا SQLite (محلي). إذا ضُبط DATABASE_URL، نستخدمه (PostgreSQL عادةً).
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if DATABASE_URL:
    if dj_database_url is None:
        raise RuntimeError(
            "تم ضبط DATABASE_URL لكن الحزمة dj-database-url غير مثبتة. "
            "ثبّت الحزمة: pip install dj-database-url"
        )
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            ssl_require=env_bool("DB_SSL_REQUIRE", "False"),
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ----------------- كلمات المرور -----------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ----------------- الترجمة والمنطقة الزمنية -----------------
LANGUAGE_CODE = "ar"
TIME_ZONE = "Asia/Riyadh"
USE_I18N = True
USE_TZ = True  # احتفظ بها True لدقة التحويلات الزمنية

# ----------------- الملفات الثابتة والوسائط -----------------
STATIC_URL = "/static/"

# إضافة static المحلي فقط إذا المجلد موجود لتجنب تحذيرات غير ضرورية
_static_dir = BASE_DIR / "static"
STATICFILES_DIRS = [_static_dir] if _static_dir.exists() else []

STATIC_ROOT = BASE_DIR / "staticfiles"  # للإنتاج مع collectstatic

# WhiteNoise (تخزين مضغوط + Manifest للنسخ المصدّرة)
STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ----------------- نوع المفتاح الافتراضي -----------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ----------------- DRF إعدادات -----------------
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    # مخرجات أخف بالإنتاج
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ] if not DEBUG else [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}

# ----------------- الأمان -----------------
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", "False")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True  # يمنع JavaScript من قراءة توكن CSRF

if not DEBUG:
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", "True")
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", "True")
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"

# ----------------- التسجيل (Logging) -----------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG" if DEBUG else "WARNING")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "[{levelname}] {asctime} {name}: {message}", "style": "{"},
        "simple": {"format": "[{levelname}] {message}", "style": "{"},
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "verbose"}},
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {"django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": True}},
}

# ----------------- المصادقة وتوجيهات لوحة التحكم -----------------
LOGIN_URL = "dashboard:login"
LOGIN_REDIRECT_URL = "dashboard:index"
LOGOUT_REDIRECT_URL = "dashboard:login"

# ----------------- عنوان الموقع (اختياري للتطبيقات) -----------------
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "http://127.0.0.1:8000")

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"   # اختر مسارًا مناسبًا


# settings.py
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent

# --------- ملفات الميديا (رفع المستخدم) ---------
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# --------- الملفات الثابتة ---------
STATIC_URL = "/static/"
# لو عندك مجلد static للتطوير:
STATICFILES_DIRS = [BASE_DIR / "static"]
# ولو تستخدم مجلد تجميع للإنتاج:
STATIC_ROOT = BASE_DIR / "staticfiles"

# --------- Django 5: STORAGES ---------
# تخزين افتراضي للملفات المرفوعة على نظام الملفات المحلي (development)
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {
            # مهمّة لاحتساب url الصحيح (تساوي MEDIA_URL)
            "base_url": MEDIA_URL,
            # موقع الحفظ الفعلي (تساوي MEDIA_ROOT)
            "location": str(MEDIA_ROOT),
        },
    },
    "staticfiles": {
        # للتطوير؛ للإنتاج قد تستخدم ManifestStaticFilesStorage أو WhiteNoise
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# ----------------- ملاحظات تشغيلية -----------------
# 1) .env (إنتاج):
#    DEBUG=False
#    SECRET_KEY=قيمة-قوية-طويلة
#    ALLOWED_HOSTS=example.com,www.example.com
#    CSRF_TRUSTED_ORIGINS=https://example.com,https://www.example.com
#    DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST/DB
#    SECURE_SSL_REDIRECT=True
#
# 2) قبل الإنتاج:
#    python manage.py collectstatic
#
# 3) خلف Proxy (Cloudflare/Nginx):
#    تأكد من تمكين X-Forwarded-Proto (ضبطناه في SECURE_PROXY_SSL_HEADER)
#
# 4) للتقويم الهجري:
#    hijri-converter مثبت ويمكن استدعاؤه داخل views/templatetags.
