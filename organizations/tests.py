"""
Tests for Organization and Member management.

These tests verify:
1. Users can view members within their organization
2. Staff/administrators can view all organizations and their members
"""
import os
import requests

from django.test import SimpleTestCase, TestCase, override_settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from rest_framework import status
from unittest.mock import MagicMock, patch

from .models import (
    EmployeeProfile, Organization, OrganizationMembership, Team, TeamMembership,
)
from .services.team_roster_authority import FleetIdentityUnavailable
from .views import SuperuserDashboardView, SuperuserSystemHealthView


class MockUser:
    """Mock user object for testing without shizuha-id dependency."""
    def __init__(self, id, email, is_staff=False, is_superuser=False):
        self.id = id
        self.email = email
        self.is_staff = is_staff
        self.is_superuser = is_superuser
        self.is_authenticated = True
        self.enabled_services = None  # None = unrestricted (for tests)


class PulseRosterAuthorityWriteTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(
            name='Authority Org', slug='authority-org', owner_id=1,
        )
        membership = OrganizationMembership.objects.create(
            organization=self.org,
            user_id=7,
            user_email='agent@shizuha.com',
            display_name='Agent',
            role='member',
            is_pending=False,
            is_active=True,
        )
        self.profile, _ = EmployeeProfile.objects.get_or_create(
            membership=membership,
            defaults={'job_title': 'Engineer'},
        )
        self.team = Team.objects.create(
            organization=self.org, name='Engineering',
        )
        self.client.force_authenticate(MockUser(
            id=1, email='staff@shizuha.com', is_staff=True, is_superuser=True,
        ))
        self.url = (
            f'/api/organizations/{self.org.slug}/teams/{self.team.pk}/members/'
        )

    @patch('organizations.views.fleet_agent_write_denial')
    def test_agent_add_is_rejected_without_local_persistence(self, denial):
        denial.return_value = {
            'error': 'pulse_team_roster_authority',
            'pulse_command': {'path': '/pulse/api/admin/team-roster/members/'},
        }

        response = self.client.post(
            self.url,
            {'employee_profile_id': self.profile.id, 'role': 'member'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.data)
        self.assertEqual(response.data['error'], 'pulse_team_roster_authority')
        self.assertFalse(TeamMembership.objects.filter(
            team=self.team, employee_profile=self.profile, is_active=True,
        ).exists())

    @patch('organizations.views.fleet_agent_write_denial')
    def test_identity_outage_fails_closed_without_local_persistence(self, denial):
        denial.side_effect = FleetIdentityUnavailable('identity unavailable')

        response = self.client.post(
            self.url,
            {'employee_profile_id': self.profile.id, 'role': 'member'},
            format='json',
        )

        self.assertEqual(
            response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE, response.data,
        )
        self.assertFalse(TeamMembership.objects.filter(
            team=self.team, employee_profile=self.profile, is_active=True,
        ).exists())

    @patch('organizations.views.fleet_agent_write_denial')
    def test_agent_remove_is_rejected_and_legacy_edge_is_not_claimed_authoritative(self, denial):
        edge = TeamMembership.objects.create(
            team=self.team, employee_profile=self.profile, role='member',
        )
        denial.return_value = {
            'error': 'pulse_team_roster_authority',
            'pulse_command': {'path': '/pulse/api/admin/team-roster/members/'},
        }

        response = self.client.delete(f'{self.url}{edge.pk}/')

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.data)
        edge.refresh_from_db()
        self.assertTrue(edge.is_active)

    @patch('organizations.views.fetch_authoritative_team_members')
    @patch('organizations.views.fetch_fleet_agent_emails')
    def test_read_replaces_legacy_agent_edge_with_pulse_projection(self, agents, roster):
        TeamMembership.objects.create(
            team=self.team, employee_profile=self.profile, role='lead',
        )
        agents.return_value = {'agent@shizuha.com'}
        roster.return_value = {'agent@shizuha.com'}

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['routing_count'], 1)
        self.assertEqual(response.data['directory_count'], 0)
        self.assertEqual(response.data['members'][0]['source'], 'pulse-team-roster')
        self.assertEqual(response.data['members'][0]['role'], 'member')

    @patch('organizations.views.fetch_authoritative_team_members', return_value=set())
    @patch('organizations.views.fetch_fleet_agent_emails', return_value={'agent@shizuha.com'})
    def test_authoritative_empty_hides_legacy_agent_edge(self, _agents, _roster):
        TeamMembership.objects.create(
            team=self.team, employee_profile=self.profile, role='member',
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['authoritative_empty'])
        self.assertEqual(response.data['members'], [])




