"""PLAT-5343 slice 1 — Admin v2 subject-assertion boundary (ID→Admin hop).

Admin sits in the middle of the acyclic projection (HLD v12 §4.1/§4.3):

1. **Validate** the ID-issued subject assertion on
   ``POST /api/internal/v2/project-memberships:resolve`` — issuer
   ``shizuha-id``, audience ``shizuha-admin``, scope
   ``membership-projection:resolve``, decimal positive-integer ``sub``,
   canonical ``email`` when known, ``iat``/``exp ≤ +5s``, ``jti``, signed with
   ID's dedicated internal-signing key under the S1 algorithm allowlist
   (EdDSA/ES256 only — ``alg: none``/missing-``alg``/RS-HS confusion are
   validation failures, never a fallback).

2. **Emit** the Admin-signed derivative assertion for the Admin→Pulse hop —
   ``iss=shizuha-admin``, ``aud=shizuha-pulse``, scope
   ``project-membership-candidates:resolve``, the validated ``sub``/``email``,
   a fresh ``jti``, ``exp ≤ +5s``, and ``parent_assertion_sha256`` = SHA-256 of
   the exact parent ID assertion compact JWT that was validated. Pulse never
   accepts the ID assertion directly and never accepts caller-supplied aliases.

Stated Security-condition semantics (identical to the Pulse hop module):

- **S3 clock skew:** a stated ``CLOCK_SKEW_TOLERANCE_SECONDS`` (2 s) on both
  ``iat`` (future) and ``exp`` (past) validation — zero stated skew
  re-introduces the intermittent-failure-class auth flaps on the mint path.
- **S3 jti replay:** single-use denylist with exp-bound retention on the
  *inbound* (ID→Admin) assertion; cache-backend loss degrades to
  exp-bound-only (logged), safe because the assertion is read-only,
  scope-bound, and lives ≤5 s. The emitted derivative always carries a fresh
  ``jti`` (uuid4) so Pulse's denylist never sees a reuse.
- **S4 header↔credential binding:** the ID credential is configured per bound
  principal; a credential is accepted only when ``X-Internal-Service`` names
  exactly its principal.

``sub`` is the identity; the asserted email is a bound attribute used only for
legacy email-only rows. Nothing from the request body, query string, or any
tenant token can supply or override ``sub``/``email`` — the assertion is
constructed exclusively from the validated parent (matrix row 11).
"""
import hashlib
import logging
import time
import uuid

import jwt
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger('organizations.subject_assertion')

# Security condition S1 (akira 2026-09-09): fixed algorithm allowlist, both hops.
ALLOWED_ALGORITHMS = ('EdDSA', 'ES256')

# HLD §4.1: exp ≤ iat + 5s, receiver-enforced on both hops.
ASSERTION_MAX_LIFETIME_SECONDS = 5

# Security condition S3 (akira 2026-09-09): the stated clock-skew tolerance.
CLOCK_SKEW_TOLERANCE_SECONDS = 2

# Fixed rejection-reason enum (same vocabulary as the Pulse hop module).
REASON_MISSING_HEADERS = 'missing_headers'
REASON_UNKNOWN_CALLER = 'unknown_caller'
REASON_CREDENTIAL_MISMATCH = 'credential_mismatch'
REASON_ASSERTION_MISSING = 'assertion_missing'
REASON_ASSERTION_MALFORMED = 'assertion_malformed'
REASON_ALGORITHM_NOT_ALLOWED = 'algorithm_not_allowed'
REASON_BAD_SIGNATURE = 'bad_signature'
REASON_WRONG_ISSUER = 'wrong_issuer'
REASON_WRONG_AUDIENCE = 'wrong_audience'
REASON_WRONG_SCOPE = 'wrong_scope'
REASON_EXPIRED = 'expired'
REASON_FUTURE_IAT = 'future_iat'
REASON_LIFETIME_EXCEEDED = 'lifetime_exceeded'
REASON_INVALID_SUBJECT = 'invalid_subject'
REASON_INVALID_EMAIL = 'invalid_email'
REASON_MISSING_JTI = 'missing_jti'
REASON_REPLAYED_JTI = 'replayed_jti'
REASON_CALLER_SUPPLIED_IDENTITY = 'caller_supplied_identity'
REASON_NOT_CONFIGURED = 'not_configured'

