"""Service-boundary authorization for federated Shizuha ID JWTs."""

import re
from urllib.parse import unquote

from django.http import JsonResponse

from .authentication import ShizuhaJWTAuthentication


_INTERNAL_API_MARKER = '/api/internal/'

# Organization list/create/membership is the customer's own workspace, enforced
# again by OrganizationPermission. It must not require the staff `admin`
# service, or shizuha.com/pulse cannot load or create an org.
_ORG_SELF_SERVICE = re.compile(
    r'^/api/organizations(?:'
    r'|/[^/]+'
    r'|/[^/]+/members'
    r'|/[^/]+/members/[^/]+'
    r'|/[^/]+/leave'
    r'|/[^/]+/projects'
    r')$'
)


def request_via_ingress(request):
    """Return whether the request passed through the public HTTP ingress.

    The ingress controller overwrites/appends these forwarding headers before
    proxying.  Direct ClusterIP callers do not carry either header.
    """
    meta = request.META
    return bool(meta.get('HTTP_X_FORWARDED_FOR') or meta.get('HTTP_X_REAL_IP'))


def is_internal_api_path(path):
    """Match canonical/prefixed internal paths after defensive normalization.

    NGINX normally presents a normalized path, but the application guard must
    fail closed if it is ever reached directly with encoded or repeated slashes.
    Decode twice to cover common double-encoding without an unbounded loop.
    """
    normalized = path or ''
    for _ in range(2):
        normalized = unquote(normalized)
    normalized = re.sub(r'/+', '/', normalized).lower().rstrip('/')
    return normalized.endswith('/api/internal') or _INTERNAL_API_MARKER in normalized


class InternalApiIngressGuardMiddleware:
    """Deny public-ingress access to service-to-service Admin endpoints.

    Internal callers use the ClusterIP directly.  A tenant bearer token or a
    spoofed service-name header must never turn the network-internal API into a
    public API, so ingress provenance is checked before DRF authentication.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if is_internal_api_path(request.path) and request_via_ingress(request):
            return JsonResponse(
                {'error': 'Internal API is not available through public ingress.'},
                status=403,
            )
        return self.get_response(request)


class ServiceAccessMiddleware:
    SERVICE_SLUG = 'admin'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith('/api/'):
            return self.get_response(request)
        if '/internal/' in request.path:
            return self.get_response(request)

        # PLAT-434 all-agent read exemption: any /company-os/ read is
        # intentionally outside the admin service boundary.
        if self._is_all_agent_read_path(request.path):
            return self.get_response(request)
        if _is_org_self_service(request.path):
            return self.get_response(request)

        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            try:
                claims = ShizuhaJWTAuthentication().get_validated_token(token)
            except Exception:
                return self.get_response(request)

            if claims.get('is_staff') or claims.get('is_superuser'):
                return self.get_response(request)
            enabled_services = claims.get('enabled_services')
            if enabled_services is not None and self.SERVICE_SLUG not in enabled_services:
                return JsonResponse(
                    {
                        'error': 'You do not have access to this service.',
                        'service': self.SERVICE_SLUG,
                        'code': 'service_access_denied',
                    },
                    status=403,
                )

        return self.get_response(request)

    @staticmethod
    def _is_all_agent_read_path(path: str) -> bool:
        """True for the PLAT-434 read-only Company-OS endpoint.

        Matches ``/api/organizations/<slug>/company-os/`` (normalized, trailing
        slash optional). Only the GET read is exempted by the caller; the path
        check alone is sufficient because the view enforces IsAuthenticated and
        exposes no mutation surface.
        """
        normalized = (path or '').rstrip('/')
        return normalized.endswith('/company-os') and '/api/organizations/' in normalized


def _is_org_self_service(path: str) -> bool:
    """True for the organization APIs Pulse uses to list, create, and join orgs."""
    normalized = unquote(path or '')
    normalized = re.sub(r'/+', '/', normalized).rstrip('/') or '/'
    return _ORG_SELF_SERVICE.match(normalized) is not None
