"""PLAT-4200 service-auth invariants for Admin's internal control plane."""

from django.test import RequestFactory, SimpleTestCase, override_settings

from organizations.internal_auth import InternalServicePermission


class InternalServicePermissionTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.permission = InternalServicePermission()

    @override_settings(
        ADMIN_INTERNAL_SERVICE_TOKEN='service-secret',
        ADMIN_INTERNAL_SERVICE_TOKEN_ENFORCE=True,
    )
    def test_named_service_with_correct_token_is_allowed(self):
        request = self.factory.get(
            '/api/internal/users/7/memberships/',
            HTTP_X_INTERNAL_SERVICE='shizuha-id',
            HTTP_X_INTERNAL_SERVICE_TOKEN='service-secret',
        )

        self.assertTrue(self.permission.has_permission(request, object()))

    @override_settings(
        ADMIN_INTERNAL_SERVICE_TOKEN='service-secret',
        ADMIN_INTERNAL_SERVICE_TOKEN_ENFORCE=True,
    )
    def test_missing_wrong_or_unnamed_token_is_denied_in_enforce_mode(self):
        requests = [
            self.factory.get('/api/internal/users/7/memberships/'),
            self.factory.get(
                '/api/internal/users/7/memberships/',
                HTTP_X_INTERNAL_SERVICE='shizuha-id',
                HTTP_X_INTERNAL_SERVICE_TOKEN='wrong',
            ),
            self.factory.get(
                '/api/internal/users/7/memberships/',
                HTTP_X_INTERNAL_SERVICE_TOKEN='service-secret',
            ),
            self.factory.get(
                '/api/internal/users/7/memberships/',
                HTTP_X_INTERNAL_SERVICE='shizuha-id',
            ),
        ]

        for request in requests:
            with self.subTest(headers=request.META):
                self.assertFalse(self.permission.has_permission(request, object()))

    @override_settings(
        ADMIN_INTERNAL_SERVICE_TOKEN='service-secret',
        ADMIN_INTERNAL_SERVICE_TOKEN_ENFORCE=False,
    )
    def test_tenant_bearer_is_denied_even_during_compatibility_phase(self):
        request = self.factory.get(
            '/api/internal/users/7/memberships/',
            HTTP_AUTHORIZATION='Bearer tenant-jwt',
        )

        self.assertFalse(self.permission.has_permission(request, object()))

    @override_settings(
        ADMIN_INTERNAL_SERVICE_TOKEN='service-secret',
        ADMIN_INTERNAL_SERVICE_TOKEN_ENFORCE=False,
    )
    def test_tokenless_direct_caller_remains_available_during_migration(self):
        request = self.factory.get('/api/internal/users/7/memberships/')

        self.assertTrue(self.permission.has_permission(request, object()))