ALL_REASONS = (
    REASON_MISSING_HEADERS,
    REASON_UNKNOWN_CALLER,
    REASON_CREDENTIAL_MISMATCH,
    REASON_ASSERTION_MISSING,
    REASON_ASSERTION_MALFORMED,
    REASON_ALGORITHM_NOT_ALLOWED,
    REASON_BAD_SIGNATURE,
    REASON_WRONG_ISSUER,
    REASON_WRONG_AUDIENCE,
    REASON_WRONG_SCOPE,
    REASON_EXPIRED,
    REASON_FUTURE_IAT,
    REASON_LIFETIME_EXCEEDED,
    REASON_INVALID_SUBJECT,
    REASON_INVALID_EMAIL,
    REASON_MISSING_JTI,
    REASON_REPLAYED_JTI,
    REASON_CALLER_SUPPLIED_IDENTITY,
    REASON_NOT_CONFIGURED,
)

SERVICE_HEADER = 'HTTP_X_INTERNAL_SERVICE'
CREDENTIAL_HEADER = 'HTTP_X_INTERNAL_SERVICE_TOKEN'
ASSERTION_HEADER = 'HTTP_X_SHIZUHA_SUBJECT_ASSERTION'

IDENTITY_BODY_KEYS = frozenset({
    'sub', 'subject', 'subject_id', 'user_id', 'email', 'user_email',
    'aliases', 'email_aliases', 'principal',
})

_JTI_CACHE_PREFIX = 'shizuha:admin:v2:subject-assertion:jti:'


class SubjectAssertionRejected(Exception):
    """A v2 internal request failed authentication; carry the fixed reason."""

    def __init__(self, reason: str):
        if reason not in ALL_REASONS:
            raise ValueError(f'unknown subject-assertion rejection reason {reason!r}')
        self.reason = reason
        super().__init__(reason)


def _credential_map():
    """Bound-principal → dedicated credential for the ID→Admin hop (S4)."""
    configured = getattr(settings, 'ADMIN_V2_INTERNAL_SERVICE_CREDENTIALS', None) or {}
    if not isinstance(configured, dict):
        return {}
    return {
        str(principal): str(credential)
        for principal, credential in configured.items()
        if str(principal or '').strip() and str(credential or '').strip()
    }


def _verification_keys():
    """Accepted ID internal-signing public keys (PEM), current first."""
    keys = getattr(settings, 'ADMIN_V2_ID_SIGNING_PUBLIC_KEYS', None) or []
    if isinstance(keys, str):
        keys = [keys]
    return [str(key) for key in keys if str(key or '').strip()]


def _signing_key():
    """Admin's dedicated internal-signing private key (PEM) for derivatives."""
    key = str(getattr(settings, 'ADMIN_V2_SIGNING_PRIVATE_KEY', '') or '').strip()
    return key.replace('\\n', '\n') if key else ''


def _constant_time_equal(a: str, b: str) -> bool:
    from django.utils.crypto import constant_time_compare
    return bool(a) and bool(b) and constant_time_compare(a, b)


def _reject_if_body_carries_identity(body) -> None:
    if not isinstance(body, dict):
        return
    for key in body:
        if str(key).strip().lower() in IDENTITY_BODY_KEYS:
            raise SubjectAssertionRejected(REASON_CALLER_SUPPLIED_IDENTITY)


