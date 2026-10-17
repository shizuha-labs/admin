"""PLAT-4927 regression: the org member-services listing must expose each
member's actual service grants (observed from shizuha-id), so an admin can
verify that a grant issued through POST /organizations/<slug>/services/members/
<user_id>/ actually landed. Before this fix the GET returned only membership
metadata (user_id/user_email/role), making the grant/verify contract
untruthful end-to-end.
"""
import threading
import time
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Organization, OrganizationMembership, OrganizationServiceAccess
from .tests import MockUser
from .views import OrgMemberServicesView


class FakeIdResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class MemberServicesListingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(
            name='Personal 3', slug='personal-3', owner_id=3,
        )
        OrganizationMembership.objects.create(
            organization=self.org, user_id=3, user_email='test-owner@shizuha.com',
            role='owner', is_active=True, is_pending=False,
        )
        # An org-creation signal may pre-seed default service rows; upsert so
        # the fixture is exactly pulse+books enabled regardless.
        for slug in ('pulse', 'books'):
            OrganizationServiceAccess.objects.update_or_create(
                organization=self.org, service_slug=slug,
                defaults={'is_enabled': True},
            )
        OrganizationServiceAccess.objects.filter(organization=self.org).exclude(
            service_slug__in=('pulse', 'books')
        ).update(is_enabled=False)

    def _url(self):
        return f'/api/organizations/{self.org.slug}/services/members/'

    def _auth_as_owner(self):
        self.client.force_authenticate(
            user=MockUser(id=3, email='test-owner@shizuha.com'))
        self.client.credentials(HTTP_AUTHORIZATION='Bearer org-admin-token')

    @staticmethod
    def _id_payload(user_id=3, slugs=()):
        """Exact AdminUserServicesView response fields we consume."""
        return {
            'user_id': user_id,
            'username': f'user-{user_id}',
            'email': f'user-{user_id}@shizuha.com',
            'is_staff': False,
            'enabled_services': list(slugs),
        }

    def test_listing_includes_member_service_grants(self):
        """Grants come from shizuha-id and are scoped to the org's services:
        'drive' is enabled for the user globally but not for this org, so the
        org-scoped listing must not show it."""
        self._auth_as_owner()
        id_payload = self._id_payload(slugs=('pulse', 'drive'))
        with patch('requests.get', return_value=FakeIdResponse(200, id_payload)) as rg:
            resp = self.client.get(self._url())

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['org_services'], ['books', 'pulse'])
        member = resp.data['members'][0]
        self.assertEqual(member['user_id'], 3)
        self.assertEqual(member['services'], ['pulse'])
        called_url = rg.call_args[0][0]
        self.assertIn('/auth/admin/users/3/services/', called_url)
        self.assertEqual(
            rg.call_args.kwargs['headers'],
            {'Authorization': 'Bearer org-admin-token'},
        )

    def test_grant_then_list_shows_the_new_service(self):
        """The verify path is truthful after a grant: once shizuha-id reports
        the new slug, the org listing exposes it for that member."""
        self._auth_as_owner()

        empty_payload = self._id_payload()
        with patch('requests.get', return_value=FakeIdResponse(200, empty_payload)):
            before = self.client.get(self._url())
        self.assertEqual(before.data['members'][0]['services'], [])

        with patch('requests.post',
                   return_value=FakeIdResponse(200, {'ok': True})) as rp:
            grant = self.client.post(
                self._url() + '3/',
                {'service_slugs': ['pulse'], 'action': 'grant'},
                format='json',
            )
        self.assertEqual(grant.status_code, 200)
        self.assertEqual(
            rp.call_args.kwargs['json'],
            {'service_slugs': ['pulse'], 'action': 'grant'},
        )

        granted_payload = self._id_payload(slugs=('pulse',))
        with patch('requests.get', return_value=FakeIdResponse(200, granted_payload)):
            after = self.client.get(self._url())
        self.assertEqual(after.data['members'][0]['services'], ['pulse'])

    def test_legacy_or_malformed_provider_shape_is_not_false_empty(self):
        """Only the provider-owned enabled_services envelope is authoritative;
        a different shape must degrade visibly, never claim an empty grant."""
        self._auth_as_owner()
        with patch(
            'requests.get',
            return_value=FakeIdResponse(200, {'results': []}),
        ):
            resp = self.client.get(self._url())

        member = resp.data['members'][0]
        self.assertIsNone(member['services'])
        self.assertEqual(
            member['services_error'], 'identity service response invalid'
        )

    def test_provider_response_is_bound_to_the_requested_member(self):
        """A valid grant envelope for another user must not be misattributed."""
        self._auth_as_owner()
        with patch(
            'requests.get',
            return_value=FakeIdResponse(
                200, self._id_payload(user_id=999, slugs=('pulse',))
            ),
        ):
            resp = self.client.get(self._url())

        member = resp.data['members'][0]
        self.assertIsNone(member['services'])
        self.assertEqual(
            member['services_error'], 'identity service response invalid'
        )

    def test_identity_failure_degrades_that_row_not_the_listing(self):
        self._auth_as_owner()
        with patch('requests.get', return_value=FakeIdResponse(502, {'error': 'down'})):
            resp = self.client.get(self._url())

        self.assertEqual(resp.status_code, 200)
        member = resp.data['members'][0]
        self.assertIsNone(member['services'])
        self.assertEqual(member['services_error'], 'identity service unavailable')

    def test_member_lookups_are_parallel_and_per_call_timeout_is_bounded(self):
        for user_id in range(
            10, 10 + OrgMemberServicesView.IDENTITY_LOOKUP_WORKERS + 3
        ):
            OrganizationMembership.objects.create(
                organization=self.org,
                user_id=user_id,
                user_email=f'user-{user_id}@shizuha.com',
                role='member',
                is_active=True,
                is_pending=False,
            )
        self._auth_as_owner()

        lock = threading.Lock()
        active = 0
        max_active = 0

        def identity_get(*args, **kwargs):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            user_id = int(args[0].rstrip('/').rsplit('/', 2)[-2])
            return FakeIdResponse(200, self._id_payload(user_id=user_id))

        with patch('requests.get', side_effect=identity_get) as rg:
            resp = self.client.get(self._url())

        self.assertEqual(resp.status_code, 200)
        self.assertGreater(max_active, 1)
        self.assertLessEqual(max_active, OrgMemberServicesView.IDENTITY_LOOKUP_WORKERS)
        self.assertTrue(rg.call_args_list)
        self.assertTrue(all(
            call.kwargs['timeout'] == OrgMemberServicesView.IDENTITY_LOOKUP_TIMEOUT
            for call in rg.call_args_list
        ))

    def test_member_pages_bound_lookups_and_make_every_row_retrievable(self):
        total_extra = OrgMemberServicesView.MEMBER_PAGE_LIMIT + 3
        for user_id in range(10, 10 + total_extra):
            OrganizationMembership.objects.create(
                organization=self.org,
                user_id=user_id,
                user_email=f'user-{user_id:03d}@shizuha.com',
                role='member',
                is_active=True,
                is_pending=False,
            )
        self._auth_as_owner()

        def identity_get(url, **kwargs):
            user_id = int(url.rstrip('/').rsplit('/', 2)[-2])
            return FakeIdResponse(200, self._id_payload(user_id=user_id))

        with patch('requests.get', side_effect=identity_get) as rg:
            first = self.client.get(self._url())
            first_calls = rg.call_count
            second = self.client.get(
                self._url(),
                {'offset': first.data['next_offset']},
            )

        expected_count = total_extra + 1  # includes the owner fixture
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data['count'], expected_count)
        self.assertEqual(first.data['limit'], OrgMemberServicesView.MEMBER_PAGE_LIMIT)
        self.assertEqual(first.data['offset'], 0)
        self.assertEqual(
            first.data['next_offset'], OrgMemberServicesView.MEMBER_PAGE_LIMIT
        )
        self.assertEqual(
            first_calls, OrgMemberServicesView.MEMBER_PAGE_LIMIT
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data['offset'], first.data['next_offset'])
        self.assertIsNone(second.data['next_offset'])
        self.assertEqual(
            rg.call_count - first_calls,
            expected_count - OrgMemberServicesView.MEMBER_PAGE_LIMIT,
        )
        seen_ids = {
            member['user_id']
            for member in first.data['members'] + second.data['members']
        }
        self.assertEqual(seen_ids, {3, *range(10, 10 + total_extra)})

    def test_non_admin_still_forbidden(self):
        OrganizationMembership.objects.create(
            organization=self.org, user_id=7, user_email='viewer@shizuha.com',
            role='viewer', is_active=True, is_pending=False,
        )
        self.client.force_authenticate(
            user=MockUser(id=7, email='viewer@shizuha.com'))
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 403)
