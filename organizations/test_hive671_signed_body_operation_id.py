"""HIVE-671: Hive mutations require operation_id in signed body."""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, RequestFactory, override_settings

from organizations.internal_auth import HiveSignedInternalPermission


@override_settings(ADMIN_INTERNAL_SERVICE_TOKEN='test-token')
class HiveSignedBodyOperationIdTests(SimpleTestCase):
    def setUp(self):
        self.perm = HiveSignedInternalPermission()
        self.factory = RequestFactory()

    def _signed_headers(self, method, path, body: bytes):
        import hashlib, hmac, time
        ts = str(int(time.time()))
        nonce = f'n-{ts}-test'
        body_sha = hashlib.sha256(body).hexdigest()
        signing = "\n".join([method, path, ts, nonce, body_sha])
        sig = hmac.new(b'test-token', signing.encode(), hashlib.sha256).hexdigest()
        return {
            'HTTP_X_INTERNAL_SERVICE': 'shizuha-hive',
            'HTTP_X_INTERNAL_SERVICE_TOKEN': 'test-token',
            'HTTP_X_HIVE_TIMESTAMP': ts,
            'HTTP_X_HIVE_NONCE': nonce,
            'HTTP_X_HIVE_BODY_SHA256': body_sha,
            'HTTP_X_HIVE_SIGNATURE': sig,
        }

    @patch('organizations.internal_auth.cache')
    def test_delete_without_operation_id_rejected(self, cache):
        cache.add.return_value = True
        body = b'{}'
        path = '/api/internal/organizations/1/members/2/'
        headers = self._signed_headers('DELETE', path, body)
        req = self.factory.generic('DELETE', path, data=body, content_type='application/json', **headers)
        self.assertFalse(self.perm.has_permission(req, MagicMock()))

    @patch('organizations.internal_auth.cache')
    def test_delete_with_operation_id_accepted(self, cache):
        cache.add.return_value = True
        body = b'{"operation_id":"op-1"}'
        path = '/api/internal/organizations/1/members/2/'
        headers = self._signed_headers('DELETE', path, body)
        req = self.factory.generic('DELETE', path, data=body, content_type='application/json', **headers)
        self.assertTrue(self.perm.has_permission(req, MagicMock()))
        self.assertEqual(req.hive_operation_id, 'op-1')
# HIVE-671: signed body operation_id required for Hive membership mutations

# HIVE-671: Connect Admin lookups require service token