def _parse_and_check_header(assertion: str) -> dict:
    try:
        header = jwt.get_unverified_header(assertion)
    except jwt.exceptions.PyJWTError:
        raise SubjectAssertionRejected(REASON_ASSERTION_MALFORMED)
    if not isinstance(header, dict) or not header.get('alg'):
        raise SubjectAssertionRejected(REASON_ALGORITHM_NOT_ALLOWED)
    if header.get('alg') not in ALLOWED_ALGORITHMS:
        raise SubjectAssertionRejected(REASON_ALGORITHM_NOT_ALLOWED)
    return header


def _verify_signature(assertion: str, keys):
    for key in keys:
        try:
            return jwt.decode(
                assertion,
                key,
                algorithms=list(ALLOWED_ALGORITHMS),
                options={
                    'verify_exp': False,
                    'verify_iat': False,
                    'verify_aud': False,
                    'verify_iss': False,
                    'verify_sub': False,
                },
            )
        except jwt.exceptions.InvalidSignatureError:
            continue
        except jwt.exceptions.PyJWTError:
            raise SubjectAssertionRejected(REASON_ASSERTION_MALFORMED)
    raise SubjectAssertionRejected(REASON_BAD_SIGNATURE)


def _validate_claims(claims, *, expected_issuer, expected_audience, expected_scope,
                     now) -> dict:
    if not isinstance(claims, dict):
        raise SubjectAssertionRejected(REASON_ASSERTION_MALFORMED)

    if claims.get('iss') != expected_issuer:
        raise SubjectAssertionRejected(REASON_WRONG_ISSUER)
    aud = claims.get('aud')
    aud_values = aud if isinstance(aud, list) else [aud]
    if expected_audience not in aud_values:
        raise SubjectAssertionRejected(REASON_WRONG_AUDIENCE)
    if claims.get('scope') != expected_scope:
        raise SubjectAssertionRejected(REASON_WRONG_SCOPE)

    skew = CLOCK_SKEW_TOLERANCE_SECONDS
    exp = claims.get('exp')
    iat = claims.get('iat')
    if not isinstance(exp, (int, float)) or isinstance(exp, bool):
        raise SubjectAssertionRejected(REASON_ASSERTION_MALFORMED)
    if not isinstance(iat, (int, float)) or isinstance(iat, bool):
        raise SubjectAssertionRejected(REASON_ASSERTION_MALFORMED)
    if exp > iat + ASSERTION_MAX_LIFETIME_SECONDS:
        raise SubjectAssertionRejected(REASON_LIFETIME_EXCEEDED)
    if exp < now - skew:
        raise SubjectAssertionRejected(REASON_EXPIRED)
    if iat > now + skew:
        raise SubjectAssertionRejected(REASON_FUTURE_IAT)

    sub = claims.get('sub')
    if isinstance(sub, bool):
        raise SubjectAssertionRejected(REASON_INVALID_SUBJECT)
    if isinstance(sub, int):
        subject = sub
    elif isinstance(sub, str) and sub.strip().isdigit():
        subject = int(sub.strip())
    else:
        raise SubjectAssertionRejected(REASON_INVALID_SUBJECT)
    if subject <= 0:
        raise SubjectAssertionRejected(REASON_INVALID_SUBJECT)

    email = claims.get('email')
    if email is not None:
        email = str(email).strip().lower()
        if not email or '@' not in email:
            raise SubjectAssertionRejected(REASON_INVALID_EMAIL)
        claims['email'] = email

    jti = claims.get('jti')
    if not isinstance(jti, str) or not jti.strip():
        raise SubjectAssertionRejected(REASON_MISSING_JTI)

    claims['sub'] = subject
    return claims


