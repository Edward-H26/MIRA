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

MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'data' / 'db.sqlite3',
    }
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True