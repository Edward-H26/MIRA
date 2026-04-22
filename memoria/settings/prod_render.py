from .base import *
import os

DEBUG = False

os.environ["CHAT_LOCAL_MODEL_ENABLED"] = "0"

ALLOWED_HOSTS = ["miramemoria.com", "www.miramemoria.com", "mira-ydqq.onrender.com"]
CSRF_TRUSTED_ORIGINS = [
    "https://miramemoria.com",
    "https://www.miramemoria.com",
    "https://mira-ydqq.onrender.com",
]

CORS_ALLOWED_ORIGINS = ["https://vega.github.io"]

MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL:
    import dj_database_url
    DATABASES = {
        "default": dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "data" / "db.sqlite3",
        }
    }

SESSION_ENGINE = "app.users.neo4j_session_backend"

AUTHENTICATION_BACKENDS = (
    "app.users.neo4j_auth_backend.Neo4jAuthenticationBackend",
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
)

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_SSL_REDIRECT = True

X_FRAME_OPTIONS = "DENY"

ENABLE_DEV_EVENT_LOG = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "event": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "stdout": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "event",
        },
    },
    "loggers": {
        "event_log_sink": {
            "handlers": ["stdout"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["stdout"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}