def _register_jti_use(jti: str, exp: float, now: float) -> None:
    """Single-use denylist with exp-bound retention (stated S3 semantics).

    Cache-backend loss degrades to exp-bound-only protection (logged, never
    silent) — safe for a read-only, scope-bound, ≤5 s assertion.
    """
    retention = int(max(exp - now, 0) + 2 * CLOCK_SKEW_TOLERANCE_SECONDS) + 1
    retention = max(1, min(retention, 30))
    fingerprint = hashlib.sha256(jti.encode('utf-8')).hexdigest()
    key = f'{_JTI_CACHE_PREFIX}{fingerprint}'
    try:
        added = cache.add(key, True, timeout=retention)
    except Exception as exc:  # cache backend outage — stated degradation
        logger.warning('admin-v2-internal-auth jti_denylist_unavailable reason=cache-error class=%s',
                       type(exc).__name__)
        return
    if not added:
        raise SubjectAssertionRejected(REASON_REPLAYED_JTI)


def authenticate_id_assertion(request, *, body=None):
    """Authenticate the ID→Admin hop end-to-end.

    Returns ``(principal, claims, parent_assertion)`` — the parent compact JWT
    is returned so the derivative can bind it by hash. Raises
    :class:`SubjectAssertionRejected` with a fixed-enum reason on failure.
    Never logs assertion contents, credentials, or subject PII.
    """
    service_name = (request.META.get(SERVICE_HEADER, '') or '').strip()
    credential = request.META.get(CREDENTIAL_HEADER, '') or ''
    assertion = request.META.get(ASSERTION_HEADER, '') or ''

    if not service_name and not credential and not assertion:
        raise SubjectAssertionRejected(REASON_MISSING_HEADERS)

    credentials = _credential_map()
    keys = _verification_keys()
    if not credentials or not keys:
        # Fail closed: the v2 path never inherits the tokenless compat mode.
        raise SubjectAssertionRejected(REASON_NOT_CONFIGURED)

    if service_name not in credentials:
        raise SubjectAssertionRejected(REASON_UNKNOWN_CALLER)
    if not _constant_time_equal(credential, credentials[service_name]):
        raise SubjectAssertionRejected(REASON_CREDENTIAL_MISMATCH)

    if not assertion:
        raise SubjectAssertionRejected(REASON_ASSERTION_MISSING)

    _reject_if_body_carries_identity(body)

    _parse_and_check_header(assertion)
    claims = _verify_signature(assertion, keys)
    now = time.time()
    claims = _validate_claims(
        claims,
        expected_issuer='shizuha-id',
        expected_audience='shizuha-admin',
        expected_scope='membership-projection:resolve',
        now=now,
    )
    _register_jti_use(claims['jti'], float(claims['exp']), now)

    logger.info('admin-v2-internal-auth ok service=%s reason=none', service_name)
    return service_name, claims, assertion


def emit_derivative_assertion(parent_assertion, claims):
    """Mint the Admin-signed derivative for the Admin→Pulse hop (HLD §4.1).

    New ``jti``, ``exp ≤ +5s``, ``parent_assertion_sha256`` binding the exact
    parent compact JWT. The subject/email are copied ONLY from the validated
    parent claims — never from request data.
    """
    signing_key = _signing_key()
    if not signing_key:
        raise SubjectAssertionRejected(REASON_NOT_CONFIGURED)
    now = int(time.time())
    derivative = {
        'iss': 'shizuha-admin',
        'aud': 'shizuha-pulse',
        'scope': 'project-membership-candidates:resolve',
        'sub': str(claims['sub']),
        'iat': now,
        'exp': now + ASSERTION_MAX_LIFETIME_SECONDS,
        'jti': str(uuid.uuid4()),
        'parent_assertion_sha256': hashlib.sha256(
            parent_assertion.encode('utf-8')).hexdigest(),
    }
    if claims.get('email'):
        derivative['email'] = claims['email']
    return jwt.encode(derivative, signing_key, algorithm='EdDSA')


def pulse_hop_credential():
    """Admin's dedicated credential for the Admin→Pulse hop (bound principal
    ``shizuha-admin`` on the Pulse side)."""
    return str(getattr(settings, 'ADMIN_V2_PULSE_SERVICE_CREDENTIAL', '') or '')
