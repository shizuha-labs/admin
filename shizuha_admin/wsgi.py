"""
WSGI config for Shizuha Admin project.
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shizuha_admin.settings')
application = get_wsgi_application()
