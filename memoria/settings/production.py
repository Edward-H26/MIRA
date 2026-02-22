from .base import *

DEBUG = False

ALLOWED_HOSTS = ['*']

MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'data' / 'db.sqlite3',
    }
}