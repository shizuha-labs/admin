"""Authentication gate for Admin's network-internal service API.

PLAT-4200 introduces service-token authentication without breaking the legacy
tokenless ClusterIP consumers in one unsafe cutover.  Rollout is explicit:

* public-ingress requests are rejected earlier by the ingress guard;
* a tenant bearer token is never accepted as service proof;
* callers carrying the configured token and a service name are authenticated;
* tokenless direct callers remain in logged compatibility mode until every
  consumer is migrated, then ``ADMIN_INTERNAL_SERVICE_TOKEN_ENFORCE`` flips the
  same permission class to fail closed.
"""

import logging

from django.conf import settings
from django.utils.crypto import constant_time_compare
from rest_framework import permissions


logger = logging.getLogger('organizations.internal_auth')

SERVICE_NAME_HEADER = 'HTTP_X_INTERNAL_SERVICE'
SERVICE_TOKEN_HEADER = 'HTTP_X_INTERNAL_SERVICE_TOKEN'


def _hive_signing_keys():
    """Keys accepted for the X-Hive-* envelope, dedicated key first (HIVE-671 P1 #3).

    During the migration window the verifier DUAL-ACCEPTS a request signed +
    tokened with the dedicated Hive-only key (``HIVE_SERVICE_SIGNING_KEY``,
    delivered by the deploy secret ``hive-service-signing-key``) OR the legacy
    shared ``ADMIN_INTERNAL_SERVICE_TOKEN``, so the Hive producer's cutover is
    safe under any deploy interleaving. A later enforcement flip drops the
    shared-token acceptance once every producer signs with the dedicated key.
    """
    keys = []
    dedicated = str(getattr(settings, 'HIVE_SERVICE_SIGNING_KEY', '') or '').strip()
    if dedicated:
        keys.append(dedicated)
    shared = getattr(settings, 'ADMIN_INTERNAL_SERVICE_TOKEN', '') or ''
    if shared and shared not in keys:
        keys.append(shared)
    return keys


def has_valid_service_token(request):
    """Return True only for a named caller with the configured shared token."""
    expected = getattr(settings, 'ADMIN_INTERNAL_SERVICE_TOKEN', '') or ''
    supplied = request.META.get(SERVICE_TOKEN_HEADER, '') or ''
    service_name = (request.META.get(SERVICE_NAME_HEADER, '') or '').strip()
    return bool(
        expected
        and supplied
        and service_name
        and constant_time_compare(supplied, expected)
    )


class InternalServicePermission(permissions.BasePermission):
    """Authorize a service token, with a temporary tokenless ClusterIP bridge."""

    message = 'Service authentication is required for this endpoint.'

    def has_permission(self, request, view):
        service_name = (request.META.get(SERVICE_NAME_HEADER, '') or '').strip()
        if has_valid_service_token(request):
            logger.info('admin-internal-auth mode=service-token service=%s', service_name)
            return True

        # A user/tenant JWT is identity for the public API, never a substitute
        # for service authentication on the internal control plane.
        if request.META.get('HTTP_AUTHORIZATION'):
            logger.warning('admin-internal-auth denied mode=user-bearer service=%s', service_name or 'unknown')
            return False

        enforce = bool(getattr(settings, 'ADMIN_INTERNAL_SERVICE_TOKEN_ENFORCE', False))
        if enforce:
            logger.warning('admin-internal-auth denied mode=missing-or-invalid service=%s', service_name or 'unknown')
            return False

        # Compatibility phase: the ingress guard has already rejected public
        # requests; direct ClusterIP consumers remain available while they add
        # the service token.  This branch is removed by the enforce-mode flip.
        logger.info('admin-internal-auth mode=network-trust-compat service=%s', service_name or 'unknown')
        return True


import hashlib
import hmac
import time
from django.core.cache import cache


class HiveSignedInternalPermission(permissions.BasePermission):
    """Fail-closed Hive-only signed envelope for HIVE-671 membership mutations.

    Requires:
    - X-Internal-Service: shizuha-hive
    - valid shared ADMIN_INTERNAL_SERVICE_TOKEN
    - X-Hive-Timestamp / X-Hive-Nonce / X-Hive-Body-Sha256 / X-Hive-Signature
    - nonce single-use in durable cache
    """

    message = 'Hive signed service authentication required.'

    def has_permission(self, request, view):
        keys = _hive_signing_keys()
        supplied = request.META.get(SERVICE_TOKEN_HEADER, '') or ''
        service_name = (request.META.get(SERVICE_NAME_HEADER, '') or '').strip()
        if service_name != 'shizuha-hive':
            return False
        # The plaintext token header must match exactly one accepted key (the key
        # the producer signed with); that same key must then verify the
        # signature. This dual-accepts the dedicated Hive key or the shared token
        # without ever accepting a signature under a key the caller did not prove.
        matched_key = ''
        for key in keys:
            if key and supplied and constant_time_compare(supplied, key):
                matched_key = key
                break
        if not matched_key:
            return False
        ts = (request.META.get('HTTP_X_HIVE_TIMESTAMP') or '').strip()
        nonce = (request.META.get('HTTP_X_HIVE_NONCE') or '').strip()
        body_sha = (request.META.get('HTTP_X_HIVE_BODY_SHA256') or '').strip()
        sig = (request.META.get('HTTP_X_HIVE_SIGNATURE') or '').strip()
        if not (ts and nonce and body_sha and sig):
            return False
        try:
            ts_i = int(ts)
        except ValueError:
            return False
        if abs(int(time.time()) - ts_i) > 300:
            return False
        # body hash
        try:
            raw = request.body or b''
        except Exception:
            raw = b''
        calc = hashlib.sha256(raw).hexdigest()
        if not constant_time_compare(calc, body_sha):
            return False
        path = request.path
        method = request.method.upper()
        signing_input = "\n".join([method, path, ts, nonce, body_sha])
        expect_sig = hmac.new(matched_key.encode(), signing_input.encode(), hashlib.sha256).hexdigest()
        if not constant_time_compare(expect_sig, sig):
            return False
        # durable nonce (after body+sig verification)
        key = f'admin:hive-nonce:{nonce}'
        try:
            if not cache.add(key, '1', timeout=600):
                return False
        except Exception:
            return False
        # HIVE-671: operation_id must be bound into the signed body for mutations.
        # Header-only operation IDs are not authoritative.
        if request.method.upper() in ('POST', 'PUT', 'PATCH', 'DELETE'):
            import json as _json
            try:
                payload = _json.loads(raw.decode('utf-8') or '{}') if raw else {}
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                return False
            op = str(payload.get('operation_id') or '').strip()
            if not op:
                return False
            request.hive_operation_id = op
        return True
