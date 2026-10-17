"""
Custom JWT Authentication for Shizuha Admin

This authentication class validates JWT tokens issued by Shizuha ID
without requiring the user to exist in the local database.

In a microservices architecture with unified login (like Atlassian):
- Shizuha ID issues JWT tokens
- Other services (Admin, Pulse, Connect, etc.) validate and trust those tokens
- User data is fetched from the token claims, not the local database
"""

import logging
from rest_framework import authentication, exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


class FederatedUser:
    """
    A lightweight user object for federated authentication.
    Used when the user exists in Shizuha ID but not in the local database.
    """
    def __init__(self, user_id, email=None, username=None, first_name=None, last_name=None,
                 date_joined=None, is_staff=False, is_superuser=False, enabled_services=None):
        from django.utils import timezone
        # PLAT-5042: coerce JWT claim types so IntegerField comparisons stay exact.
        # Mirrors organizations.views._normalize_user_id at the FederatedUser boundary.
        if user_id is not None and not isinstance(user_id, bool):
            try:
                user_id = int(str(user_id).strip())
            except (TypeError, ValueError):
                pass
        self.id = user_id
        self.pk = user_id
        self.email = email or f"user_{user_id}@shizuha.id"
        self.username = username or f"user_{user_id}"
        self.first_name = first_name or ""
        self.last_name = last_name or ""
        self.date_joined = date_joined or timezone.now()
        self.is_authenticated = True
        self.is_active = True
        self.is_anonymous = False
        self.is_staff = is_staff
        self.is_superuser = is_superuser
        # None means legacy/unrestricted; an explicit list is restrictive.
        self.enabled_services = enabled_services

    def __str__(self):
        return f"FederatedUser({self.id})"

    def save(self, *args, **kwargs):
        pass  # No-op for federated users


# ───────────────────────── OAuth 2.0 advisory + enforcement ─────────────────
# Inlined from packages/shizuha-auth: Phase 2/4 of OAuth migration. Services
# that import the shared package should prefer that copy; this duplicate
# keeps parity while the migration to the shared package is in-flight.

def _oauth_advisory_claim_check(validated_token):
    """Log mismatched `aud`/`iss` claims without rejecting. Returns status dict."""
    import os as _os
    from django.conf import settings as _st
    service_name = getattr(_st, 'SHIZUHA_SERVICE_NAME', '') or _os.environ.get('SHIZUHA_SERVICE_NAME', '')
    expected_issuer = getattr(_st, 'SHIZUHA_EXPECTED_ISSUER', '') or _os.environ.get('SHIZUHA_EXPECTED_ISSUER', '')
    aud = validated_token.get('aud')
    if aud is not None and aud not in ('*', ['*']):
        aud_list = aud if isinstance(aud, list) else [aud]
        if service_name and service_name not in aud_list:
            logger.warning(
                f"JWT aud={aud_list!r} does not include service={service_name!r}. "
                f"Phase 2 advisory — token accepted."
            )
    iss = validated_token.get('iss')
    if iss is not None and expected_issuer and iss != expected_issuer:
        logger.warning(
            f"JWT iss={iss!r} does not match expected={expected_issuer!r}. "
            f"Phase 2 advisory — token accepted."
        )


def _oauth_enforce_audience_claim(validated_token):
    """Phase 4: when SHIZUHA_AUD_ENFORCE=True, reject tokens with mismatched aud."""
    import os as _os
    from django.conf import settings as _st
    from rest_framework_simplejwt.exceptions import InvalidToken as _InvalidToken
    enforce = bool(getattr(_st, 'SHIZUHA_AUD_ENFORCE', False)) or \
        _os.environ.get('SHIZUHA_AUD_ENFORCE', '').lower() in ('1', 'true', 'yes')
    if not enforce:
        return
    service_name = getattr(_st, 'SHIZUHA_SERVICE_NAME', '') or _os.environ.get('SHIZUHA_SERVICE_NAME', '')
    if not service_name:
        return
    aud = validated_token.get('aud')
    if aud is None or aud == '*' or aud == ['*']:
        return
    aud_list = aud if isinstance(aud, list) else [aud]
    if service_name not in aud_list:
        logger.warning(
            f"JWT rejected: aud={aud_list!r} does not include required service={service_name!r}"
        )
        raise _InvalidToken(f"Token audience {aud_list} does not include '{service_name}'")


