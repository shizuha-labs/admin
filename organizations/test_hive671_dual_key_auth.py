"""HIVE-671 P1 #3 — admin HiveSignedInternalPermission dual-key acceptance.

During the migration window the verifier must accept a request signed + tokened
with the DEDICATED Hive-only key (HIVE_SERVICE_SIGNING_KEY) OR the legacy shared
ADMIN_INTERNAL_SERVICE_TOKEN, so the producer's cutover is safe under any deploy
interleaving. A signature under any other key — or a token header that disagrees
with the key that actually signed — is rejected.
"""
import hashlib
import hmac
import time

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory

from organizations.internal_auth import HiveSignedInternalPermission


def _signed_get(path, sign_key, token_header, nonce):
    rf = APIRequestFactory()
    ts = str(int(time.time()))
    body_sha = hashlib.sha256(b"").hexdigest()
    signing_input = "\n".join(["GET", path, ts, nonce, body_sha])
    sig = hmac.new(sign_key.encode(), signing_input.encode(), hashlib.sha256).hexdigest()
    return rf.get(
        path,
        HTTP_X_INTERNAL_SERVICE="shizuha-hive",
        HTTP_X_INTERNAL_SERVICE_TOKEN=token_header,
        HTTP_X_HIVE_AUTH_VERSION="v1",
        HTTP_X_HIVE_TIMESTAMP=ts,
        HTTP_X_HIVE_NONCE=nonce,
        HTTP_X_HIVE_BODY_SHA256=body_sha,
        HTTP_X_HIVE_SIGNATURE=sig,
    )


@override_settings(ADMIN_INTERNAL_SERVICE_TOKEN="shared-tok",
                   HIVE_SERVICE_SIGNING_KEY="dedicated-key")
class HiveDualKeyPermissionTests(SimpleTestCase):
    PATH = "/api/internal/personal-agent-membership/"

    def setUp(self):
        cache.clear()
        self.perm = HiveSignedInternalPermission()

    def test_dedicated_key_accepted(self):
        req = _signed_get(self.PATH, "dedicated-key", "dedicated-key", "adm-nonce-0000000a")
        self.assertTrue(self.perm.has_permission(req, None))

    def test_shared_token_still_accepted(self):
        req = _signed_get(self.PATH, "shared-tok", "shared-tok", "adm-nonce-0000000b")
        self.assertTrue(self.perm.has_permission(req, None))

    def test_unknown_key_rejected(self):
        req = _signed_get(self.PATH, "attacker-key", "attacker-key", "adm-nonce-0000000c")
        self.assertFalse(self.perm.has_permission(req, None))

    def test_token_header_and_signature_key_must_agree(self):
        # Token header claims the shared token (an accepted key) but the signature
        # was made with the dedicated key -> matched_key=shared-tok, signature
        # verifies under shared-tok -> mismatch -> rejected.
        req = _signed_get(self.PATH, "dedicated-key", "shared-tok", "adm-nonce-0000000d")
        self.assertFalse(self.perm.has_permission(req, None))
