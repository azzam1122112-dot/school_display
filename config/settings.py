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


def env_int_clamped(name: str, default: int, min_v: int, max_v: int) -> int:
    try:
        v = int(os.getenv(name, str(default)).strip())
    except Exception:
        v = int(default)
    return max(int(min_v), min(int(max_v), int(v)))


# =========================
# Base
# =========================
BASE_DIR = Path(__file__).resolve().parent.parent

# مهم: خلي DEBUG True افتراضيًا محليًا لتفادي مشاكل SSL/Redirect إذا ما عندك .env
DEBUG = env_bool("DEBUG", "True")

# Optional: enable noisy middleware debug prints (default off).
MIDDLEWARE_DEBUG = env_bool("MIDDLEWARE_DEBUG", "False")

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
# Feature Flags: Realtime WebSocket Push
# =========================
# Phase 0-1: False (infrastructure only)
# Phase 2-3: Gradual rollout (per-school flag TBD)
DISPLAY_WS_ENABLED = env_bool("DISPLAY_WS_ENABLED", "False")

# Allow multiple devices per screen token (HTTP + WS must respect this)
DISPLAY_ALLOW_MULTI_DEVICE = env_bool("DISPLAY_ALLOW_MULTI_DEVICE", "False")



# =========================
# Origin snapshot TTL (seconds)
# Used by schedule.api_views.snapshot origin-only caching/ETag.
# =========================
try:
    DISPLAY_SNAPSHOT_TTL = int(
        os.environ.get("DISPLAY_SNAPSHOT_TTL", str(DISPLAY_SNAPSHOT_CACHE_TTL))
    )
except Exception:
    DISPLAY_SNAPSHOT_TTL = DISPLAY_SNAPSHOT_CACHE_TTL

DISPLAY_SNAPSHOT_TTL = max(1, min(60, DISPLAY_SNAPSHOT_TTL))


# =========================
# Phase 2: Dynamic Snapshot TTLs
# =========================
# Active window school-snapshot TTL (15–20s)
try:
    DISPLAY_SNAPSHOT_ACTIVE_TTL = int(os.getenv("DISPLAY_SNAPSHOT_ACTIVE_TTL", "15"))
except Exception:
    DISPLAY_SNAPSHOT_ACTIVE_TTL = 15

DISPLAY_SNAPSHOT_ACTIVE_TTL = max(15, min(20, DISPLAY_SNAPSHOT_ACTIVE_TTL))


# Outside active window: steady snapshot TTL cap (1h–24h)
try:
    DISPLAY_SNAPSHOT_STEADY_MAX_TTL = int(os.getenv("DISPLAY_SNAPSHOT_STEADY_MAX_TTL", "86400"))
except Exception:
    DISPLAY_SNAPSHOT_STEADY_MAX_TTL = 86400

DISPLAY_SNAPSHOT_STEADY_MAX_TTL = max(3600, min(86400, DISPLAY_SNAPSHOT_STEADY_MAX_TTL))


# Throttled cache metrics log interval (seconds)
try:
    DISPLAY_SNAPSHOT_CACHE_METRICS_INTERVAL_SEC = int(
        os.getenv("DISPLAY_SNAPSHOT_CACHE_METRICS_INTERVAL_SEC", "600")
    )
except Exception:
    DISPLAY_SNAPSHOT_CACHE_METRICS_INTERVAL_SEC = 600

DISPLAY_SNAPSHOT_CACHE_METRICS_INTERVAL_SEC = max(60, min(3600, DISPLAY_SNAPSHOT_CACHE_METRICS_INTERVAL_SEC))


# =========================
# Status polling log throttles (seconds)
# Used by schedule.api_views.status to avoid log storms at scale.
# =========================
# General throttle (legacy + sampled 304 logs fallback)
DISPLAY_STATUS_LOG_INTERVAL_SEC = env_int_clamped("DISPLAY_STATUS_LOG_INTERVAL_SEC", 300, 30, 3600)

# Throttle for status 200 (revision changed): log at most once per (school_id, rev) per window.
DISPLAY_STATUS_200_LOG_INTERVAL_SEC = env_int_clamped("DISPLAY_STATUS_200_LOG_INTERVAL_SEC", 120, 10, 3600)

# Throttle for operational warnings (e.g., failed token->school resolve)
DISPLAY_STATUS_WARN_LOG_INTERVAL_SEC = env_int_clamped("DISPLAY_STATUS_WARN_LOG_INTERVAL_SEC", 300, 30, 3600)


# =========================
# Status polling metrics (best-effort; cache-only)
# Used to confirm /api/display/status is cache-only at scale.
# =========================
DISPLAY_STATUS_METRICS_ENABLED = env_bool("DISPLAY_STATUS_METRICS_ENABLED", "False")
DISPLAY_STATUS_METRICS_SAMPLE_EVERY = env_int_clamped("DISPLAY_STATUS_METRICS_SAMPLE_EVERY", 50, 1, 1000)
DISPLAY_STATUS_METRICS_KEY_TTL = env_int_clamped("DISPLAY_STATUS_METRICS_KEY_TTL", 86400, 60, 86400 * 14)


# Build/revision identifier (optional; used for diagnostics headers)
APP_REVISION = (
    os.getenv("APP_REVISION")
    or os.getenv("RENDER_GIT_COMMIT")
    or os.getenv("GIT_COMMIT")
    or os.getenv("SOURCE_VERSION")
    or ""
).strip()


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
# School-level snapshot cache (shared between tokens)
# Tunable via ENV with safe clamps.
# =========================
SCHOOL_SNAPSHOT_TTL = env_int_clamped("SCHOOL_SNAPSHOT_TTL", 1200, 60, 3600)  # default 20 minutes
SCHOOL_SNAPSHOT_LOCK_TTL = env_int_clamped("SCHOOL_SNAPSHOT_LOCK_TTL", 8, 3, 30)
try:
    SCHOOL_SNAPSHOT_WAIT_TIMEOUT = float(os.getenv("SCHOOL_SNAPSHOT_WAIT_TIMEOUT", "0.7"))
