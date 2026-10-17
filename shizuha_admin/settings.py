"""
Django settings for Shizuha Admin (Organization Service).
"""
import os
from pathlib import Path
from datetime import timedelta

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
# This should be the same JWT_SECRET_KEY across all services for token validation
def _required_env(name):
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f'{name} must be configured with a nonblank value')
    return value


SECRET_KEY = (_required_env('JWT_SECRET_KEY') if 'JWT_SECRET_KEY' in os.environ
              else _required_env('SECRET_KEY'))

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DEBUG', '1') == '1'

ALLOWED_HOSTS = [value.strip() for value in os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if value.strip()]
CSRF_TRUSTED_ORIGINS = [value.strip() for value in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',') if value.strip()]

# URL Configuration - no FORCE_SCRIPT_NAME needed since nginx passes full path

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'drf_spectacular',
    # Local
    'organizations',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # PLAT-4200: internal service routes are ClusterIP-only.  This guard must
    # run before all endpoint/service-access logic so tenant JWTs and spoofed
    # service headers cannot reach an AllowAny internal view through ingress.
    'organizations.middleware.InternalApiIngressGuardMiddleware',
    'organizations.middleware.ServiceAccessMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'shizuha_admin.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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

WSGI_APPLICATION = 'shizuha_admin.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'shizuha_admin'),
        'USER': os.environ.get('POSTGRES_USER', 'postgres'),
        'PASSWORD': _required_env('POSTGRES_PASSWORD'),
        'HOST': os.environ.get('POSTGRES_HOST', 'localhost'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = 'shizuha-admin/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Public Admin API mount. The edge proxy exposes /admin/api/ and strips
# /admin before forwarding to Django's /api/ URLConf; pagination links must
# point at the public mount so clients can follow next/previous directly.
ADMIN_INTERNAL_API_PREFIX = os.environ.get('ADMIN_INTERNAL_API_PREFIX', '/api')
ADMIN_PUBLIC_API_PREFIX = os.environ.get('ADMIN_PUBLIC_API_PREFIX', '/admin/api')

# PLAT-4200: staged service authentication for /api/internal/*.  The ingress
# guard is immediate; token enforcement flips only after all ClusterIP callers
# have adopted X-Internal-Service + X-Internal-Service-Token.
ADMIN_INTERNAL_SERVICE_TOKEN = os.environ.get('ADMIN_INTERNAL_SERVICE_TOKEN', '')

# PLAT-5343 slice 1 — v2 membership-projection trust boundary (HLD v12 §4.1).
# Fail-closed from the first release. Credentials are bound per principal
# (Security condition S4). Env provisioning (deploy secrets, never in code):
#   SHIZUHA_ADMIN_V2_SERVICE_CREDENTIALS     JSON {"shizuha-id": "<token>"}  (ID→Admin hop)
#   SHIZUHA_ADMIN_V2_ID_SIGNING_PUBLIC_KEY   ID internal-signing public key (PEM); _PREVIOUS for rotation
#   SHIZUHA_ADMIN_V2_SIGNING_PRIVATE_KEY     Admin internal-signing private key (PEM) for derivatives
#   SHIZUHA_ADMIN_V2_PULSE_SERVICE_CREDENTIAL Admin's dedicated credential on the Admin→Pulse hop
import json as _json

def _admin_v2_pem(value):
    """Accept a PEM blob with literal newlines or \\n escapes; '' when unset."""
    raw = str(value or '').strip()
    if not raw:
        return ''
    return raw.replace('\\n', '\n')

ADMIN_V2_INTERNAL_SERVICE_CREDENTIALS = {}
_credentials_env = os.environ.get('SHIZUHA_ADMIN_V2_SERVICE_CREDENTIALS', '')
if _credentials_env:
    try:
        _parsed = _json.loads(_credentials_env)
        if isinstance(_parsed, dict):
            ADMIN_V2_INTERNAL_SERVICE_CREDENTIALS = {
                str(k): str(v) for k, v in _parsed.items() if str(v or '').strip()
            }
    except (ValueError, TypeError):
        pass

ADMIN_V2_ID_SIGNING_PUBLIC_KEYS = [
    pem
    for pem in (
        _admin_v2_pem(os.environ.get('SHIZUHA_ADMIN_V2_ID_SIGNING_PUBLIC_KEY')),
        _admin_v2_pem(os.environ.get('SHIZUHA_ADMIN_V2_ID_SIGNING_PUBLIC_KEY_PREVIOUS')),
    )
    if pem
]
ADMIN_V2_SIGNING_PRIVATE_KEY = os.environ.get('SHIZUHA_ADMIN_V2_SIGNING_PRIVATE_KEY', '')
ADMIN_V2_PULSE_SERVICE_CREDENTIAL = os.environ.get('SHIZUHA_ADMIN_V2_PULSE_SERVICE_CREDENTIAL', '')
# HIVE-671 P1 #3: dedicated Hive-only signing key (deploy secret
# hive-service-signing-key). HiveSignedInternalPermission dual-accepts a request
# signed+tokened with this key OR the legacy shared token during the migration
# window; an enforcement flip later drops the shared-token acceptance.
HIVE_SERVICE_SIGNING_KEY = os.environ.get('HIVE_SERVICE_SIGNING_KEY', '')
ADMIN_INTERNAL_SERVICE_TOKEN_ENFORCE = (
    os.environ.get('ADMIN_INTERNAL_SERVICE_TOKEN_ENFORCE', 'false').lower()
    in ('1', 'true', 'yes')
)

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        # Use custom authentication that supports federated users from Shizuha ID
        'organizations.authentication.ShizuhaJWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'organizations.pagination.AdminPublicPageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

# JWT Configuration - shared secret for validation across services
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': False,
    'SIGNING_KEY': SECRET_KEY,
    'ALGORITHM': 'HS256',
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
}

