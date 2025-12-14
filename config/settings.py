# config/settings.py
from __future__ import annotations

import os
import sys
from pathlib import Path

import dj_database_url

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass


BASE_DIR = Path(__file__).resolve().parent.parent


# -------------------------
# Helpers
# -------------------------
def env_bool(key: str, default: str = "False") -> bool:
    return os.getenv(key, default).strip().lower() in {"1", "true", "yes", "on"}


def env_int(key: str, default: str) -> int:
    try:
        return int(os.getenv(key, default))
    except Exception:
        return int(default)


def env_list(key: str, default: str = "") -> list[str]:
    raw = os.getenv(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def exists_dir(p: Path) -> bool:
    try:
        return p.exists() and p.is_dir()
    except Exception:
        return False


# -------------------------
# Core
# -------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-key-change-me")
DEBUG = env_bool("DEBUG", "True")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "127.0.0.1,localhost,.onrender.com")


# -------------------------
# CSRF Trusted Origins
# - إذا ضبطتها في ENV نستخدمها مباشرة
# - وإلا نولدها من ALLOWED_HOSTS بشكل آمن (ونستبعد localhost)
# -------------------------
_csrf_env = env_list("CSRF_TRUSTED_ORIGINS", "")
if _csrf_env:
    CSRF_TRUSTED_ORIGINS = _csrf_env
else:
    CSRF_TRUSTED_ORIGINS: list[str] = []
    for host in ALLOWED_HOSTS:
        h = host.strip()
        if not h or h in {"127.0.0.1", "localhost"}:
            continue
        if h.startswith("."):
            # .example.com => https://*.example.com
            CSRF_TRUSTED_ORIGINS.append(f"https://*{h}")
        else:
            CSRF_TRUSTED_ORIGINS.append(f"https://{h}")


# -------------------------
# Firebase (اختياري)
# -------------------------
ENABLE_FIREBASE = env_bool("ENABLE_FIREBASE", "False")
USE_FIREBASE = ENABLE_FIREBASE  # للتوافق إن كان هناك استخدام قديم
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
FIREBASE_CREDENTIALS = os.getenv("FIREBASE_CREDENTIALS", "")
FIREBASE_CREDENTIALS_BASE64 = os.getenv("FIREBASE_CREDENTIALS_BASE64", "")


# -------------------------
# Applications
# -------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Storage (Media)
    "cloudinary_storage",
    "cloudinary",

    # REST
    "rest_framework",

    # Project apps
    "core",
    "schedule",
    "standby",
    "notices.apps.NoticesConfig",
    "website",
    "dashboard",
    "subscriptions.apps.SubscriptionsConfig",
]


# -------------------------
# Middleware (Final Approved Order)
# -------------------------
MIDDLEWARE = [
    # أساسيات الأمان
    "django.middleware.security.SecurityMiddleware",

    # Static files (WhiteNoise)
    "whitenoise.middleware.WhiteNoiseMiddleware",

    # Sessions & Common
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",

    # ضغط الاستجابات (بعد Common)
    "django.middleware.gzip.GZipMiddleware",

    # CSRF
    "django.middleware.csrf.CsrfViewMiddleware",

    # Auth
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",

    # 🔐 Multi-school (بعد auth)
    "core.middleware.ActiveSchoolMiddleware",

    # 🖥️ Display API (يعتمد على request)
    "core.middleware.DisplayTokenMiddleware",

    # 💳 اشتراك الداشبورد
    "dashboard.middleware.SubscriptionRequiredMiddleware",

    # 🛡️ Headers إضافية
    "core.middleware.SecurityHeadersMiddleware",

    # Clickjacking
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# -------------------------
# URLs / Templates
# -------------------------
ROOT_URLCONF = "config.urls"

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


# -------------------------
# Database
# -------------------------
if DEBUG:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": dj_database_url.config(
            env="DATABASE_URL",
            conn_max_age=600,
            ssl_require=True,
        )
    }


# -------------------------
# Cache (Redis اختياري)
# -------------------------
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


# -------------------------
# Auth
# -------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# -------------------------
# Locale / Time
# -------------------------
LANGUAGE_CODE = "ar"
TIME_ZONE = os.getenv("TIME_ZONE", "Asia/Riyadh")
USE_I18N = True
USE_TZ = True


# -------------------------
# Static / Media
# -------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

_static_dir = BASE_DIR / "static"
STATICFILES_DIRS = [_static_dir] if exists_dir(_static_dir) else []

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# Cloudinary Media (اختياري وبشكل آمن)
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME") or os.getenv("CLOUDINARY_CLOUD_NAME".lower(), "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY") or os.getenv("CLOUDINARY_API_KEY".lower(), "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET") or os.getenv("CLOUDINARY_API_SECRET".lower(), "")

CLOUDINARY_STORAGE = {
    "CLOUD_NAME": os.getenv("CLOUDINARY_CLOUD_NAME"),
    "API_KEY": os.getenv("CLOUDINARY_API_KEY"),
    "API_SECRET": os.getenv("CLOUDINARY_API_SECRET"),
}

# لا نفعل Cloud storage إلا إذا كانت القيم متوفرة فعلاً
USE_CLOUD_STORAGE = (not DEBUG) and bool(CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET)

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

# WhiteNoise settings
WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_USE_FINDERS = DEBUG

# إذا تبغى تمنع 500 بسبب أي static ناقص (غير مفضل للإطلاق)، فعّلها من ENV فقط:
# WHITENOISE_MANIFEST_STRICT=False
WHITENOISE_MANIFEST_STRICT = env_bool("WHITENOISE_MANIFEST_STRICT", "True")


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# -------------------------
# DRF
# -------------------------
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
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.getenv("DRF_ANON_RATE", "60/min"),
        "user": os.getenv("DRF_USER_RATE", "1000/day"),
        # جاهز إذا أضفت DisplayScreenThrottle لاحقًا
        "display_screen": os.getenv("DRF_DISPLAY_SCREEN_RATE", "30/min"),
    },
}


# -------------------------
# Security / Proxy (Render)
# -------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", "False" if DEBUG else "True")

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # أحيانًا تحتاجه JS (حسب تطبيقك)

SECURE_CONTENT_TYPE_NOSNIFF = True

# منع الإطارات (إذا احتجت تضمين لاحقًا غيّره إلى SAMEORIGIN عبر ENV)
X_FRAME_OPTIONS = os.getenv("X_FRAME_OPTIONS", "DENY")

if not DEBUG:
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", "31536000")
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", "True")
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", "True")
    SECURE_REFERRER_POLICY = os.getenv(
        "SECURE_REFERRER_POLICY",
        "strict-origin-when-cross-origin",
    )


# -------------------------
# Logging
# -------------------------
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
            "level": DJANGO_CONSOLE_LEVEL,
        },
    },
    "root": {"handlers": ["console"], "level": DJANGO_LOG_LEVEL},
    "loggers": {
        "django.utils.autoreload": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.server": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "rest_framework": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR" if "test" in sys.argv else "WARNING",
            "propagate": False,
        },
    },
}


# -------------------------
# Auth redirects
# -------------------------
LOGIN_URL = "dashboard:login"
LOGIN_REDIRECT_URL = "dashboard:index"
LOGOUT_REDIRECT_URL = "dashboard:login"


# -------------------------
# Site base url (اختياري)
# -------------------------
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "http://127.0.0.1:8000")
