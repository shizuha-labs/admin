"""Real historical-model rows in a separate disposable SQLite connection."""
import copy
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from django.db import connections
from django.db.migrations.loader import MigrationLoader


class CompanyOSSeedConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.alias = 'company_seed_fixture'
        config = copy.deepcopy(connections.databases['default'])
        config.update(ENGINE='django.db.backends.sqlite3', NAME=':memory:', OPTIONS={},
                      USER='',PASSWORD='',HOST='',PORT='')
        connections.databases[self.alias] = config
        self.connection = connections[self.alias]
        self.apps = MigrationLoader(None).project_state([('organizations','0009_company_os')]).apps
        self.Organization = self.apps.get_model('organizations','Organization')
        with self.connection.schema_editor() as editor:editor.create_model(self.Organization)
        self.seed = importlib.import_module('organizations.migrations.0010_seed_company_os').seed
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def tearDown(self):
        self.connection.close()
        del connections[self.alias]
        del connections.databases[self.alias]

    def organization(self, identity=1,slug='fixture-global'):
        return self.Organization.objects.using(self.alias).create(pk=identity,name='Fixture Global',slug=slug,owner_id=91)

    def run_seed(self,payload=None):
        filename=''
        if payload is not None:
            path=Path(self.directory.name)/'installation.json'
            path.write_text(json.dumps(payload));filename=str(path)
        with mock.patch.dict(os.environ,{'ADMIN_COMPANY_OS_SEED_FILE':filename}):
            with self.connection.schema_editor() as editor:self.seed(self.apps,editor)

    def payload(self, targets):
        return {'schema':'shizuha.company-os-seed.v1','organizations':targets}

    def target(self,identity=1,slug='fixture-global'):
        return {'id':identity,'slug':slug,'fields':{'mission':'Generic fixture mission','strategic_bets':['Fixture goal']}}

    def test_no_configuration_does_not_seed_installation_strategy(self):
        organization=self.organization()
        self.run_seed()
        organization.refresh_from_db(using=self.alias)
        self.assertTrue(organization.mission == '', 'unconfigured installation data must remain empty')
        self.assertEqual(organization.strategic_bets,[])

    def test_exact_explicit_target_updates_real_historical_fields(self):
        organization=self.organization()
        self.run_seed(self.payload([self.target()]))
        organization.refresh_from_db(using=self.alias)
        self.assertEqual(organization.mission,'Generic fixture mission')
        self.assertEqual(organization.strategic_bets,['Fixture goal'])

    def test_later_wrong_slug_refuses_before_any_write(self):
        organization=self.organization()
        self.organization(2,'second')
        with self.assertRaises(ValueError):self.run_seed(self.payload([self.target(),self.target(2,'wrong')]))
        organization.refresh_from_db(using=self.alias)
        self.assertTrue(organization.mission == '', 'unconfigured installation data must remain empty')

    def test_substring_name_match_is_never_a_target(self):
        organization=self.organization(41,'fixture-global')
        with self.assertRaises(ValueError):self.run_seed(self.payload([self.target()]))
        organization.refresh_from_db(using=self.alias)
        self.assertTrue(organization.mission == '', 'unconfigured installation data must remain empty')

    def test_bad_payload_and_duplicate_target_are_rejected(self):
        self.organization()
        for payload in ({},self.payload([self.target(),self.target()]),self.payload([dict(self.target(),fields={'owner_id':3})]),self.payload([dict(self.target(),fields={'strategic_bets':'wrong-shape'})])):
            with self.subTest(payload=payload),self.assertRaises(ValueError):self.run_seed(payload)

    def test_empty_fresh_install_needs_no_seed(self):
        self.run_seed()
        self.assertEqual(self.Organization.objects.using(self.alias).count(),0)