# Cross-origin access is an explicit deployment decision.
CORS_ALLOW_ALL_ORIGINS = os.environ.get(
    'CORS_ALLOW_ALL_ORIGINS', 'true' if DEBUG else 'false',
).lower() in ('1', 'true', 'yes')
CORS_ALLOWED_ORIGINS = [
    value.strip() for value in os.environ.get('CORS_ALLOWED_ORIGINS', '').split(',')
    if value.strip()
]

# Celery Configuration
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/3')

# HIVE-671: shared Redis cache for cross-pod Hive nonce claim (fail-closed).
_REDIS_CACHE_URL = os.environ.get(
    'ADMIN_CACHE_REDIS_URL',
    os.environ.get('REDIS_URL', CELERY_BROKER_URL),
)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': _REDIS_CACHE_URL,
        'KEY_PREFIX': 'admin',
        'TIMEOUT': 300,
    }
}
CONNECT_SECURITY_EVENT_METRICS_REDIS_URL = os.environ.get(
    'CONNECT_SECURITY_EVENT_METRICS_REDIS_URL', CELERY_BROKER_URL,
)
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/3')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# Celery Queue Configuration
CELERY_TASK_ROUTES = {
    'organizations.*': {'queue': 'shizuha_admin'},
}
CELERY_BEAT_SCHEDULE = {
    'reconcile-pending-kubernetes-jit-uses': {
        'task': 'organizations.tasks.reconcile_pending_kubernetes_jit_uses_task',
        'schedule': 60.0,
    },
}

# OpenAPI/Swagger
SPECTACULAR_SETTINGS = {
    'TITLE': 'Shizuha Admin API',
    'DESCRIPTION': 'Organization and Project Management Service',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

# Cross-service communication
SHIZUHA_ID_API_URL = os.environ.get('SHIZUHA_ID_API_URL', 'http://localhost:8001/api')

# PLAT-4133: authenticated, sanitized boundary-denial events to Connect SIEM-lite.
SHIZUHA_CONNECT_SECURITY_EVENT_URL = os.environ.get(
    'SHIZUHA_CONNECT_SECURITY_EVENT_URL',
    'http://localhost:8019/api/internal/security-events/',
)
CONNECT_SECURITY_EVENT_ORIGIN_SECRET = os.environ.get('CONNECT_SECURITY_EVENT_ORIGIN_SECRET', '')
CONNECT_SECURITY_EVENT_TIMEOUT_SECONDS = float(os.environ.get('CONNECT_SECURITY_EVENT_TIMEOUT_SECONDS', '1.0'))
CONNECT_SECURITY_EVENT_EMIT_ENABLED = os.environ.get('CONNECT_SECURITY_EVENT_EMIT_ENABLED', 'true').lower() in ('1', 'true', 'yes')
ORIGIN_API_URL = os.environ.get(
    'ORIGIN_API_URL', 'http://localhost:3000'
)
ORIGIN_JIT_DISPATCH_TOKEN = os.environ.get('ORIGIN_JIT_DISPATCH_TOKEN', '')
ORIGIN_JIT_DISPATCH_TIMEOUT_SECONDS = float(
    os.environ.get('ORIGIN_JIT_DISPATCH_TIMEOUT_SECONDS', '10')
)
CONNECT_SECURITY_EVENT_DEDUPE_SECONDS = int(os.environ.get('CONNECT_SECURITY_EVENT_DEDUPE_SECONDS', '300'))

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'organizations': {
            'handlers': ['console'],
            'level': 'INFO',
        },
    },
}


# ─────────── OAuth 2.0 Phase 2/4 — advisory claims + enforcement flag ───────
# Used by ShizuhaJWTAuthentication to log aud/iss mismatches and optionally
# reject tokens whose `aud` doesn't include this service. Defaults keep
# Phase 2 (advisory only) behavior; flip SHIZUHA_AUD_ENFORCE to True once
# advisory logs show clean traffic.
import os as _os
SHIZUHA_SERVICE_NAME = _os.environ.get('SHIZUHA_SERVICE_NAME', 'admin')
SHIZUHA_EXPECTED_ISSUER = _os.environ.get(
    'SHIZUHA_EXPECTED_ISSUER',
    'http://localhost:8001',
)
SHIZUHA_AUD_ENFORCE = _os.environ.get('SHIZUHA_AUD_ENFORCE', '').lower() in ('1', 'true', 'yes')
