from .base import *

DEBUG = False

ALLOWED_HOSTS = ["<your-username>.pythonanywhere.com"]

CSRF_TRUSTED_ORIGINS = ["https://<your-username>.pythonanywhere.com"]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'data' / 'db.sqlite3',
    }
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True