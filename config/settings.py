import os
from pathlib import Path
import sys

import dj_database_url

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass


BASE_DIR = Path(__file__).resolve().parent.parent


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


# ===== إعدادات أساسية =====
SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-key-change-me")
DEBUG = env_bool("DEBUG", "True")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "127.0.0.1,localhost,.onrender.com")

# CSRF_TRUSTED_ORIGINS
_csrf_env = env_list("CSRF_TRUSTED_ORIGINS", "")
if _csrf_env:
    CSRF_TRUSTED_ORIGINS = _csrf_env
else:
    CSRF_TRUSTED_ORIGINS: list[str] = []
    for host in ALLOWED_HOSTS:
        h = host.lstrip(".")
        if h and h not in {"127.0.0.1", "localhost"}:
            CSRF_TRUSTED_ORIGINS.append(f"https://{h}")
            CSRF_TRUSTED_ORIGINS.append(f"https://*.{h}")

# تفعيل / تعطيل Firebase عبر متغير بيئة واحد
ENABLE_FIREBASE = env_bool("ENABLE_FIREBASE", "False")
USE_FIREBASE = ENABLE_FIREBASE  # للتوافق مع أي استخدام سابق لاسم USE_FIREBASE

# مسارات مفاتيح Google/Firebase (اختياري – حسب ما هو موجود في البيئة)
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
FIREBASE_CREDENTIALS = os.getenv("FIREBASE_CREDENTIALS", "")


# ===== التطبيقات =====
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # التخزين السحابي للوسائط
    "cloudinary_storage",
    "cloudinary",
    # REST API
    "rest_framework",
    # تطبيقات المشروع
    "core",
    "schedule",
    "standby",
    "notices.apps.NoticesConfig",
    "website",
    "dashboard",
    "subscriptions.apps.SubscriptionsConfig",
 ]


# ===== الوسطاء (Middleware) =====
MIDDLEWARE = [
    # 1) الأمن الأساسي
    "django.middleware.security.SecurityMiddleware",


    # 2) Static files (قبل بقية الوسطاء كما توصي WhiteNoise)
    "whitenoise.middleware.WhiteNoiseMiddleware",

    # 3) الجلسات والعمليات الأساسية
    "django.contrib.sessions.middleware.SessionMiddleware",

    "django.middleware.common.CommonMiddleware",

    # 4) CSRF وحماية الفورمات
    "django.middleware.csrf.CsrfViewMiddleware",

    # 5) تسجيل الدخول والصلاحيات
    "django.contrib.auth.middleware.AuthenticationMiddleware",

    # 6) الرسائل (ضروري قبل أي ميدل وير يستخدم messages)
    "django.contrib.messages.middleware.MessageMiddleware",

    # 7) Middlewares الخاصة بالنظام
    "core.middleware.DisplayTokenMiddleware",     # لعرض الشاشة (مهم لعمل Public Display)
    "core.middleware.SecurityHeadersMiddleware",  # هيدر الأمان المخصص

    # 8) حماية الاشتراكات — الآن بعد MessageMiddleware
    "dashboard.middleware.SubscriptionRequiredMiddleware",

    # 9) حماية الإطارات
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# ===== إعدادات DRF =====
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
        if not DEBUG
        else (
            "rest_framework.renderers.JSONRenderer",
            "rest_framework.renderers.BrowsableAPIRenderer",
        )
    ),
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        # يمكن إضافة Throttle مخصص لشاشات العرض لاحقاً (DisplayScreenThrottle)
        # وتفعيله هنا أو على مستوى الـ View فقط.
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "1000/day",
        # نسبة جاهزة للاستخدام في حال أنشأنا DisplayScreenThrottle
        "display_screen": "30/min",
    },
}


ROOT_URLCONF = "config.urls"


# ===== القوالب =====
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


# ===== قاعدة البيانات =====
if DEBUG:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    # في الإنتاج نعتمد على DATABASE_URL من متغيرات البيئة
    DATABASES = {
        "default": dj_database_url.config(
            env="DATABASE_URL",
            conn_max_age=600,
            ssl_require=True,
        )
    }


# ===== الكاش (Cache) =====
# افتراضياً: LocMemCache
# يمكن استخدام Redis إذا تم ضبط REDIS_URL في البيئة.
REDIS_URL = os.getenv("REDIS_URL", "").strip()

if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "school_display_cache",
        }
    }


# ===== كلمات المرور =====
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ===== اللغة والوقت =====
LANGUAGE_CODE = "ar"
TIME_ZONE = os.getenv("TIME_ZONE", "Asia/Riyadh")
USE_I18N = True
USE_TZ = True


# ===== الملفات الثابتة والوسائط =====
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

_static_dir = BASE_DIR / "static"
STATICFILES_DIRS = [_static_dir] if _static_dir.exists() else []

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# ===== Cloudinary للوسائط =====
CLOUDINARY_STORAGE = {
    "CLOUD_NAME": os.getenv("CLOUDINARY_CLOUD_NAME"),
    "API_KEY": os.getenv("CLOUDINARY_API_KEY"),
    "API_SECRET": os.getenv("CLOUDINARY_API_SECRET"),
}

USE_CLOUD_STORAGE = not DEBUG

STORAGES = {
    "default": {
        "BACKEND": (
            "cloudinary_storage.storage.MediaCloudinaryStorage"
            if USE_CLOUD_STORAGE
            else "django.core.files.storage.FileSystemStorage"
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


WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_USE_FINDERS = DEBUG

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ===== أمان و Proxy =====
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

# إعادة التوجيه الإجباري إلى HTTPS في الإنتاج افتراضياً
SECURE_SSL_REDIRECT = env_bool(
    "SECURE_SSL_REDIRECT",
    "False" if DEBUG else "True",
)

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # نتركه False لأن CSRF تعتمد على JS في بعض الأحيان

SECURE_CONTENT_TYPE_NOSNIFF = True
# منع الإطار (Clickjacking) – CSP أيضاً يضيف frame-ancestors
X_FRAME_OPTIONS = "DENY"

if not DEBUG:
    # HSTS
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", "31536000")
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
        "SECURE_HSTS_INCLUDE_SUBDOMAINS",
        "True",
    )
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", "True")

    # سياسة الإحالة
    SECURE_REFERRER_POLICY = os.getenv(
        "SECURE_REFERRER_POLICY",
        "strict-origin-when-cross-origin",
    )


# ===== التسجيل (Logging) =====
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
        "simple": {
            "format": "[{levelname}] {message}",
            "style": "{",
        },
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
        "django.utils.autoreload": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.server": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "rest_framework": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR" if "test" in sys.argv else "WARNING",
            "propagate": False,
        },
    },
}

# ===== توجيهات الدخول =====
LOGIN_URL = "dashboard:login"
LOGIN_REDIRECT_URL = "dashboard:index"
LOGOUT_REDIRECT_URL = "dashboard:login"

SITE_BASE_URL = os.getenv("SITE_BASE_URL", "http://127.0.0.1:8000")