class SuperuserSystemHealthViewTests(SimpleTestCase):
    """Regression tests for the superuser system-health topology."""

    def test_default_targets_use_local_health_urls_and_no_stale_compose_ports(self):
        targets = SuperuserSystemHealthView.DEFAULT_SERVICE_TARGETS
        urls = ' '.join(str(t.get('default_url')) for t in targets)

        self.assertNotIn('shizuha-hr:8022', urls)
        self.assertNotIn('shizuha-time:8023', urls)
        self.assertNotIn('shizuha-scs:8024', urls)
        self.assertNotIn('shizuha-scs.shizuha.svc.cluster.local:8011', urls)
        self.assertNotIn('http://shizuha-agent:8017/api/', urls)
        self.assertIn('localhost:8001/api/health/', urls)
        self.assertNotIn('svc.cluster.local', urls)

    def test_optional_target_without_url_is_not_deployed(self):
        result = SuperuserSystemHealthView()._check_service(
            MagicMock(),
            {'name': 'shizuha-time', 'default_url': None, 'optional': True},
        )

        self.assertEqual(result['status'], 'not_deployed')
        self.assertEqual(result['name'], 'shizuha-time')

    def test_summary_excludes_not_deployed_from_unhealthy_and_uses_current_redis(self):
        old_redis_host = os.environ.pop('REDIS_HOST', None)
        try:
            summary = SuperuserSystemHealthView._service_summary([
                {'name': 'alive', 'status': 'healthy'},
                {'name': 'shizuha-time', 'status': 'not_deployed'},
            ])
            redis_host = SuperuserSystemHealthView._redis_host()
        finally:
            if old_redis_host is not None:
                os.environ['REDIS_HOST'] = old_redis_host

        self.assertEqual(summary['healthy'], 1)
        self.assertEqual(summary['not_deployed'], 1)
        self.assertEqual(summary['unhealthy'], 0)
        self.assertEqual(redis_host, 'localhost')

    def test_health_payload_reports_healthy_with_expected_not_deployed_services(self):
        payload = SuperuserSystemHealthView._health_payload(
            [
                {'name': 'shizuha-id', 'status': 'healthy', 'optional': False},
                {'name': 'shizuha-time', 'status': 'not_deployed', 'optional': True},
            ],
            [{'name': 'PostgreSQL', 'status': 'healthy'}],
        )

        self.assertEqual(payload['status'], 'healthy')
        self.assertIn('timestamp', payload)
        self.assertEqual(payload['summary']['unhealthy'], 0)
        self.assertEqual(payload['summary']['not_deployed'], 1)

    def test_health_payload_degrades_for_optional_failures(self):
        payload = SuperuserSystemHealthView._health_payload(
            [
                {'name': 'shizuha-id', 'status': 'healthy', 'optional': False},
                {'name': 'optional-app', 'status': 'timeout', 'optional': True},
            ],
            [{'name': 'PostgreSQL', 'status': 'healthy'}],
        )

        self.assertEqual(payload['status'], 'degraded')

    def test_health_payload_reports_unhealthy_for_required_or_infra_failures(self):
        required_failure = SuperuserSystemHealthView._health_payload(
            [{'name': 'shizuha-id', 'status': 'unreachable', 'optional': False}],
            [{'name': 'PostgreSQL', 'status': 'healthy'}],
        )
        infra_failure = SuperuserSystemHealthView._health_payload(
            [{'name': 'shizuha-id', 'status': 'healthy', 'optional': False}],
            [{'name': 'PostgreSQL', 'status': 'unhealthy'}],
        )

        self.assertEqual(required_failure['status'], 'unhealthy')
        self.assertEqual(infra_failure['status'], 'unhealthy')


