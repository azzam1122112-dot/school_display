# config/settings.py
# إعدادات Django — نسخة احترافية آمنة ومرنة (Arabic / Asia/Riyadh)
# - تحميل .env
# - SQLite للتطوير وPostgreSQL عبر DATABASE_URL للإنتاج
# - WhiteNoise للملفات الثابتة
# - DRF مُفعّل مع مخرجات أخف بالإنتاج
# - لوجينغ هادئ (إسكات django.utils.autoreload) مع إمكانية التحكم عبر متغيرات البيئة

from pathlib import Path
import os
from dotenv import load_dotenv

# محاولة استيراد dj_database_url بشكل آمن
try:
    import dj_database_url  # type: ignore
except Exception:
    dj_database_url = None

# تحميل متغيرات البيئة من .env (إن وُجد)
load_dotenv()

# ----------------- المسارات -----------------
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

# موثوقون للـ CSRF (يجب أن تتضمن البروتوكول مثل https://example.com)
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
    "notices.apps.NoticesConfig",
    "website",
    "dashboard",
]

# ----------------- الميدلوير -----------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # خدمة static (وCDN-friendly) + ضغط
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
# افتراضيًا SQLite (محلي). إذا وُجد DATABASE_URL نستخدمه (PostgreSQL عادةً).
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
# Static
STATIC_URL = "/static/"
_static_dir = BASE_DIR / "static"
STATICFILES_DIRS = [_static_dir] if _static_dir.exists() else []  # للتطوير (اختياري)
STATIC_ROOT = BASE_DIR / "staticfiles"  # للإنتاج مع collectstatic

# Media
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Django 5 STORAGES
STORAGES = {
    # تخزين افتراضي للملفات المرفوعة على النظام المحلي (development/بسيط)
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"base_url": MEDIA_URL, "location": str(MEDIA_ROOT)},
    },
    # ملفات ثابتة عبر WhiteNoise (ضغط + Manifest)
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

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
    "DEFAULT_RENDERER_CLASSES": (
        ["rest_framework.renderers.JSONRenderer"]
        if not DEBUG
        else [
            "rest_framework.renderers.JSONRenderer",
            "rest_framework.renderers.BrowsableAPIRenderer",
        ]
    ),
}

# ----------------- الأمان -----------------
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", "False")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True  # يمنع JavaScript من قراءة توكن CSRF
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"

if not DEBUG:
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", "True")
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", "True")
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# ----------------- التسجيل (Logging) -----------------
# افتراضيًا: INFO حتى في التطوير، مع إسكات autoreload وثرثرة DRF
DJANGO_LOG_LEVEL = os.getenv("DJANGO_LOG_LEVEL", "INFO")
DJANGO_CONSOLE_LEVEL = os.getenv("DJANGO_CONSOLE_LEVEL", "INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "verbose": {
            "format": "[{levelname}] {asctime} {name}: {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "simple": {"format": "[{levelname}] {message}", "style": "{"},
    },

    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "level": DJANGO_CONSOLE_LEVEL,  # لا تطبع DEBUG على الكونسول افتراضيًا
        },
    },

    # اجعل الجذر INFO
    "root": {"handlers": ["console"], "level": DJANGO_LOG_LEVEL},

    "loggers": {
        # إسكات رسائل أوتولود المزعجة
        "django.utils.autoreload": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        # تقليل الضجيج من خادم التطوير
        "django.server": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        # تقليل ثرثرة DRF
        "rest_framework": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        # لوجات Django العامة
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# ----------------- المصادقة وتوجيهات لوحة التحكم -----------------
LOGIN_URL = "dashboard:login"
LOGIN_REDIRECT_URL = "dashboard:index"
LOGOUT_REDIRECT_URL = "dashboard:login"

# ----------------- عنوان الموقع (اختياري للتطبيقات) -----------------
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "http://127.0.0.1:8000")

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
# 4) DRF: عند DEBUG=False يلغى Browsable API تلقائيًا لإخراج أخف وأأمن