except Exception:
    SCHOOL_SNAPSHOT_WAIT_TIMEOUT = 0.7
SCHOOL_SNAPSHOT_WAIT_TIMEOUT = max(0.1, min(2.0, SCHOOL_SNAPSHOT_WAIT_TIMEOUT))


# =========================
# Hosts / CSRF
# =========================
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
    # ASGI server for WebSocket support (must be first)
    "daphne",
    
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

    # WebSocket support
    "channels",

    # Project apps
    "core.apps.CoreConfig",
    "schedule.apps.ScheduleConfig",
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

    # Hard redirect legacy favicon path before WhiteNoise.
    "core.middleware.StaticFaviconRedirectMiddleware",

    # Phase 1: ensure /api/display/snapshot/* is edge-cacheable and cookie/vary-free.
    # Note: Django executes response middleware in reverse order.
    # Placing this BEFORE WhiteNoise ensures it runs AFTER WhiteNoise on the response path.
    "core.middleware.SnapshotEdgeCacheMiddleware",

    # Diagnostics: detect which endpoint actually produces StreamingHttpResponse under ASGI.
    # Place BEFORE WhiteNoise so it runs AFTER WhiteNoise on the response path.
    "core.middleware.StreamingResponseProbeMiddleware",

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
# URLs / WSGI / ASGI
# =========================
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# =========================
# Templates
# =========================
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
# Cache (Redis if REDIS_URL exists) - باستخدام django-redis ✅
# =========================
REDIS_URL = os.getenv("REDIS_URL", "").strip()

# Default cache TTL as a safety net (seconds).
# Per-key timeouts in the codebase can still override this.
DEFAULT_CACHE_TIMEOUT = env_int("CACHE_DEFAULT_TIMEOUT", str(60 * 30))  # 30 minutes

if REDIS_URL:
    # ✅ تحسينات مهمة:
    # - backend الصحيح لـ django-redis
    # - timeouts قصيرة لمنع التعليق
    # - health_check
    # - retry_on_timeout
    # - connection pooling للحد من استنزاف connections
    # - KEY_PREFIX: لتفادي تعارض مفاتيح بين بيئات/خدمات
    import socket
    
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "TIMEOUT": DEFAULT_CACHE_TIMEOUT,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "SOCKET_CONNECT_TIMEOUT": env_int("REDIS_CONNECT_TIMEOUT", "2"),
                "SOCKET_TIMEOUT": env_int("REDIS_SOCKET_TIMEOUT", "2"),
                "RETRY_ON_TIMEOUT": True,
                "HEALTH_CHECK_INTERVAL": env_int("REDIS_HEALTHCHECK_INTERVAL", "30"),
                # Connection pooling configuration
                "CONNECTION_POOL_KWARGS": {
                    "max_connections": env_int("REDIS_MAX_CONNECTIONS", "50"),
                    "retry_on_timeout": True,
                    "socket_keepalive": True,
                    "socket_keepalive_options": {
                        socket.TCP_KEEPIDLE: 60,
                        socket.TCP_KEEPINTVL: 10,
                        socket.TCP_KEEPCNT: 3,
                    }
                }
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
            "TIMEOUT": DEFAULT_CACHE_TIMEOUT,
        }
    }


# =========================
# Channels Layer (WebSocket)
# =========================
if REDIS_URL:
    # Production-ready configuration for 500+ schools (1500+ screens)
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [REDIS_URL],
                # Capacity: max messages per channel before blocking
                # 1500 screens × ~1 msg/screen during burst = 1500 capacity
                "capacity": env_int("WS_CHANNEL_CAPACITY", "2000"),
                # Expiry: messages auto-delete after N seconds (prevents memory leak)
                "expiry": env_int("WS_MESSAGE_EXPIRY", "60"),
                # Symmetric encryption: optional, adds ~1ms latency but secures Redis traffic
                # "symmetric_encryption_keys": [SECRET_KEY[:32]],  # Uncomment for encryption
            },
        },
    }
else:
    # محليًا: in-memory channel layer (للاختبار فقط)
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer"
        },
    }

# ASGI application for Channels
ASGI_APPLICATION = "config.asgi.application"

# WebSocket configuration (for 500+ schools scale)
WS_MAX_CONNECTIONS_PER_INSTANCE = env_int("WS_MAX_CONNECTIONS", "2000")
WS_PING_INTERVAL_SECONDS = env_int("WS_PING_INTERVAL", "30")
WS_METRICS_LOG_INTERVAL = env_int("WS_METRICS_LOG_INTERVAL", "300")  # 5 minutes


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
    "filters": {
        "snapshot_request_noise": {
            "()": "core.logging_filters.SnapshotRequestNoiseFilter",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
        "request_console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
            "filters": ["snapshot_request_noise"],
        },
    },
    "formatters": {
        "simple": {"format": "[{levelname}] {message}", "style": "{"},
    },
    "loggers": {
        # Keep django.request warnings, but drop expected snapshot polling noise.
        "django.request": {
            "handlers": ["request_console"],
            "level": "WARNING",
            "propagate": False,
        },
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


# =========================
# Site base URL
# =========================
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://school-display.com")
