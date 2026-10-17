"""Overview + org-services contracts for the live Admin surfaces.

The Superuser Overview used to serialize every org/member/department and
fan out Pulse per org. Settings treated `/organizations/<slug>/services/`
as named objects while the API returned bare slugs. These tests lock the
replacement contracts.
"""
from unittest.mock import patch

import requests
from django.test import TestCase
from rest_framework.test import APIClient

from .models import (
    Department,
    Organization,
    OrganizationMembership,
    OrganizationServiceAccess,
)
from .service_display import service_display_name
from .tests import MockUser


class FakeIdResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class ServiceDisplayNameTests(TestCase):
    def test_known_and_prefixed_slugs(self):
        self.assertEqual(service_display_name('pulse'), 'Pulse')
        self.assertEqual(service_display_name('id'), 'ID')
        self.assertEqual(service_display_name('hr'), 'HR')
        self.assertEqual(service_display_name('shizuha-wiki'), 'Wiki')
        self.assertEqual(service_display_name('custom-tool'), 'Custom Tool')


class SuperuserDashboardPayloadTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.su = MockUser(
            id=1, email='su@example.com', is_staff=True, is_superuser=True,
        )
        for idx in range(3):
            org = Organization.objects.create(
                name=f'Dash Org {idx}',
                slug=f'dash-org-{idx}',
                owner_id=1,
            )
            OrganizationMembership.objects.create(
                organization=org,
                user_id=10 + idx,
                user_email=f'member{idx}@example.com',
                role='member',
                is_active=True,
                is_pending=False,
            )
            Department.objects.create(
                organization=org,
                name=f'Dept {idx}',
                code=f'D{idx}',
            )

    def _get(self, fake_get=None):
        self.client.force_authenticate(self.su)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer su-token')
        ctx = patch('requests.get', side_effect=fake_get) if fake_get else patch(
            'requests.get', return_value=FakeIdResponse(200, {'count': 0, 'results': []}),
        )
        with ctx as mocked:
            response = self.client.get('/api/superuser/dashboard/')
        return response, mocked

    def test_dashboard_returns_counts_without_pulse_fanout_or_org_dump(self):
        captured = []

        def fake_get(url, *args, **kwargs):
            captured.append(url)
            return FakeIdResponse(200, {
                'count': 41,
                'results': [
                    {
                        'id': 3,
                        'username': 'hritik',
                        'email': 'test-owner@shizuha.com',
                        'is_staff': True,
                        'is_superuser': True,
                    },
                    {
                        'id': 9,
                        'username': 'alice',
                        'email': 'alice@example.com',
                        'is_staff': False,
                        'is_superuser': False,
                    },
                ],
            })

        response, _ = self._get(fake_get)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            data['stats']['total_organizations'],
            Organization.objects.filter(is_active=True).count(),
        )
        self.assertEqual(
            data['stats']['total_members'],
            OrganizationMembership.objects.filter(is_active=True).count(),
        )
        self.assertEqual(
            data['stats']['total_departments'],
            Department.objects.filter(is_active=True).count(),
        )
        self.assertGreaterEqual(data['stats']['total_organizations'], 3)
        self.assertGreaterEqual(data['stats']['total_departments'], 3)
        self.assertEqual(data['stats']['total_users'], 41)
        self.assertEqual(data['stats']['total_pulse_projects'], 0)
        self.assertEqual(data['organizations'], [])
        self.assertEqual(data['users'][0]['username'], 'hritik')
        self.assertEqual(len(data['users']), 2)
        self.assertTrue(any('/internal/admin/users/' in url for url in captured))
        self.assertFalse(any('/projects/' in url for url in captured))

    def test_id_timeout_still_returns_local_counts(self):
        def fake_get(url, *args, **kwargs):
            raise requests.Timeout('id down')

        response, _ = self._get(fake_get)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(data['stats']['total_organizations'], 3)
        self.assertEqual(data['stats']['total_users'], 0)
        self.assertEqual(data['users'], [])


class OrgServiceListContractTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(
            name='Services Org', slug='services-org', owner_id=3,
        )
        OrganizationMembership.objects.create(
            organization=self.org,
            user_id=3,
            user_email='owner@example.com',
            role='owner',
            is_active=True,
            is_pending=False,
        )
        OrganizationServiceAccess.objects.update_or_create(
            organization=self.org,
            service_slug='pulse',
            defaults={'is_enabled': True},
        )
        OrganizationServiceAccess.objects.update_or_create(
            organization=self.org,
            service_slug='hive',
            defaults={'is_enabled': False},
        )

    def test_member_list_returns_named_objects(self):
        self.client.force_authenticate(
            MockUser(id=3, email='owner@example.com'),
        )
        response = self.client.get(f'/api/organizations/{self.org.slug}/services/')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        by_slug = {row['slug']: row for row in payload['services']}
        self.assertTrue(all(isinstance(row, dict) for row in payload['services']))
        self.assertEqual(by_slug['pulse']['name'], 'Pulse')
        self.assertTrue(by_slug['pulse']['is_enabled'])
        self.assertEqual(by_slug['hive']['name'], 'Hive')
        self.assertFalse(by_slug['hive']['is_enabled'])
        self.assertNotIn('pulse', payload['services'])
