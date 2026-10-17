import json
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase
from rest_framework.exceptions import AuthenticationFailed

from organizations.authentication import ShizuhaJWTAuthentication
from organizations.middleware import ServiceAccessMiddleware


class ServiceAccessMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _middleware(self):
        return ServiceAccessMiddleware(lambda request: HttpResponse('ok'))

    def test_drive_only_token_is_denied_at_admin_boundary(self):
        request = self.factory.get('/api/me/', HTTP_AUTHORIZATION='Bearer token')
        with patch(
            'organizations.middleware.ShizuhaJWTAuthentication.get_validated_token',
            return_value={'enabled_services': ['id', 'drive']},
        ):
            response = self._middleware()(request)

        self.assertEqual(response.status_code, 403)
        payload = json.loads(response.content)
        self.assertEqual(payload['code'], 'service_access_denied')
        self.assertEqual(payload['service'], 'admin')

    def test_admin_enabled_token_is_allowed(self):
        request = self.factory.get('/api/me/', HTTP_AUTHORIZATION='Bearer token')
        with patch(
            'organizations.middleware.ShizuhaJWTAuthentication.get_validated_token',
            return_value={'enabled_services': ['id', 'admin']},
        ):
            response = self._middleware()(request)

        self.assertEqual(response.status_code, 200)

    def test_legacy_token_without_enabled_services_is_allowed(self):
        request = self.factory.get('/api/me/', HTTP_AUTHORIZATION='Bearer token')
        with patch(
            'organizations.middleware.ShizuhaJWTAuthentication.get_validated_token',
            return_value={},
        ):
            response = self._middleware()(request)

        self.assertEqual(response.status_code, 200)

    def test_invalid_token_is_left_for_drf_authentication(self):
        request = self.factory.get('/api/me/', HTTP_AUTHORIZATION='Bearer bad')
        with patch(
            'organizations.middleware.ShizuhaJWTAuthentication.get_validated_token',
            side_effect=AuthenticationFailed('bad token'),
        ):
            response = self._middleware()(request)

        self.assertEqual(response.status_code, 200)

    def test_federated_user_preserves_enabled_services_claim(self):
        user = ShizuhaJWTAuthentication().get_user({
            'user_id': 183,
            'email': 'drive-only@example.com',
            'username': 'drive-only',
            'enabled_services': ['id', 'drive'],
        })

        self.assertEqual(user.enabled_services, ['id', 'drive'])


class CompanyOsAllAgentExemptionTests(SimpleTestCase):
    """HIVE-1893: PLAT-434 company-os read is exempt from the admin service gate."""

    def setUp(self):
        self.factory = RequestFactory()

    def _middleware(self):
        return ServiceAccessMiddleware(lambda request: HttpResponse('ok'))

    def test_company_os_read_allowed_without_admin_service(self):
        request = self.factory.get(
            '/api/organizations/shizuha/company-os/',
            HTTP_AUTHORIZATION='Bearer token',
        )
        with patch(
            'organizations.middleware.ShizuhaJWTAuthentication.get_validated_token',
            return_value={'enabled_services': ['id', 'hive']},
        ):
            response = self._middleware()(request)

        self.assertEqual(response.status_code, 200)

    def test_company_os_read_allowed_without_enabled_services(self):
        request = self.factory.get(
            '/api/organizations/shizuha/company-os/',
            HTTP_AUTHORIZATION='Bearer token',
        )
        with patch(
            'organizations.middleware.ShizuhaJWTAuthentication.get_validated_token',
            return_value={},
        ):
            response = self._middleware()(request)

        self.assertEqual(response.status_code, 200)

    def test_non_company_os_admin_path_still_denied_without_admin_service(self):
        request = self.factory.get(
            '/api/me/',
            HTTP_AUTHORIZATION='Bearer token',
        )
        with patch(
            'organizations.middleware.ShizuhaJWTAuthentication.get_validated_token',
            return_value={'enabled_services': ['id', 'hive']},
        ):
            response = self._middleware()(request)

        self.assertEqual(response.status_code, 403)
        payload = json.loads(response.content)
        self.assertEqual(payload['code'], 'service_access_denied')

    def test_org_self_service_does_not_require_the_admin_service(self):
        paths = (
            '/api/organizations/',
            '/api/organizations/personal-1001/',
            '/api/organizations/personal-1001/members/',
            '/api/organizations/personal-1001/projects/',
        )
        for path in paths:
            request = self.factory.post(path, HTTP_AUTHORIZATION='Bearer token')
            with patch(
                'organizations.middleware.ShizuhaJWTAuthentication.get_validated_token',
                return_value={'enabled_services': ['id', 'pulse']},
            ):
                response = self._middleware()(request)
            self.assertEqual(response.status_code, 200, path)

    def test_org_hr_paths_still_require_the_admin_service(self):
        request = self.factory.get(
            '/api/organizations/personal-1001/employees/',
            HTTP_AUTHORIZATION='Bearer token',
        )
        with patch(
            'organizations.middleware.ShizuhaJWTAuthentication.get_validated_token',
            return_value={'enabled_services': ['id', 'pulse']},
        ):
            response = self._middleware()(request)
        self.assertEqual(response.status_code, 403)
