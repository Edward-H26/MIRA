from .base import *
import os

DEBUG = True
ENABLE_DEV_EVENT_LOG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

os.environ.setdefault("CHAT_LOCAL_MODEL_ENABLED", "1")

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'data' / 'test_db.sqlite3',
    }
}

os.makedirs(BASE_DIR / "log", exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "event": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "dev_event_file": {
            "level": "INFO",
            "class": "logging.FileHandler",
            "filename": str(BASE_DIR / "log" / "debug.log"),
            "formatter": "event",
            "encoding": "utf-8",
        },
    },
    "loggers": {
        "event_log_sink": {
            "handlers": ["dev_event_file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
