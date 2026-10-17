"""PLAT-4200: Admin's service-to-service API must not be public.

The public edge mounts both ``/admin/api/`` and ``/shizuha-admin/api/``.  All
``/api/internal/`` routes intentionally remain available to direct ClusterIP
callers during the staged service-auth migration, but the public ingress must
deny them even when an attacker supplies a tenant JWT or service-name header.
"""

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase

from organizations.middleware import (
    InternalApiIngressGuardMiddleware,
    is_internal_api_path,
    request_via_ingress,
)


_SENTINEL = object()


class InternalApiIngressGuardTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = InternalApiIngressGuardMiddleware(lambda request: _SENTINEL)

    def test_ingress_request_is_forbidden_even_with_tenant_bearer(self):
        request = self.factory.get(
            '/api/internal/users/7/memberships/',
            HTTP_X_FORWARDED_FOR='203.0.113.7',
            HTTP_AUTHORIZATION='Bearer tenant-jwt',
        )

        response = self.middleware(request)

        self.assertEqual(response.status_code, 403)

    def test_ingress_request_is_forbidden_with_spoofed_service_header(self):
        request = self.factory.post(
            '/api/internal/permissions/check/',
            HTTP_X_FORWARDED_FOR='203.0.113.7',
            HTTP_X_INTERNAL_SERVICE='shizuha-id',
        )

        response = self.middleware(request)

        self.assertEqual(response.status_code, 403)

    def test_x_real_ip_also_marks_public_ingress(self):
        request = self.factory.get(
            '/api/internal/organizations/1/members/',
            HTTP_X_REAL_IP='203.0.113.7',
        )

        self.assertEqual(self.middleware(request).status_code, 403)

    def test_ingress_prefixed_internal_path_is_forbidden(self):
        request = self.factory.get(
            '/shizuha-admin/api/internal/users/7/memberships/',
            HTTP_X_FORWARDED_FOR='203.0.113.7',
        )

        self.assertEqual(self.middleware(request).status_code, 403)

    def test_direct_clusterip_internal_request_passes(self):
        request = self.factory.get('/api/internal/users/7/memberships/')

        self.assertIs(self.middleware(request), _SENTINEL)

    def test_non_internal_request_passes_through_ingress(self):
        request = self.factory.get(
            '/api/organizations/',
            HTTP_X_FORWARDED_FOR='203.0.113.7',
        )

        self.assertIs(self.middleware(request), _SENTINEL)

    def test_path_and_provenance_helpers_fail_closed(self):
        self.assertTrue(is_internal_api_path('/api/internal/'))
        self.assertTrue(is_internal_api_path('/api/internal/users/7/'))
        self.assertTrue(is_internal_api_path('/shizuha-admin/api/internal/users/7/'))
        self.assertTrue(is_internal_api_path('/admin/api//internal/users/7/'))
        self.assertTrue(is_internal_api_path('/admin/api/internal%2Fusers/7/'))
        self.assertTrue(is_internal_api_path('/ADMIN/API/INTERNAL/users/7/'))
        self.assertFalse(is_internal_api_path('/api/organizations/'))
        self.assertFalse(is_internal_api_path('/api/internality/users/7/'))
        self.assertTrue(
            request_via_ingress(
                self.factory.get('/x', HTTP_X_FORWARDED_FOR='203.0.113.7')
            )
        )
        self.assertFalse(request_via_ingress(self.factory.get('/x')))

    def test_guard_is_wired_before_service_access_middleware(self):
        guard = 'organizations.middleware.InternalApiIngressGuardMiddleware'
        service_access = 'organizations.middleware.ServiceAccessMiddleware'

        self.assertIn(guard, settings.MIDDLEWARE)
        self.assertLess(settings.MIDDLEWARE.index(guard), settings.MIDDLEWARE.index(service_access))
