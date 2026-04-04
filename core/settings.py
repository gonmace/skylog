import os
from decouple import config, Csv

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(PROJECT_DIR)

SECRET_KEY = config('SECRET_KEY')

DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='', cast=Csv())

ADMIN_URL = config('ADMIN_URL', default='admin/')

# Application definition

INSTALLED_APPS = [
    'daphne',
    'home',
    'axes',
    'channels',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'employees',
    'workdays',
    'screenshots',
    'authentication',
    'agent_ws',

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'csp.middleware.CSPMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'axes.middleware.AxesMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]

INSTALLED_APPS += ['tailwind', 'theme']
TAILWIND_APP_NAME = 'theme'

if DEBUG:
    INSTALLED_APPS += ['django_browser_reload']
    MIDDLEWARE += ['django_browser_reload.middleware.BrowserReloadMiddleware']
    INTERNAL_IPS = ['127.0.0.1', '::1']
    NPM_BIN_PATH = r'C:\Program Files\nodejs\npm.cmd'

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'
ASGI_APPLICATION = 'core.asgi.application'

# Database: SQLite por defecto en dev, PostgreSQL si se define POSTGRES_DB
if config('POSTGRES_DB', default=''):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('POSTGRES_DB'),
            'USER': config('POSTGRES_USER'),
            'PASSWORD': config('POSTGRES_PASSWORD'),
            'HOST': config('POSTGRES_HOST', default='postgres'),
            'PORT': config('POSTGRES_PORT', default='5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es'
TIME_ZONE = 'America/La_Paz'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
WHITENOISE_MANIFEST_STRICT = False

STORAGES = {
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
    },
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Email: consola en dev, SMTP en prod si se configura EMAIL_HOST
if config('EMAIL_HOST', default=''):
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = config('EMAIL_HOST')
    EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
    EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
    EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
    EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
    DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='noreply@example.com')
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# ── Seguridad ──────────────────────────────────────────────────────────────────
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
# SameSite=None permite que las cookies se envíen en el iframe cross-origin (sky.redlinegs.com → skylog.redlinegs.com)
# Requiere Secure=True — solo aplica en producción (HTTPS). En dev se usa Lax para evitar loop en admin.
CSRF_COOKIE_SAMESITE = 'None' if not DEBUG else 'Lax'
SESSION_COOKIE_SAMESITE = 'None' if not DEBUG else 'Lax'
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Permitir iframe desde Nextcloud (CSP frame-ancestors es más granular que X-Frame-Options)
# XFrameOptionsMiddleware se elimina del MIDDLEWARE; usamos CSP_FRAME_ANCESTORS en su lugar.

# ── django-axes (protección brute force) ──────────────────────────────────────
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # hora
AXES_LOCKOUT_PARAMETERS = ['ip_address', 'username']

# ── Content Security Policy ───────────────────────────────────────────────────
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'",)
CSP_STYLE_SRC = ("'self'",)
CSP_IMG_SRC = ("'self'", "data:")
CSP_FONT_SRC = ("'self'",)
CSP_CONNECT_SRC = ("'self'", "http://127.0.0.1:7337") if not DEBUG else ("'self'", "ws://localhost:*", "ws://127.0.0.1:*", "http://127.0.0.1:7337")
CSP_FORM_ACTION = ("'self'", "https://sky.redlinegs.com")
CSP_OBJECT_SRC = ("'none'",)
CSP_BASE_URI = ("'self'",)

# ── Django REST Framework ─────────────────────────────────────────────────────
from datetime import timedelta

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/min',
        'user': '300/min',
    },
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=2),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# ── WebSocket / Redis ─────────────────────────────────────────────────────────
REDIS_URL = config('REDIS_URL', default='')

if REDIS_URL:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {'hosts': [REDIS_URL]},
        }
    }
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }

NEXTCLOUD_SERVER_URL = config('NEXTCLOUD_SERVER_URL', default='https://sky.redlinegs.com')
NEXTCLOUD_OAUTH2_CLIENT_ID = config('NEXTCLOUD_OAUTH2_CLIENT_ID', default='')
NEXTCLOUD_OAUTH2_CLIENT_SECRET = config('NEXTCLOUD_OAUTH2_CLIENT_SECRET', default='')
# URI de redirección registrada en Nextcloud — debe coincidir exactamente
NEXTCLOUD_OAUTH2_REDIRECT_URI = config('NEXTCLOUD_OAUTH2_REDIRECT_URI', default='')
# URL a la que se redirige tras autenticación (ej: página de Nextcloud que contiene el iframe)
NEXTCLOUD_RETURN_URL = config('NEXTCLOUD_RETURN_URL', default='')

# Permitir que Nextcloud embeba la app en iframe
CSP_FRAME_ANCESTORS = ("'self'", NEXTCLOUD_SERVER_URL)
SCREENSHOT_STORAGE_PATH = config('SCREENSHOT_STORAGE_PATH', default='screenshots')
_av = {}
exec(open(os.path.join(BASE_DIR, 'agent', 'version.py')).read(), _av)
AGENT_LATEST_VERSION = _av['VERSION']
del _av

# Almacenamiento de capturas en Nextcloud (opcional).
# Si NEXTCLOUD_SCREENSHOTS_USER está definido, las capturas se suben vía WebDAV
# en lugar de guardarse localmente en MEDIA_ROOT.
NEXTCLOUD_SCREENSHOTS_USER = config('NEXTCLOUD_SCREENSHOTS_USER', default='')
NEXTCLOUD_SCREENSHOTS_PASSWORD = config('NEXTCLOUD_SCREENSHOTS_PASSWORD', default='')
NEXTCLOUD_SCREENSHOTS_FOLDER = config('NEXTCLOUD_SCREENSHOTS_FOLDER', default='Skylog/screenshots')

# ── Admins y logging ──────────────────────────────────────────────────────────
_admin_name = config('ADMIN_NAME', default='')
_admin_email = config('ADMIN_EMAIL', default='')
ADMINS = [(_admin_name, _admin_email)] if _admin_name and _admin_email else []
MANAGERS = ADMINS

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'require_debug_false': {'()': 'django.utils.log.RequireDebugFalse'}
    },
    'handlers': {
        'mail_admins': {
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler',
        }
    },
    'loggers': {
        'django.request': {
            'handlers': ['mail_admins'],
            'level': 'ERROR',
            'propagate': True,
        },
    },
}
