from .base import *

DEBUG = False

ALLOWED_HOSTS = ["https://miramemoria.com", "https://www.miramemoria.com"]
CSRF_TRUSTED_ORIGINS = ["https://miramemoria.com", "https://www.miramemoria.com"]

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