# -------------------------------------------------------
#  Django Settings (Arabic / Asia/Riyadh) — نسخة احترافية
# -------------------------------------------------------
#  ✔ يدعم تشغيل محلي (SQLite)
#  ✔ يدعم تشغيل إنتاج (Render/PostgreSQL)
#  ✔ يدعم Cloudinary
#  ✔ يدعم Firebase عبر USE_FIREBASE
#  ✔ WhiteNoise للـ static
#  ✔ DRF محسّن
#  ✔ Logging متقدم
#  ✔ CSRF/SECURITY مضبوط للإنتاج
# -------------------------------------------------------

import os
from pathlib import Path
import dj_database_url

# ----------------- تحميل .env (اختياري) -----------------
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# ----------------- المسارات -----------------
BASE_DIR = Path(__file__).resolve().parent.parent

# ---- أدوات بيئة ----
def env_bool(key: str, default: str = "False") -> bool:
    return os.getenv(key, default).strip().lower() in {"1", "true", "yes", "on"}

def env_list(key: str, default: str = "") -> list[str]:
    raw = os.getenv(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]

def env_int(key: str, default: str) -> int:
    try:
        return int(os.getenv(key, default))
    except Exception:
        return int(default)

# ----------------- وضع التشغيل -----------------
SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-key-change-me")  # غيّرها بالإنتاج
DEBUG = env_bool("DEBUG", "True")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "127.0.0.1,localhost,.onrender.com")

# ----------------- CSRF -----------------
_csrf_env = env_list("CSRF_TRUSTED_ORIGINS", "")
if _csrf_env:
    CSRF_TRUSTED_ORIGINS = _csrf_env
else:
    CSRF_TRUSTED_ORIGINS = []
    for host in ALLOWED_HOSTS:
        h = host.lstrip(".")
        if h and h not in {"127.0.0.1", "localhost"}:
            CSRF_TRUSTED_ORIGINS.append(f"https://{h}")
            CSRF_TRUSTED_ORIGINS.append(f"https://*.{h}")

# ----------------- التطبيقات -----------------
INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third Party
    "cloudinary_storage",
    "cloudinary",
    "rest_framework",

    # Project Apps
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
    "whitenoise.middleware.WhiteNoiseMiddleware",
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
        "DIRS": [BASE_DIR / "templates"],
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

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ----------------- قاعدة البيانات -----------------

if DEBUG:
    # تشغيل محليًا — SQLite
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    # تشغيل في Render — PostgreSQL
    DATABASES = {
        "default": dj_database_url.parse(
            os.environ.get("DATABASE_URL"),
            conn_max_age=600,
            ssl_require=True
        )
    }

# ----------------- كلمات المرور -----------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ----------------- المنطقة الزمنية -----------------
LANGUAGE_CODE = "ar"
TIME_ZONE = os.getenv("TIME_ZONE", "Asia/Riyadh")
USE_I18N = True
USE_TZ = True

# ----------------- الملفات الثابتة -----------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

_static_dir = BASE_DIR / "static"
STATICFILES_DIRS = [_static_dir] if _static_dir.exists() else []

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Cloudinary
CLOUDINARY_STORAGE = {
    'CLOUD_NAME': os.getenv('CLOUDINARY_CLOUD_NAME'),
    'API_KEY': os.getenv('CLOUDINARY_API_KEY'),
    'API_SECRET': os.getenv('CLOUDINARY_API_SECRET'),
}

USE_CLOUD_STORAGE = not DEBUG
USE_FIREBASE = not DEBUG

STORAGES = {
    "default": {
        "BACKEND": (
            "cloudinary_storage.storage.MediaCloudinaryStorage"
            if USE_CLOUD_STORAGE else
            "django.core.files.storage.FileSystemStorage"
        ),
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

if not USE_CLOUD_STORAGE:
    STORAGES["default"]["OPTIONS"] = {
        "base_url": MEDIA_URL,
        "location": str(MEDIA_ROOT),
    }

# WhiteNoise
WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_USE_FINDERS = DEBUG

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ----------------- DRF -----------------
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_RENDERER_CLASSES": (
        ("rest_framework.renderers.JSONRenderer",)
        if not DEBUG else (
            "rest_framework.renderers.JSONRenderer",
            "rest_framework.renderers.BrowsableAPIRenderer",
        )
    ),
}

# ----------------- الأمان -----------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", "False" if DEBUG else "True")

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

if not DEBUG:
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", "31536000")
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", "True")
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", "True")
    SECURE_REFERRER_POLICY = os.getenv("SECURE_REFERRER_POLICY", "strict-origin-when-cross-origin")

# ----------------- Logging -----------------
DJANGO_LOG_LEVEL = os.getenv("DJANGO_LOG_LEVEL", "INFO")
DJANGO_CONSOLE_LEVEL = os.getenv("DJANGO_CONSOLE_LEVEL", "INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "[{levelname}] {asctime} {name}: {message}", "style": "{", "datefmt": "%Y-%m-%d %H:%M:%S"},
        "simple": {"format": "[{levelname}] {message}", "style": "{"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "level": DJANGO_CONSOLE_LEVEL,
        },
    },
    "root": {"handlers": ["console"], "level": DJANGO_LOG_LEVEL},
    "loggers": {
        "django.utils.autoreload": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.server": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "rest_framework": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# ----------------- Auth Redirects -----------------
LOGIN_URL = "dashboard:login"
LOGIN_REDIRECT_URL = "dashboard:index"
LOGOUT_REDIRECT_URL = "dashboard:login"

# ----------------- الموقع الأساسي -----------------
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "http://127.0.0.1:8000")

# ----------------- إعدادات الأمان (Security Hardening) -----------------
if not DEBUG:
    # 1. فرض HTTPS
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # 2. تفعيل HSTS (يخبر المتصفح برفض أي اتصال غير مشفر لمدة سنة)
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # 3. تأمين الكوكيز
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # 4. منع تشغيل الموقع داخل IFrame (إلا من نفس الدومين)
    X_FRAME_OPTIONS = "SAMEORIGIN"
    # 5. منع المتصفح من تخمين نوع الملفات
    SECURE_CONTENT_TYPE_NOSNIFF = True
