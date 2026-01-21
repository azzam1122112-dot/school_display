# config/settings.py
from __future__ import annotations

import os
import sys
from pathlib import Path

import dj_database_url

# تحميل .env لو موجود (محليًا)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass


# =========================
# Helpers
# =========================
def env_bool(key: str, default: str = "False") -> bool:
    return os.getenv(key, default).strip().lower() in {"1", "true", "yes", "on"}


def env_int(key: str, default: str) -> int:
    try:
        return int(os.getenv(key, default))
    except Exception:
        return int(default)


def env_list(key: str, default: str = "") -> list[str]:
    raw = os.getenv(key, default).strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def exists_dir(p: Path) -> bool:
    try:
        return p.exists() and p.is_dir()
    except Exception:
        return False


# =========================
# Base
# =========================
BASE_DIR = Path(__file__).resolve().parent.parent

# مهم: خلي DEBUG True افتراضيًا محليًا لتفادي مشاكل SSL/Redirect إذا ما عندك .env
DEBUG = env_bool("DEBUG", "True")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-key-change-me")
if not DEBUG and (not SECRET_KEY or SECRET_KEY == "dev-insecure-key-change-me"):
    raise RuntimeError("SECRET_KEY must be set in production!")


# =========================
# Snapshot cache TTL (seconds)
# Used by schedule.api_views.snapshot server-side caching.
# =========================
try:
    DISPLAY_SNAPSHOT_CACHE_TTL = int(os.environ.get("DISPLAY_SNAPSHOT_CACHE_TTL", "15"))
except Exception:
    DISPLAY_SNAPSHOT_CACHE_TTL = 15

# حدود آمنة حتى لا تكسر الأداء أو تزيد الـ staleness
DISPLAY_SNAPSHOT_CACHE_TTL = max(5, min(30, DISPLAY_SNAPSHOT_CACHE_TTL))


# =========================
# Snapshot Edge cache max-age (seconds)
# Used for Cache-Control on /api/display/snapshot/* to enable short Cloudflare caching.
# Keep it short; Cloudflare Cache Rules should be set to "Edge TTL: Respect origin".
# =========================
try:
    DISPLAY_SNAPSHOT_EDGE_MAX_AGE = int(os.getenv("DISPLAY_SNAPSHOT_EDGE_MAX_AGE", "10"))
except Exception:
    DISPLAY_SNAPSHOT_EDGE_MAX_AGE = 10

DISPLAY_SNAPSHOT_EDGE_MAX_AGE = max(1, min(60, DISPLAY_SNAPSHOT_EDGE_MAX_AGE))


# =========================
# Hosts / CSRF
# =========================
# يسمح بإضافة hosts من env (مفيد عند تغيير الدومين أو إضافة subdomains)
# ملاحظة: لا نخلي env يكتب فوق الافتراضي بالكامل حتى لا يتسبب بقطع الخدمة لو كانت القيمة ناقصة.
_default_allowed_hosts = [
    "school-display.com",
    "www.school-display.com",
    ".school-display.com",
    ".onrender.com",
    "localhost",
    "127.0.0.1",
]
_env_hosts = env_list("ALLOWED_HOSTS", "")
ALLOWED_HOSTS: list[str] = []
for _h in [*_default_allowed_hosts, *_env_hosts]:
    if _h and _h not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_h)

# CSRF_TRUSTED_ORIGINS يجب أن تحتوي scheme
_csrf_env = env_list("CSRF_TRUSTED_ORIGINS", "")
if _csrf_env:
    CSRF_TRUSTED_ORIGINS = _csrf_env
else:
    if DEBUG:
        CSRF_TRUSTED_ORIGINS = [
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ]
    else:
        CSRF_TRUSTED_ORIGINS = [
            "https://school-display.com",
            "https://www.school-display.com",
        ]


# =========================
# Apps
# =========================
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Media
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


# =========================
# Middleware
# =========================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",

    # Phase 1: ensure /api/display/snapshot/* is edge-cacheable and cookie/vary-free.
    # Put it BEFORE WhiteNoise so it runs AFTER it on the response path.
    "core.middleware.SnapshotEdgeCacheMiddleware",

    "whitenoise.middleware.WhiteNoiseMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",

    # Project middleware
    "core.middleware.ActiveSchoolMiddleware",
    "dashboard.middleware.SubscriptionRequiredMiddleware",
    "dashboard.middleware.SupportDashboardOnlyMiddleware",
    "core.middleware.DisplayTokenMiddleware",

    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
]


