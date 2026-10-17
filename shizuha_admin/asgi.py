"""
ASGI config for Shizuha Admin project.
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shizuha_admin.settings')
application = get_asgi_application()