# ───────────────────────── OAuth 2.0 RS256 validation ──────────────────────
# Phase 5 of OAuth migration: accept tokens signed with RS256 (shizuha-id's
# RSA key, public half published at /id/.well-known/jwks.json). Falls back
# from default HS256 validation so legacy tokens keep working during grace.

class _Rs256Token(dict):
    """Lightweight dict-like token — satisfies simplejwt get_user() interface."""
    pass


_JWKS_CACHE = {'keys': {}, 'fetched_at': 0}
_JWKS_TTL = 600  # seconds


def _jwks_fetch_keys():
    import json as _json, os as _os, time as _time, urllib.request as _urlreq
    import jwt as _jwt
    if _time.time() - _JWKS_CACHE['fetched_at'] < _JWKS_TTL and _JWKS_CACHE['keys']:
        return _JWKS_CACHE['keys']
    issuer = (_os.environ.get('SHIZUHA_EXPECTED_ISSUER') or
              'http://shizuha-id:8001').rstrip('/')
    jwks_url = _os.environ.get('SHIZUHA_OAUTH_JWKS_URL') or f'{issuer}/.well-known/jwks.json'
    try:
        resp = _urlreq.urlopen(jwks_url, timeout=5)
        jwks = _json.loads(resp.read())
        _JWKS_CACHE['keys'] = {
            k['kid']: _jwt.algorithms.RSAAlgorithm.from_jwk(_json.dumps(k))
            for k in jwks.get('keys', []) if k.get('kid')
        }
        _JWKS_CACHE['fetched_at'] = _time.time()
    except Exception as _exc:
        logger.warning(f'JWKS fetch from {jwks_url} failed: {_exc}')
    return _JWKS_CACHE['keys']


def _try_rs256_validate(raw_token):
    """Return a _Rs256Token on success, None if not RS256, raise if bad RS256."""
    import jwt as _jwt
    from rest_framework_simplejwt.exceptions import InvalidToken as _InvalidToken
    try:
        header = _jwt.get_unverified_header(raw_token)
    except Exception:
        return None
    if header.get('alg') != 'RS256':
        return None
    kid = header.get('kid')
    keys = _jwks_fetch_keys()
    key = keys.get(kid) if kid else (next(iter(keys.values())) if keys else None)
    if key is None:
        # Re-fetch once in case of key rotation
        _JWKS_CACHE['fetched_at'] = 0
        keys = _jwks_fetch_keys()
        key = keys.get(kid) if kid else (next(iter(keys.values())) if keys else None)
    if key is None:
        raise _InvalidToken(f'No JWKS key available for kid={kid!r}')
    try:
        payload = _jwt.decode(
            raw_token, key=key, algorithms=['RS256'],
            options={'verify_aud': False, 'verify_exp': True},
        )
    except _jwt.PyJWTError as exc:
        raise _InvalidToken(f'RS256 validation failed: {exc}')
    return _Rs256Token(payload)

