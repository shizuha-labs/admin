"""
Celery configuration for Shizuha Admin.
"""
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shizuha_admin.settings')

app = Celery('shizuha_admin')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Configure task defaults
app.conf.update(
    task_default_queue='shizuha_admin',
    task_default_exchange='shizuha_admin',
    task_default_routing_key='shizuha_admin',
)
