"""External installation settings must honor environment and have no private topology."""
import json
import os
import secrets
import subprocess
import sys
from unittest.mock import patch

from django.test import SimpleTestCase
from organizations.views import SuperuserSystemHealthView


class ExternalConfigurationTests(SimpleTestCase):
    def read_settings(self, extra):
        # Supply required disposable credentials; installation topology stays unset.
        env = {'PATH': os.environ['PATH'], 'DEBUG': '0',
               'JWT_SECRET_KEY': secrets.token_urlsafe(32),
               'POSTGRES_PASSWORD': secrets.token_urlsafe(32), **extra}
        code = "import json; from shizuha_admin import settings as s; print(json.dumps({key: getattr(s, key) for key in " + repr([
            'ALLOWED_HOSTS', 'CSRF_TRUSTED_ORIGINS', 'CORS_ALLOW_ALL_ORIGINS',
            'CORS_ALLOWED_ORIGINS', 'SHIZUHA_EXPECTED_ISSUER', 'ORIGIN_API_URL',
            'SHIZUHA_CONNECT_SECURITY_EVENT_URL', 'ADMIN_PUBLIC_API_PREFIX',
        ]) + "}))"
        return json.loads(subprocess.check_output([sys.executable, '-c', code], env=env, text=True))

    def test_unconfigured_production_does_not_allow_all_origins_or_private_topology(self):
        config = self.read_settings({})
        self.assertFalse(config['CORS_ALLOW_ALL_ORIGINS'])
        self.assertEqual(config['ALLOWED_HOSTS'], ['localhost', '127.0.0.1'])
        self.assertNotIn('shizuha.com', json.dumps(config))
        self.assertNotIn('svc.cluster.local', json.dumps(config))

    def test_external_urls_hosts_and_trusted_origins(self):
        config = self.read_settings({
            'ALLOWED_HOSTS': ' admin.example.test, localhost ',
            'CSRF_TRUSTED_ORIGINS': 'https://app.example.test',
            'CORS_ALLOWED_ORIGINS': 'https://app.example.test',
            'CORS_ALLOW_ALL_ORIGINS': 'false',
            'SHIZUHA_EXPECTED_ISSUER': 'https://app.example.test/id',
            'ORIGIN_API_URL': 'https://code.example.test',
            'SHIZUHA_CONNECT_SECURITY_EVENT_URL': 'http://connect:8019/api/internal/security-events/',
            'ADMIN_PUBLIC_API_PREFIX': '/org/api',
        })
        self.assertEqual(config['ALLOWED_HOSTS'], ['admin.example.test', 'localhost'])
        self.assertEqual(config['CSRF_TRUSTED_ORIGINS'], ['https://app.example.test'])
        self.assertEqual(config['CORS_ALLOWED_ORIGINS'], ['https://app.example.test'])
        self.assertEqual(config['SHIZUHA_EXPECTED_ISSUER'], 'https://app.example.test/id')
        self.assertEqual(config['ORIGIN_API_URL'], 'https://code.example.test')
        self.assertEqual(config['ADMIN_PUBLIC_API_PREFIX'], '/org/api')

    def test_health_list_is_owned_by_deployment(self):
        targets = [{'name': 'wiki', 'url': 'http://wiki:8013/api/health/'}]
        with patch.dict(os.environ, {'SYSTEM_HEALTH_SERVICES': json.dumps(targets), 'REDIS_HOST': 'redis'}):
            self.assertEqual(SuperuserSystemHealthView._configured_service_targets(), targets)
            self.assertEqual(SuperuserSystemHealthView._redis_host(), 'redis')