class ShizuhaJWTAuthentication(JWTAuthentication):
    """
    Custom JWT authentication that works with Shizuha ID tokens.

    Shizuha ID issues the JWT `user_id` claim as the Django User primary key.
    Federated tokens carry an `email` claim; those must return a FederatedUser
    built from token claims because local Admin PKs can collide with ID PKs.
    Local DB lookup is only for legacy Admin-issued tokens without `email`.
    """


    def get_validated_token(self, raw_token):
        """Try HS256 first (legacy); fall back to RS256 via JWKS (Phase 5)."""
        try:
            tok = super().get_validated_token(raw_token)
        except Exception:
            tok = _try_rs256_validate(raw_token)
            if tok is None:
                raise
        # Keep authority denial outside signature fallback: a revoked valid
        # token must never be retried through another algorithm path.
        from .token_revocation import is_token_revoked
        claims = tok.payload if hasattr(tok, 'payload') else tok
        if is_token_revoked(claims, raw_token):
            raise InvalidToken('Token has been revoked')
        return tok

    def _fetch_user_from_shizuha_id(self, user_id):
        """Fetch user details from shizuha-id internal API."""
        import os
        import requests

        shizuha_id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
        try:
            response = requests.get(
                f'{shizuha_id_url}/internal/users/{user_id}/',
                timeout=5
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.warning(f"Failed to fetch user {user_id} from shizuha-id: {e}")
        return None

    def get_user(self, validated_token):
        """
        Get the user from the validated token.

        Federated Shizuha ID token (has `email`) -> FederatedUser from claims.
        Legacy local Admin token (no `email`) -> local User lookup by PK, with
        shizuha-id fetch only as a best-effort legacy fallback.
        """
        _oauth_advisory_claim_check(validated_token)
        _oauth_enforce_audience_claim(validated_token)
        try:
            user_id = validated_token.get('user_id')
            if user_id is None:
                raise InvalidToken('Token contained no recognizable user identification')

            email = validated_token.get('email')
            username = validated_token.get('username')
            first_name = validated_token.get('first_name')
            last_name = validated_token.get('last_name')
            is_staff = validated_token.get('is_staff', False)
            is_superuser = validated_token.get('is_superuser', False)
            enabled_services = validated_token.get('enabled_services')
            if is_staff or is_superuser:
                enabled_services = None

            # CRITICAL: shizuha-id user_ids collide with local PKs. Trust
            # token claims when `email` is present; only fall back to local
            # DB lookup for legacy tokens without email.
            if email:
                return FederatedUser(
                    user_id=user_id,
                    email=email,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    is_staff=is_staff,
                    is_superuser=is_superuser,
                    enabled_services=enabled_services,
                )

            try:
                user = User.objects.get(pk=user_id)
                return user
            except User.DoesNotExist:
                logger.debug(
                    f"User {user_id} not found locally and token has no "
                    f"email claim; fetching from shizuha-id as fallback"
                )
                # Fallback for legacy tokens: fetch from shizuha-id
                user_data = self._fetch_user_from_shizuha_id(user_id)
                if user_data:
                    email = user_data.get('email', email)
                    username = user_data.get('username', username)
                    first_name = user_data.get('first_name', first_name)
                    last_name = user_data.get('last_name', last_name)
                    is_staff = user_data.get('is_staff', is_staff)
                    is_superuser = user_data.get('is_superuser', is_superuser)

                return FederatedUser(
                    user_id=user_id,
                    email=email,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    is_staff=is_staff,
                    is_superuser=is_superuser,
                    enabled_services=enabled_services,
                )

        except KeyError:
            raise InvalidToken('Token contained no recognizable user identification')


class ShizuhaIDAuthentication(authentication.BaseAuthentication):
    """
    Alternative authentication that validates tokens against Shizuha ID service.

    This can be used to verify tokens by calling the Shizuha ID API directly,
    which is useful for:
    - Getting fresh user data
    - Validating token hasn't been revoked
    - Supporting token refresh flows
    """

    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        if not auth_header.startswith('Bearer '):
            return None

        token = auth_header.split(' ')[1]

        try:
            # Validate the token locally first (fast path)
            validated_token = AccessToken(token)
            user_id = validated_token.get('user_id')

            if user_id is None:
                raise exceptions.AuthenticationFailed('Invalid token')

            email = validated_token.get('email')
            username = validated_token.get('username')
            first_name = validated_token.get('first_name')
            last_name = validated_token.get('last_name')
            is_staff = validated_token.get('is_staff', False)
            is_superuser = validated_token.get('is_superuser', False)
            enabled_services = validated_token.get('enabled_services')
            if is_staff or is_superuser:
                enabled_services = None

            # Federated Shizuha ID tokens include email. Do not look up the
            # local Admin DB first: ID user PKs can collide with local PKs.
            if email:
                return (FederatedUser(
                    user_id=user_id,
                    email=email,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    is_staff=is_staff,
                    is_superuser=is_superuser,
                    enabled_services=enabled_services,
                ), validated_token)

            # Legacy local Admin tokens do not carry email; local PK lookup is
            # safe because the token and DB are from the same service.
            try:
                user = User.objects.get(pk=user_id)
                return (user, validated_token)
            except User.DoesNotExist:
                federated_user = FederatedUser(
                    user_id=user_id,
                    email=email,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    is_staff=is_staff,
                    is_superuser=is_superuser,
                    enabled_services=enabled_services,
                )
                return (federated_user, validated_token)

        except TokenError as e:
            raise exceptions.AuthenticationFailed(f'Invalid token: {str(e)}')

    def authenticate_header(self, request):
        return 'Bearer realm="api"'
