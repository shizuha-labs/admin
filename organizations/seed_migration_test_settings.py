"""Isolated settings for historical seed tests; no service startup defaults."""
import os
SECRET_KEY=os.environ['SECRET_KEY']
INSTALLED_APPS=['organizations']
DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}}
DEFAULT_AUTO_FIELD='django.db.models.BigAutoField'
USE_TZ=True
class FixtureRouter:
    def db_for_read(self,model,**hints):
        return 'company_seed_fixture' if model._meta.app_label=='organizations' else None
    db_for_write=db_for_read
DATABASE_ROUTERS=['organizations.seed_migration_test_settings.FixtureRouter']