class OrganizationMemberViewTests(TestCase):
    """Tests for viewing organization members."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        # Create organizations
        self.org1 = Organization.objects.create(
            name="Acme Corp",
            slug="acme-corp",
            owner_id=1
        )
        self.org2 = Organization.objects.create(
            name="Test Inc",
            slug="test-inc",
            owner_id=2
        )

        # Create memberships for org1
        self.membership_owner = OrganizationMembership.objects.create(
            organization=self.org1,
            user_id=1,
            user_email="owner@acme.com",
            role='owner',
            is_pending=False
        )
        self.membership_admin = OrganizationMembership.objects.create(
            organization=self.org1,
            user_id=2,
            user_email="admin@acme.com",
            role='admin',
            is_pending=False
        )
        self.membership_member = OrganizationMembership.objects.create(
            organization=self.org1,
            user_id=3,
            user_email="member@acme.com",
            role='member',
            is_pending=False
        )

        # Create membership for org2
        self.membership_org2_owner = OrganizationMembership.objects.create(
            organization=self.org2,
            user_id=4,
            user_email="owner@test.com",
            role='owner',
            is_pending=False
        )

    def _mock_authenticate(self, user):
        """Mock JWT authentication."""
        self.client.force_authenticate(user=user)

    @patch('organizations.views.permissions.IsAuthenticated.has_permission')
    def test_member_can_view_organization_members(self, mock_perm):
        """Test that organization members can view all members in their org."""
        mock_perm.return_value = True

        # Create mock user who is a member
        user = MockUser(id=3, email="member@acme.com", is_staff=False)
        self._mock_authenticate(user)

        response = self.client.get(f'/api/organizations/{self.org1.slug}/members/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['count'], 3)

        # Verify all members are returned
        emails = [m['user_email'] for m in data['members']]
        self.assertIn('owner@acme.com', emails)
        self.assertIn('admin@acme.com', emails)
        self.assertIn('member@acme.com', emails)

    @patch('organizations.views.permissions.IsAuthenticated.has_permission')
    def test_member_cannot_view_other_organization_members(self, mock_perm):
        """Test that members cannot view members of organizations they don't belong to."""
        mock_perm.return_value = True

        # Create mock user who is only member of org1
        user = MockUser(id=3, email="member@acme.com", is_staff=False)
        self._mock_authenticate(user)

        # Try to view org2 members
        response = self.client.get(f'/api/organizations/{self.org2.slug}/members/')

        # Should get 404 (org not found because user not a member)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch('organizations.views.permissions.IsAuthenticated.has_permission')
    def test_owner_can_view_organization_members(self, mock_perm):
        """Test that organization owners can view all members."""
        mock_perm.return_value = True

        user = MockUser(id=1, email="owner@acme.com", is_staff=False)
        self._mock_authenticate(user)

        response = self.client.get(f'/api/organizations/{self.org1.slug}/members/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['count'], 3)

    @patch('organizations.views.permissions.IsAuthenticated.has_permission')
    def test_admin_can_view_organization_members(self, mock_perm):
        """Test that organization admins can view all members."""
        mock_perm.return_value = True

        user = MockUser(id=2, email="admin@acme.com", is_staff=False)
        self._mock_authenticate(user)

        response = self.client.get(f'/api/organizations/{self.org1.slug}/members/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['count'], 3)


class StaffOrganizationViewTests(TestCase):
    """Tests for staff/administrator viewing all organizations."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        # Create multiple organizations
        self.org1 = Organization.objects.create(
            name="Acme Corp",
            slug="acme-corp",
            owner_id=1
        )
        self.org2 = Organization.objects.create(
            name="Test Inc",
            slug="test-inc",
            owner_id=2
        )
        self.org3 = Organization.objects.create(
            name="Demo LLC",
            slug="demo-llc",
            owner_id=3
        )

        # Create memberships
        for org, owner_id, email in [
            (self.org1, 1, "owner@acme.com"),
            (self.org2, 2, "owner@test.com"),
            (self.org3, 3, "owner@demo.com"),
        ]:
            OrganizationMembership.objects.create(
                organization=org,
                user_id=owner_id,
                user_email=email,
                role='owner',
                is_pending=False
            )

        # Add extra members to org1
        OrganizationMembership.objects.create(
            organization=self.org1,
            user_id=10,
            user_email="member1@acme.com",
            role='member',
            is_pending=False
        )
        OrganizationMembership.objects.create(
            organization=self.org1,
            user_id=11,
            user_email="member2@acme.com",
            role='member',
            is_pending=False
        )

    def _mock_authenticate(self, user):
        """Mock JWT authentication."""
        self.client.force_authenticate(user=user)

    @patch('organizations.views.permissions.IsAuthenticated.has_permission')
    def test_staff_only_sees_own_organizations(self, mock_perm):
        """Test that staff users only see organizations they belong to (not all)."""
        mock_perm.return_value = True

        # Staff user (not member of any org)
        user = MockUser(id=999, email="staff@shizuha.com", is_staff=True)
        self._mock_authenticate(user)

        response = self.client.get('/api/organizations/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        # Staff should only see their auto-created personal workspace
        if isinstance(data, dict) and 'results' in data:
            orgs = data['results']
        else:
            orgs = data

        self.assertEqual(len(orgs), 1)
        self.assertEqual(orgs[0]['slug'], 'personal-999')

    @patch('organizations.views.permissions.IsAuthenticated.has_permission')
    def test_staff_cannot_view_non_member_organization_members(self, mock_perm):
        """Test that staff users cannot view members of orgs they don't belong to."""
        mock_perm.return_value = True

        user = MockUser(id=999, email="staff@shizuha.com", is_staff=True)
        self._mock_authenticate(user)

        # Staff is not a member of org1, should get 404
        response = self.client.get(f'/api/organizations/{self.org1.slug}/members/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch('organizations.views.permissions.IsAuthenticated.has_permission')
    def test_regular_user_only_sees_own_organizations(self, mock_perm):
        """Test that regular users only see organizations they belong to."""
        mock_perm.return_value = True

        # Regular user who is only member of org1
        user = MockUser(id=10, email="member1@acme.com", is_staff=False)
        self._mock_authenticate(user)

        response = self.client.get('/api/organizations/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        if isinstance(data, dict) and 'results' in data:
            orgs = data['results']
        else:
            orgs = data

        # Should see org1 + auto-created personal workspace
        self.assertEqual(len(orgs), 2)
        slugs = [org['slug'] for org in orgs]
        self.assertIn('acme-corp', slugs)
        self.assertIn('personal-10', slugs)


class MemberInviteTests(TestCase):
    """Tests for inviting members to organizations."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        self.org = Organization.objects.create(
            name="Acme Corp",
            slug="acme-corp",
            owner_id=1
        )

        self.owner_membership = OrganizationMembership.objects.create(
            organization=self.org,
            user_id=1,
            user_email="owner@acme.com",
            role='owner',
            is_pending=False
        )

        self.admin_membership = OrganizationMembership.objects.create(
            organization=self.org,
            user_id=2,
            user_email="admin@acme.com",
            role='admin',
            is_pending=False
        )

        self.member_membership = OrganizationMembership.objects.create(
            organization=self.org,
            user_id=3,
            user_email="member@acme.com",
            role='member',
            is_pending=False
        )

    def _mock_authenticate(self, user):
        """Mock JWT authentication."""
        self.client.force_authenticate(user=user)

    @patch('organizations.views.permissions.IsAuthenticated.has_permission')
    def test_owner_can_invite_members(self, mock_perm):
        """Test that owners can invite new members."""
        mock_perm.return_value = True

        user = MockUser(id=1, email="owner@acme.com", is_staff=False)
        self._mock_authenticate(user)

        response = self.client.post(
            f'/api/organizations/{self.org.slug}/members/',
            {'user_email': 'newmember@acme.com', 'role': 'member'},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify member was added
        self.assertTrue(
            OrganizationMembership.objects.filter(
                organization=self.org,
                user_email='newmember@acme.com',
                is_pending=True
            ).exists()
        )

    @patch('organizations.views.permissions.IsAuthenticated.has_permission')
    def test_admin_can_invite_members(self, mock_perm):
        """Test that admins can invite new members."""
        mock_perm.return_value = True

        user = MockUser(id=2, email="admin@acme.com", is_staff=False)
        self._mock_authenticate(user)

        response = self.client.post(
            f'/api/organizations/{self.org.slug}/members/',
            {'user_email': 'newadmin@acme.com', 'role': 'member'},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch('organizations.views.permissions.IsAuthenticated.has_permission')
    def test_regular_member_cannot_invite_members(self, mock_perm):
        """Test that regular members cannot invite new members."""
        mock_perm.return_value = True

        user = MockUser(id=3, email="member@acme.com", is_staff=False)
        self._mock_authenticate(user)

        response = self.client.post(
            f'/api/organizations/{self.org.slug}/members/',
            {'user_email': 'unauthorized@acme.com', 'role': 'member'},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch('organizations.views.permissions.IsAuthenticated.has_permission')
    def test_cannot_invite_existing_member(self, mock_perm):
        """Test that inviting an existing member fails."""
        mock_perm.return_value = True

        user = MockUser(id=1, email="owner@acme.com", is_staff=False)
        self._mock_authenticate(user)

        response = self.client.post(
            f'/api/organizations/{self.org.slug}/members/',
            {'user_email': 'member@acme.com', 'role': 'admin'},  # Already a member
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class OrganizationCreateTests(TestCase):
    """Tests for creating organizations."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

    def _mock_authenticate(self, user):
        """Mock JWT authentication."""
        self.client.force_authenticate(user=user)

    @patch('organizations.views.permissions.IsAuthenticated.has_permission')
    def test_authenticated_user_can_create_organization(self, mock_perm):
        """Test that any authenticated user can create an organization."""
        mock_perm.return_value = True

        user = MockUser(id=100, email="creator@example.com", is_staff=False)
        self._mock_authenticate(user)

        response = self.client.post(
            '/api/organizations/',
            {'name': 'New Organization', 'slug': 'new-org'},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify organization was created
        org = Organization.objects.get(slug='new-org')
        self.assertEqual(org.name, 'New Organization')
        self.assertEqual(org.owner_id, 100)

        # Verify creator is owner member
        membership = OrganizationMembership.objects.get(
            organization=org,
            user_id=100
        )
        self.assertEqual(membership.role, 'owner')
        self.assertFalse(membership.is_pending)


# =============================================================================
# PLAT-18 regression tests: EmployeeProfile serializers must resolve
# manager_email -> manager_id at write time (PLAT-5 backport, mirrors PLAT-14).
# =============================================================================

from .models import EmployeeProfile
from .serializers import (
    _resolve_user_id_by_email,
    EmployeeProfileCreateSerializer,
    EmployeeProfileUpdateSerializer,
)


class OrganizationHRNumericLookupTests(TestCase):
    """HR nested endpoints accept the numeric org ids returned by /organizations/."""

    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(
            name="Visible Org",
            slug="visible-org",
            owner_id=501,
        )
        self.membership = OrganizationMembership.objects.create(
            organization=self.org,
            user_id=501,
            user_email="member@visible.test",
            role='member',
            is_pending=False,
        )
        self.profile = EmployeeProfile.objects.get(membership=self.membership)
        self.profile.job_title = "Engineer"
        self.profile.employment_status = 'active'
        self.profile.employment_type = 'full_time'
        self.profile.save()

    def _auth(self):
        self.client.force_authenticate(user=MockUser(
            id=501,
            email="member@visible.test",
            is_staff=False,
        ))

    @patch('organizations.views.permissions.IsAuthenticated.has_permission')
    def test_visible_numeric_org_id_returns_org_chart_stats(self, mock_perm):
        mock_perm.return_value = True
        self._auth()

        response = self.client.get(f'/api/organizations/{self.org.id}/org-chart/stats/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['organization'], self.org.slug)
        self.assertEqual(data['total_employees'], 1)

    @patch('organizations.views.permissions.IsAuthenticated.has_permission')
    def test_visible_numeric_org_id_employees_matches_member_profile_count(self, mock_perm):
        mock_perm.return_value = True
        self._auth()

        response = self.client.get(f'/api/organizations/{self.org.id}/employees/?page_size=200')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['user_email'], 'member@visible.test')


class ResolveUserIdByEmailTests(TestCase):
    def test_empty_email_returns_none(self):
        self.assertIsNone(_resolve_user_id_by_email(""))
        self.assertIsNone(_resolve_user_id_by_email(None))

    def test_network_exception_returns_none(self):
        # A shizuha-id outage / timeout must not block the write.
        with patch("requests.get",
                   side_effect=Exception("boom")):
            self.assertIsNone(_resolve_user_id_by_email("x@y.com"))

    def test_resolves_user_id_on_200(self):
        class _Resp:
            status_code = 200
            def json(self):
                return {"id": 42, "email": "mgr@example.com"}
        with patch("requests.get",
                   return_value=_Resp()):
            self.assertEqual(_resolve_user_id_by_email("mgr@example.com"), 42)

    def test_non_200_returns_none(self):
        class _Resp:
            status_code = 404
            def json(self):
                return {}
        with patch("requests.get",
                   return_value=_Resp()):
            self.assertIsNone(_resolve_user_id_by_email("missing@example.com"))

    def test_bad_json_returns_none(self):
        class _Resp:
            status_code = 200
            def json(self):
                raise ValueError("not json")
        with patch("requests.get",
                   return_value=_Resp()):
            self.assertIsNone(_resolve_user_id_by_email("mgr@example.com"))

    def test_string_id_is_coerced_to_int(self):
        class _Resp:
            status_code = 200
            def json(self):
                return {"id": "99"}
        with patch("requests.get",
                   return_value=_Resp()):
            self.assertEqual(_resolve_user_id_by_email("s@example.com"), 99)

    def test_non_coercible_id_returns_none(self):
        class _Resp:
            status_code = 200
            def json(self):
                return {"id": "not-a-number"}
        with patch("requests.get",
                   return_value=_Resp()):
            self.assertIsNone(_resolve_user_id_by_email("s@example.com"))


class EmployeeProfileCreateSerializerResolveTests(TestCase):
    """
    PLAT-18 regression: a create request with only manager_email must land
    on the EmployeeProfile with manager_id populated (when resolvable).
    """

    def setUp(self):
        self.org = Organization.objects.create(
            name="Hierarchy Corp", slug="hier-corp", owner_id=1,
        )
        self.membership = OrganizationMembership.objects.create(
            organization=self.org, user_id=500, user_email="new-ee@example.com",
            role='member', is_pending=False,
        )
        # Signals auto-create an EmployeeProfile for new memberships; drop it
        # so we're exercising the explicit create-serializer path in isolation.
        EmployeeProfile.objects.filter(membership=self.membership).delete()

    def _data(self, **overrides):
        base = {"membership_id": self.membership.id}
        base.update(overrides)
        return base

    def test_email_resolves_populates_manager_id(self):
        with patch("organizations.serializers._resolve_user_id_by_email",
                   return_value=77):
            ser = EmployeeProfileCreateSerializer(
                data=self._data(manager_email="mgr@example.com"),
                context={"organization": self.org},
            )
            self.assertTrue(ser.is_valid(), ser.errors)
            self.assertEqual(ser.validated_data.get('manager_id'), 77)

    def test_email_unresolvable_leaves_manager_id_none(self):
        with patch("organizations.serializers._resolve_user_id_by_email",
                   return_value=None):
            ser = EmployeeProfileCreateSerializer(
                data=self._data(manager_email="ghost@example.com"),
                context={"organization": self.org},
            )
            self.assertTrue(ser.is_valid(), ser.errors)
            self.assertIsNone(ser.validated_data.get('manager_id'))

    def test_explicit_manager_id_is_not_overridden(self):
        # Caller supplied manager_id directly — do NOT call the resolver and
        # do NOT clobber it even if manager_email is also supplied.
        with patch("organizations.serializers._resolve_user_id_by_email") as m:
            ser = EmployeeProfileCreateSerializer(
                data=self._data(manager_id=123, manager_email="other@example.com"),
                context={"organization": self.org},
            )
            self.assertTrue(ser.is_valid(), ser.errors)
            self.assertEqual(ser.validated_data.get('manager_id'), 123)
            m.assert_not_called()

    def test_dotted_line_manager_email_also_resolves(self):
        def _resolver(email):
            return {"mgr@example.com": 77, "dotted@example.com": 88}.get(email)
        with patch("organizations.serializers._resolve_user_id_by_email",
                   side_effect=_resolver):
            ser = EmployeeProfileCreateSerializer(
                data=self._data(
                    manager_email="mgr@example.com",
                    dotted_line_manager_email="dotted@example.com",
                ),
                context={"organization": self.org},
            )
            self.assertTrue(ser.is_valid(), ser.errors)
            self.assertEqual(ser.validated_data.get('manager_id'), 77)
            self.assertEqual(ser.validated_data.get('dotted_line_manager_id'), 88)

    def test_no_email_no_id_is_fine(self):
        # Founders / top-of-hierarchy have no manager.
        with patch("organizations.serializers._resolve_user_id_by_email") as m:
            ser = EmployeeProfileCreateSerializer(
                data=self._data(),
                context={"organization": self.org},
            )
            self.assertTrue(ser.is_valid(), ser.errors)
            self.assertIsNone(ser.validated_data.get('manager_id'))
            m.assert_not_called()


class EmployeeProfileUpdateSerializerResolveTests(TestCase):
    """PLAT-18 regression on the update path."""

    def setUp(self):
        self.org = Organization.objects.create(
            name="Update Corp", slug="upd-corp", owner_id=1,
        )
        self.membership = OrganizationMembership.objects.create(
            organization=self.org, user_id=600, user_email="ee@example.com",
            role='member', is_pending=False,
        )
        # Signals auto-create the profile on membership save — reuse it.
        self.profile = EmployeeProfile.objects.get(membership=self.membership)

    def test_update_with_email_resolves_manager_id(self):
        with patch("organizations.serializers._resolve_user_id_by_email",
                   return_value=321):
            ser = EmployeeProfileUpdateSerializer(
                instance=self.profile,
                data={"manager_email": "mgr@example.com"},
                partial=True,
            )
            self.assertTrue(ser.is_valid(), ser.errors)
            self.assertEqual(ser.validated_data.get('manager_id'), 321)

    def test_update_with_email_unresolvable_leaves_manager_id_unset(self):
        # When resolution fails we simply do not inject manager_id into
        # validated_data; the stored value on the instance is preserved.
        with patch("organizations.serializers._resolve_user_id_by_email",
                   return_value=None):
            ser = EmployeeProfileUpdateSerializer(
                instance=self.profile,
                data={"manager_email": "ghost@example.com"},
                partial=True,
            )
            self.assertTrue(ser.is_valid(), ser.errors)
            self.assertIsNone(ser.validated_data.get('manager_id'))

    def test_update_explicit_manager_id_wins(self):
        with patch("organizations.serializers._resolve_user_id_by_email") as m:
            ser = EmployeeProfileUpdateSerializer(
                instance=self.profile,
                data={"manager_id": 555, "manager_email": "other@example.com"},
                partial=True,
            )
            self.assertTrue(ser.is_valid(), ser.errors)
            self.assertEqual(ser.validated_data.get('manager_id'), 555)
            m.assert_not_called()


# =============================================================================
# PLAT-18 regression tests: Department.head_email and Team.lead_email must
# resolve to *_id at write time (scope #2 per the ticket, raised in PR #2
# review by ryo@). Mirrors the EmployeeProfile shape above.
# =============================================================================

from .models import TeamType  # noqa: E402
from .serializers import (  # noqa: E402
    DepartmentCreateSerializer,
    TeamCreateSerializer,
)


class DepartmentCreateSerializerResolveTests(TestCase):
    """PLAT-18: head_email must resolve to head_id at Department create time."""

    def setUp(self):
        self.org = Organization.objects.create(
            name="Dept Corp", slug="dept-corp", owner_id=1,
        )

    def _data(self, **overrides):
        base = {"name": "Engineering"}
        base.update(overrides)
        return base

    def test_head_email_resolves_populates_head_id(self):
        with patch("organizations.serializers._resolve_user_id_by_email",
                   return_value=101):
            ser = DepartmentCreateSerializer(
                data=self._data(head_email="head@example.com"),
                context={"organization": self.org},
            )
            self.assertTrue(ser.is_valid(), ser.errors)
            self.assertEqual(ser.validated_data.get('head_id'), 101)
            self.assertEqual(ser.validated_data.get('head_email'), "head@example.com")

    def test_head_email_unresolvable_leaves_head_id_none(self):
        with patch("organizations.serializers._resolve_user_id_by_email",
                   return_value=None):
            ser = DepartmentCreateSerializer(
                data=self._data(head_email="ghost@example.com"),
                context={"organization": self.org},
            )
            self.assertTrue(ser.is_valid(), ser.errors)
            self.assertIsNone(ser.validated_data.get('head_id'))
            self.assertEqual(ser.validated_data.get('head_email'), "ghost@example.com")

    def test_explicit_head_id_is_not_overridden(self):
        with patch("organizations.serializers._resolve_user_id_by_email") as m:
            ser = DepartmentCreateSerializer(
                data=self._data(head_id=202, head_email="other@example.com"),
                context={"organization": self.org},
            )
            self.assertTrue(ser.is_valid(), ser.errors)
            self.assertEqual(ser.validated_data.get('head_id'), 202)
            m.assert_not_called()


class TeamCreateSerializerResolveTests(TestCase):
    """PLAT-18: lead_email must resolve to lead_id at Team create time."""

    def setUp(self):
        self.org = Organization.objects.create(
            name="Team Corp", slug="team-corp", owner_id=1,
        )

    def _data(self, **overrides):
        base = {"name": "Platform", "team_type": TeamType.PERMANENT}
        base.update(overrides)
        return base

    def test_lead_email_resolves_populates_lead_id(self):
        with patch("organizations.serializers._resolve_user_id_by_email",
                   return_value=303):
            ser = TeamCreateSerializer(
                data=self._data(lead_email="lead@example.com"),
                context={"organization": self.org},
            )
            self.assertTrue(ser.is_valid(), ser.errors)
            self.assertEqual(ser.validated_data.get('lead_id'), 303)
            self.assertEqual(ser.validated_data.get('lead_email'), "lead@example.com")

    def test_lead_email_unresolvable_leaves_lead_id_none(self):
        with patch("organizations.serializers._resolve_user_id_by_email",
                   return_value=None):
            ser = TeamCreateSerializer(
                data=self._data(lead_email="ghost@example.com"),
                context={"organization": self.org},
            )
            self.assertTrue(ser.is_valid(), ser.errors)
            self.assertIsNone(ser.validated_data.get('lead_id'))
            self.assertEqual(ser.validated_data.get('lead_email'), "ghost@example.com")

    def test_explicit_lead_id_is_not_overridden(self):
        with patch("organizations.serializers._resolve_user_id_by_email") as m:
            ser = TeamCreateSerializer(
                data=self._data(lead_id=404, lead_email="other@example.com"),
                context={"organization": self.org},
            )
            self.assertTrue(ser.is_valid(), ser.errors)
            self.assertEqual(ser.validated_data.get('lead_id'), 404)
            m.assert_not_called()


class OrgChartNullIdRegressionTests(TestCase):
    """Regression coverage for PLAT-831 org-chart null employee IDs."""

    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(
            name="Acme Corp",
            slug="acme-corp",
            owner_id=1,
        )
        self.owner_membership = OrganizationMembership.objects.create(
            organization=self.org,
            user_id=1,
            user_email="owner@acme.com",
            display_name="owner",
            role="owner",
            is_pending=False,
        )
        self.owner_profile, _ = EmployeeProfile.objects.get_or_create(
            membership=self.owner_membership,
            defaults={
                'job_title': "Owner",
                'manager_id': None,
            },
        )
        self.member_membership = OrganizationMembership.objects.create(
            organization=self.org,
            user_id=2,
            user_email="member@acme.com",
            display_name="member",
            role="member",
            is_pending=False,
        )
        self.member_profile, _ = EmployeeProfile.objects.get_or_create(
            membership=self.member_membership,
            defaults={
                'job_title': "Member",
                'manager_id': 1,
            },
        )
        # Mirrors the production regression: a non-pending, active membership/profile
        # without a Shizuha ID must not be emitted as an employee identity node.
        self.null_id_membership = OrganizationMembership.objects.create(
            organization=self.org,
            user_id=None,
            user_email="pending-account@acme.com",
            display_name="pending-account",
            role="member",
            is_pending=False,
        )
        self.null_root_profile = EmployeeProfile.objects.create(
            membership=self.null_id_membership,
            job_title="Pending Account",
            manager_id=None,
        )
        self.null_direct_membership = OrganizationMembership.objects.create(
            organization=self.org,
            user_id=None,
            user_email="pending-report@acme.com",
            display_name="pending-report",
            role="member",
            is_pending=False,
        )
        self.null_direct_profile = EmployeeProfile.objects.create(
            membership=self.null_direct_membership,
            job_title="Pending Report",
            manager_id=1,
        )

    def _mock_authenticate(self, user):
        self.client.force_authenticate(user=user)

    @patch('organizations.views.permissions.IsAuthenticated.has_permission')
    def test_org_chart_omits_employee_profiles_without_user_id(self, mock_perm):
        mock_perm.return_value = True
        self._mock_authenticate(MockUser(id=1, email="owner@acme.com", is_staff=True))

        response = self.client.get(f'/api/organizations/{self.org.slug}/org-chart/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        seen = []

        def walk(node):
            seen.append((node.get('id'), node.get('email')))
            for child in node.get('direct_reports', []) or []:
                walk(child)

        for root in data.get('root_employees', []):
            walk(root)

        self.assertNotIn((None, 'pending-account@acme.com'), seen)
        self.assertNotIn((None, 'pending-report@acme.com'), seen)
        self.assertFalse([email for user_id, email in seen if user_id is None], seen)
        self.assertIn((1, 'owner@acme.com'), seen)
        self.assertIn((2, 'member@acme.com'), seen)
        self.assertEqual(data['total_employees'], 2)

    @patch('organizations.views.permissions.IsAuthenticated.has_permission')
    def test_org_chart_total_departments_counts_children_not_just_roots(self, mock_perm):
        """PLAT-3192: one root with children must not report Departments: 1."""
        from .models import Department

        root = Department.objects.create(
            organization=self.org, name='Corporate', is_active=True,
        )
        Department.objects.create(
            organization=self.org, name='Technology', parent=root, is_active=True,
        )
        Department.objects.create(
            organization=self.org, name='Operations', parent=root, is_active=True,
        )
        # Inactive departments stay excluded (same contract as org-chart/stats).
        Department.objects.create(
            organization=self.org, name='Dissolved', parent=root, is_active=False,
        )

        # Fixture bootstrap may add its own root (e.g. the auto-created EXEC
        # department), so derive expectations from the ORM instead of literals.
        active = Department.objects.filter(organization=self.org, is_active=True)
        expected_total = active.count()
        expected_roots = active.filter(parent__isnull=True).count()

        mock_perm.return_value = True
        self._mock_authenticate(MockUser(id=1, email="owner@acme.com", is_staff=True))

        response = self.client.get(f'/api/organizations/{self.org.slug}/org-chart/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        # The tree payload carries only roots...
        self.assertEqual(len(data['departments']), expected_roots)
        # ...but the flat total the header binds to counts every active department —
        # the two must genuinely differ here or this test can't catch the regression.
        self.assertGreater(expected_total, expected_roots)
        self.assertEqual(data['total_departments'], expected_total)

        stats = self.client.get(f'/api/organizations/{self.org.slug}/org-chart/stats/')
        self.assertEqual(stats.status_code, status.HTTP_200_OK)
        self.assertEqual(stats.json()['total_departments'], data['total_departments'])


class SuperuserDashboardBoundaryEventTests(SimpleTestCase):
    @staticmethod
    def _denied_response():
        request = APIRequestFactory().get('/api/su/dashboard/')
        user = MockUser(41, 'runner@example.com', is_staff=False)
        user.username = 'runner'
        user.organization_memberships = {1: 'member'}
        force_authenticate(request, user=user)
        return SuperuserDashboardView.as_view()(request)

    @patch('organizations.views.emit_boundary_denial')
    def test_nonstaff_denial_emits_before_preserving_403(self, emit):
        response = self._denied_response()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        emit.assert_called_once()
        self.assertEqual(emit.call_args.kwargs['service'], 'admin')
        self.assertEqual(emit.call_args.kwargs['operation'], 'admin.su_dashboard')
        self.assertEqual(emit.call_args.kwargs['reason'], 'superuser_endpoint')

    @override_settings(CONNECT_SECURITY_EVENT_ORIGIN_SECRET='boundary-secret')
    @patch('organizations.security_events.record_boundary_event_outcome')
    @patch('organizations.security_events.requests.post')
    def test_boundary_producer_success_is_counted_without_changing_403(self, post, record):
        post.return_value.status_code = status.HTTP_202_ACCEPTED

        response = self._denied_response()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        record.assert_called_once_with('success')
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['data']['operation'], 'admin.su_dashboard')
        self.assertNotIn('query', payload['data'])

    def test_boundary_producer_failures_are_counted_without_changing_403(self):
        cases = (
            ('disabled', {'CONNECT_SECURITY_EVENT_EMIT_ENABLED': False}, None, None),
            ('missing_secret', {'CONNECT_SECURITY_EVENT_ORIGIN_SECRET': ''}, None, None),
            ('non_202', {'CONNECT_SECURITY_EVENT_ORIGIN_SECRET': 'boundary-secret'}, 503, None),
            ('timeout', {'CONNECT_SECURITY_EVENT_ORIGIN_SECRET': 'boundary-secret'}, None, requests.Timeout()),
            ('exception', {'CONNECT_SECURITY_EVENT_ORIGIN_SECRET': 'boundary-secret'}, None, RuntimeError('boom')),
        )
        for expected, setting_overrides, status_code, side_effect in cases:
            with self.subTest(expected=expected), override_settings(**setting_overrides), patch(
                'organizations.security_events.record_boundary_event_outcome',
            ) as record, patch('organizations.security_events.requests.post') as post:
                if status_code is not None:
                    post.return_value.status_code = status_code
                if side_effect is not None:
                    post.side_effect = side_effect

                response = self._denied_response()

                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                record.assert_called_once_with(expected)

    @patch('organizations.security_events._metrics_redis_client')
    def test_boundary_metrics_endpoint_exposes_bounded_service_outcomes(self, client_factory):
        client = MagicMock()
        client.mget.return_value = ['3'] + ['0'] * 7
        client_factory.return_value = client

        response = self.client.get('/api/metrics/security-events/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        text = response.content.decode('utf-8')
        self.assertIn(
            'platform_boundary_event_producer_total{service="admin",outcome="success"} 3',
            text,
        )
        self.assertIn(
            'platform_boundary_event_producer_probe_errors{service="admin"} 0',
            text,
        )


class PLS770TeamRosterSummaryProjectionTests(TestCase):
    """PLS-770: list summary counts + MCP flattening agree with the detail
    projection (routing authority + directory lead dedup)."""

    def setUp(self):
        self.org = Organization.objects.create(
            name='PLS770 Org', slug='shizuha', owner_id=1,
        )

    def _mk_membership(self, email, role='member'):
        membership = OrganizationMembership.objects.create(
            organization=self.org,
            user_id=hash(email) % 100000,
            user_email=email,
            display_name=email.split('@')[0],
            role=role,
            is_pending=False,
            is_active=True,
        )
        profile, _ = EmployeeProfile.objects.get_or_create(
            membership=membership,
            defaults={'job_title': 'Member'},
        )
        return membership, profile

    def _mk_team(self, name, pulse_project_id=None):
        return Team.objects.create(
            organization=self.org, name=name,
            pulse_project_id=pulse_project_id,
        )

    def _roster(self, mapping):
        """mapping: {team_name: [emails]} -> roster-all dict keyed like the helper."""
        out = {}
        from organizations.services.team_roster_authority import _canonical_team
        for name, emails in mapping.items():
            out[(self.org.id, self.org.slug, _canonical_team(name))] = set(emails)
        return out

    @patch('organizations.views.fetch_fleet_agent_emails', return_value=set())
    def test_qa_summary_uses_projected_routing_extras(self, _agents):
        # QA detail: count=5 routing_count=5 directory_count=0; legacy summary
        # reported 4. Summary must now read 5 from the authoritative projection.
        team = self._mk_team('QA')
        for i, email in enumerate(['qa1@shizuha.com', 'qa2@shizuha.com',
                                   'qa3@shizuha.com', 'qa4@shizuha.com']):
            membership, _ = self._mk_membership(email)
            TeamMembership.objects.create(team=team, employee_profile=membership.employee_profile, role='member')
        roster = self._roster({'qa': [f'qa{i}@shizuha.com' for i in range(5)]})

        client = APIClient()
        client.force_authenticate(MockUser(id=1, email='staff@shizuha.com', is_superuser=True))
        with patch('organizations.services.team_roster_authority.fetch_authoritative_roster_all', return_value=roster):
            response = client.get(
                f'/api/organizations/shizuha/teams/{team.pk}/'
            )
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data['member_count'], 5)

    @patch('organizations.views.fetch_fleet_agent_emails', return_value=set())
    def test_ceo_decisions_directory_lead_does_not_inflate_summary(self, _agents):
        # CEO Decisions: one routing identity (hothritik1) + a directory lead
        # edge for the SAME email. Summary must dedupe to the routing count (1),
        # never present the person twice.
        team = self._mk_team('CEO Decisions')
        membership, profile = self._mk_membership('test-owner@example.com', role='lead')
        TeamMembership.objects.create(team=team, employee_profile=profile, role='lead')
        roster = self._roster({'ceo-decisions': ['test-owner@example.com']})

        client = APIClient()
        client.force_authenticate(MockUser(id=1, email='staff@shizuha.com', is_superuser=True))
        with patch('organizations.services.team_roster_authority.fetch_authoritative_roster_all', return_value=roster):
            response = client.get(f'/api/organizations/shizuha/teams/{team.pk}/')
            self.assertEqual(response.status_code, 200, response.data)
            # Routing projection is authoritative: only the one identity.
            self.assertEqual(response.data['member_count'], 1)

    @patch('organizations.views.fetch_fleet_agent_emails', return_value=set())
    def test_marketing_authoritative_empty_is_zero(self, _agents):
        # Marketing: authoritative empty projection -> summary count 0 even if a
        # legacy directory edge exists locally.
        team = self._mk_team('Marketing')
        membership, profile = self._mk_membership('mk@shizuha.com')
        TeamMembership.objects.create(team=team, employee_profile=profile, role='member')
        roster = self._roster({'marketing': []})

        client = APIClient()
        client.force_authenticate(MockUser(id=1, email='staff@shizuha.com', is_superuser=True))
        with patch('organizations.services.team_roster_authority.fetch_authoritative_roster_all', return_value=roster):
            response = client.get(f'/api/organizations/shizuha/teams/{team.pk}/')
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data['member_count'], 0)