# =========================
# Templates
# =========================
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
                "dashboard.context_processors.admin_support_ticket_badges",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# =========================
# Database
# =========================
DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=env_int("CONN_MAX_AGE", "600"),
    )
}

# SSL فقط لبوستجرس وفي الإنتاج
try:
    engine = DATABASES["default"].get("ENGINE", "")
    is_postgres = "postgres" in engine
except Exception:
    is_postgres = False

if is_postgres and not DEBUG:
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"].setdefault("sslmode", os.getenv("PGSSLMODE", "require"))


# =========================
# Cache (Redis if REDIS_URL exists)
# =========================
REDIS_URL = os.getenv("REDIS_URL", "").strip()

if REDIS_URL:
    # ✅ تحسينات مهمة:
    # - timeouts قصيرة لمنع التعليق
    # - health_check
    # - retry_on_timeout
    # - KEY_PREFIX: لتفادي تعارض مفاتيح بين بيئات/خدمات
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {
                "socket_connect_timeout": env_int("REDIS_CONNECT_TIMEOUT", "2"),
                "socket_timeout": env_int("REDIS_SOCKET_TIMEOUT", "2"),
                "retry_on_timeout": True,
                "health_check_interval": env_int("REDIS_HEALTHCHECK_INTERVAL", "30"),
            },
            "KEY_PREFIX": os.getenv("CACHE_KEY_PREFIX", "school_display"),
        }
    }
else:
    # محليًا أو بدون Redis
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "school_display_cache",
        }
    }


# =========================
# Password validators
# =========================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# =========================
# Locale
# =========================
LANGUAGE_CODE = "ar"
TIME_ZONE = "Asia/Riyadh"
USE_I18N = True
USE_TZ = True


# =========================
# Sessions (idle timeout)
# =========================
SESSION_COOKIE_AGE = env_int("SESSION_IDLE_TIMEOUT_SECONDS", "3600")
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"


# =========================
# Static / Media
# =========================
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

_static_dir = BASE_DIR / "static"
STATICFILES_DIRS = [_static_dir] if exists_dir(_static_dir) else []

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

USE_CLOUD_STORAGE = (
    (not DEBUG)
    and bool(CLOUDINARY_CLOUD_NAME)
    and bool(CLOUDINARY_API_KEY)
    and bool(CLOUDINARY_API_SECRET)
)

if USE_CLOUD_STORAGE:
    CLOUDINARY_STORAGE = {
        "CLOUD_NAME": CLOUDINARY_CLOUD_NAME,
        "API_KEY": CLOUDINARY_API_KEY,
        "API_SECRET": CLOUDINARY_API_SECRET,
        # ضغط/تحسين تلقائي
        "TRANSFORMATION": {"quality": "auto:good", "fetch_format": "auto"},
    }

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

WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_MANIFEST_STRICT = env_bool("WHITENOISE_MANIFEST_STRICT", "True")

# The Django test runner sets DEBUG=False by default, which activates the manifest storage.
# In local/dev CI runs we may not have run collectstatic; do not fail tests on missing manifest entries.
if "test" in sys.argv:
    WHITENOISE_MANIFEST_STRICT = False
    try:
        STORAGES["staticfiles"]["BACKEND"] = "django.contrib.staticfiles.storage.StaticFilesStorage"
    except Exception:
        pass


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# =========================
# DRF
# =========================
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
}


# =========================
# Security / Proxy
# =========================
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

# لا تفعّل redirect محليًا
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", "True") if not DEBUG else False
SESSION_COOKIE_SECURE = (not DEBUG)
CSRF_COOKIE_SECURE = (not DEBUG)

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# HSTS فقط في الإنتاج
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = (not DEBUG)
SECURE_HSTS_PRELOAD = (not DEBUG)


# =========================
# Logging
# =========================
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "formatters": {
        "simple": {"format": "[{levelname}] {message}", "style": "{"},
    },
    "root": {
        "handlers": ["console"],
        "level": os.getenv("DJANGO_LOG_LEVEL", "INFO"),
    },
}


# =========================
# Auth redirects
# =========================
LOGIN_URL = "dashboard:login"
LOGIN_REDIRECT_URL = "dashboard:index"
LOGOUT_REDIRECT_URL = "dashboard:login"


SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://school-display.com")
