"""Regression coverage for authenticated organization-list cache policy."""

from unittest.mock import patch

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from .models import Organization, OrganizationMembership


class TestUser:
    """Small authenticated identity compatible with the API test client."""

    def __init__(self, user_id, email):
        self.id = user_id
        self.email = email
        self.username = 'hritik'
        self.is_staff = False
        self.is_superuser = False
        self.is_authenticated = True
        self.enabled_services = None


class OrganizationCachePolicyTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = TestUser(10, 'member@acme.com')
        self.organization = Organization.objects.create(
            name='Acme Corp',
            slug='acme-corp',
            owner_id=self.user.id,
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user_id=self.user.id,
            user_email=self.user.email,
            role='owner',
            is_pending=False,
        )
        self.client.force_authenticate(user=self.user)

    @patch('organizations.views.permissions.IsAuthenticated.has_permission', return_value=True)
    def test_authenticated_list_is_never_cached_or_site_data_cleared(self, _permission):
        response = self.client.get(
            '/api/organizations/',
            HTTP_REFERER='https://shizuha.com/books/computax',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('no-cache', response['Cache-Control'])
        self.assertIn('must-revalidate', response['Cache-Control'])
        self.assertIn('Authorization', response['Vary'])
        self.assertEqual(response['Pragma'], 'no-cache')
        self.assertEqual(response['Expires'], '0')
        self.assertNotIn('Clear-Site-Data', response)
        self.assertNotIn('shizuha_computax_cache_epoch', response.cookies)
