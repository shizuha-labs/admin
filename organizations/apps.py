from django.apps import AppConfig


class OrganizationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'organizations'

    def ready(self):
        # Import signals to register them
        from . import signals  # noqa: F401
