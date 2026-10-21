from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APIRequestFactory
from unittest.mock import Mock, patch

from .internal_urls import InternalUserMembershipsView
from .models import (
    EmployeeProfile,
    JITElevatedAccessGrant,
    JITElevatedAccessGrantEvent,
    JITElevatedAccessGrantUse,
    Organization,
    OrganizationMembership,
    Team,
    TeamMembership,
)
from .tests import MockUser


class JITElevatedAccessGrantTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(
            name='Acme Corp',
            slug='acme-corp',
            owner_id=1,
        )
        OrganizationMembership.objects.create(
            organization=self.org,
            user_id=1,
            user_email='owner@acme.com',
            role='owner',
            is_pending=False,
        )
        OrganizationMembership.objects.create(
            organization=self.org,
            user_id=3,
            user_email='agent@acme.com',
            role='member',
            is_pending=False,
        )

    def _auth(self, user_id=3, email='agent@acme.com', is_staff=False):
        self.client.force_authenticate(user=MockUser(id=user_id, email=email, is_staff=is_staff))

    @patch('organizations.tasks.dispatch_kubernetes_jit_use_task.delay')
    def test_orig361_invalid_alias_refuses_without_creating_unusable_grant(self, dispatch):
        self._auth()
        payload = {
            'org_slug': self.org.slug,
            'scope': 'kubernetes.ci_deployer_rbac.apply',
            'reason': 'ORIG-361 canonical RBAC apply',
            'task_key': 'ORIG-361',
            'ttl_seconds': 900,
            'commit_sha': 'a' * 40,
        }
        response = self.client.post('/api/jit-elevations/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(response.data['code'], 'jit_scope_alias_unsupported')
        self.assertEqual(response.data['supported_scope'], 'kubernetes.rbac.apply')
        self.assertFalse(JITElevatedAccessGrant.objects.exists())
        self.assertFalse(JITElevatedAccessGrantEvent.objects.exists())
        self.assertFalse(JITElevatedAccessGrantUse.objects.exists())
        dispatch.assert_not_called()

        # The caller corrects the request; admission still requires the exact
        # contract and independent approval rather than accepting the alias.
        platform = Team.objects.create(organization=self.org, name='Platform')
        payload['scope'] = response.data['supported_scope']
        corrected = self.client.post('/api/jit-elevations/', payload, format='json')
        self.assertEqual(corrected.status_code, status.HTTP_201_CREATED, corrected.data)
        grant = JITElevatedAccessGrant.objects.get(pk=corrected.data['grant']['id'])
        self.assertTrue(grant.has_complete_current_exact_authority())
        self.assertEqual(grant.approver_team_id, platform.pk)
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_PENDING)
        self.assertEqual(grant.target_constraints['commit_sha'], 'a' * 40)
        self.assertFalse(JITElevatedAccessGrantUse.objects.exists())
        dispatch.assert_not_called()

    @patch('organizations.tasks.dispatch_kubernetes_jit_use_task.delay')
    def test_orig361_existing_alias_grant_is_not_upgraded_by_approval(self, dispatch):
        self._auth()
        grant = JITElevatedAccessGrant.objects.create(
            organization=self.org, requester_user_id=3,
            requester_email='agent@acme.com',
            scope='kubernetes.ci_deployer_rbac.apply', requested_role='admin',
            reason='Historical invalid alias', task_key='ORIG-361',
            ttl_seconds=900, status=JITElevatedAccessGrant.STATUS_APPROVED,
            expires_at=timezone.now() + timedelta(seconds=900),
        )
        response = self.client.post(
            f'/api/jit-elevations/{grant.pk}/consume-kubernetes/',
            {
                'action': 'apply-origin-ci-deployer-rbac',
                'expected_sha': 'a' * 40,
                'idempotency_key': 'orig361-existing-alias',
            }, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)
        self.assertEqual(response.data['error'], 'Grant scope does not authorize this action')
        grant.refresh_from_db()
        self.assertEqual(grant.scope, 'kubernetes.ci_deployer_rbac.apply')
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_APPROVED)
        self.assertEqual(grant.uses_consumed, 0)
        self.assertFalse(JITElevatedAccessGrantUse.objects.exists())
        dispatch.assert_not_called()

    def test_plat4952_requester_revokes_own_pending_grant_by_email_match(self):
        """PLAT-4952: a federated requester whose local user_id shifted (id Y !=
        the recorded requester_user_id X) but whose email matches can still revoke
        their own pending team-member-add grant. Requester identity is matched by
        user_id OR email (not user_id alone), mirroring the grant-query pattern."""
        grant = JITElevatedAccessGrant.objects.create(
            organization=self.org,
            requester_user_id=140,
            requester_email='nova@shizuha.com',
            scope=JITElevatedAccessGrant.TEAM_MEMBER_ADD_SCOPE,
            requested_role='member',
            reason='PLAT-4952 requester-revoke regression',
            task_key='PLAT-4952',
            ttl_seconds=1800,
            status=JITElevatedAccessGrant.STATUS_PENDING,
        )
        # same requester by email, DIFFERENT local id (Y=999 != recorded X=140)
        self._auth(user_id=999, email='nova@shizuha.com')
        resp = self.client.post(
            f'/api/jit-elevations/{grant.pk}/revoke/',
            {'note': 'withdrawing my mistaken request'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        grant.refresh_from_db()
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_REVOKED)

    def test_plat4952_requester_self_approve_stays_blocked_by_email_match(self):
        """The email-fallback identity must keep SoD fail-CLOSED: a requester
        matched by email (despite a shifted id, even as staff) still cannot
        approve their own grant."""
        grant = JITElevatedAccessGrant.objects.create(
            organization=self.org,
            requester_user_id=140,
            requester_email='nova@shizuha.com',
            scope='org.members.add',
            requested_role='admin',
            reason='PLAT-4952 SoD regression',
            task_key='PLAT-4952',
            ttl_seconds=1800,
            status=JITElevatedAccessGrant.STATUS_PENDING,
        )
        self._auth(user_id=999, email='nova@shizuha.com', is_staff=True)
        resp = self.client.post(
            f'/api/jit-elevations/{grant.pk}/approve/',
            {'note': 'trying to self-approve'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN, resp.data)

    def test_plain_member_org_member_add_without_policy_proof_stays_pending(self):
        self._auth()
        response = self.client.post('/api/jit-elevations/', {
            'org_slug': self.org.slug,
            'scope': 'org.members.add',
            'requested_role': 'admin',
            'reason': 'PLAT-1346 regression: claimed low-risk member add without policy proof',
            'task_key': 'PLAT-1346',
            'ttl_seconds': 1800,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data['auto_approved'])
        grant = JITElevatedAccessGrant.objects.get()
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_PENDING)
        self.assertFalse(grant.is_active_now())
        self.assertEqual(grant.approval_path, JITElevatedAccessGrant.APPROVAL_TEAM)

        with patch('requests.get') as mock_get:
            mock_get.return_value = Mock(status_code=404, json=lambda: {})
            invite_response = self.client.post(
                f'/api/organizations/{self.org.slug}/members/',
                {'user_email': 'new@acme.com', 'role': 'member'},
                format='json',
            )

        self.assertEqual(invite_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(OrganizationMembership.objects.filter(
            organization=self.org,
            user_email='new@acme.com',
            is_pending=True,
        ).exists())

    @patch('organizations.tasks.dispatch_kubernetes_jit_use_task.delay')
    def test_plat6167_peer_approval_requester_consumes_exact_origin_apply(self, dispatch):
        """Production order: peer approval -> requester outbox -> revoke -> dispatch."""
        for user_id, email in ((10, 'requester@shizuha.com'), (11, 'peer@shizuha.com')):
            OrganizationMembership.objects.create(
                organization=self.org, user_id=user_id, user_email=email,
                role='member', is_pending=False,
            )
        platform = Team.objects.create(organization=self.org, name='Platform')
        peer_profile = EmployeeProfile.objects.get(
            membership__organization=self.org, membership__user_id=11,
        )
        TeamMembership.objects.create(team=platform, employee_profile=peer_profile, role='member')
        sha = 'a' * 40

        self._auth(user_id=10, email='requester@shizuha.com')
        requested = self.client.post('/api/jit-elevations/', {
            'org_slug': self.org.slug,
            'scope': JITElevatedAccessGrant.KUBERNETES_RBAC_APPLY_SCOPE,
            'reason': 'PLAT-6167 canonical Origin RBAC apply',
            'task_key': 'PLAT-6167',
            'ttl_seconds': 600,
            'commit_sha': sha,
        }, format='json')
        self.assertEqual(requested.status_code, status.HTTP_201_CREATED)
        grant = JITElevatedAccessGrant.objects.get(pk=requested.data['grant']['id'])
        self.assertTrue(grant.has_complete_current_exact_authority())
        self.assertEqual(grant.target_constraints['repository'], 'shizuha-labs/deploy')
        self.assertEqual(grant.target_constraints['workflow'], 'apply-origin-ci-deployer-rbac.yml')
        self.assertEqual(grant.target_constraints['script'], 'k3s/origin/apply-ci-deployer-rbac.sh')

        # Requester self-decision remains forbidden.
        refused = self.client.post(
            f'/api/jit-elevations/{grant.pk}/approve/', {'note': 'self'}, format='json',
        )
        self.assertEqual(refused.status_code, status.HTTP_403_FORBIDDEN)

        self._auth(user_id=11, email='peer@shizuha.com')
        approval = self.client.post(
            f'/api/jit-elevations/{grant.pk}/approve/', {'note': 'independent peer'}, format='json',
        )
        self.assertEqual(approval.status_code, status.HTTP_200_OK)

        self._auth(user_id=10, email='requester@shizuha.com')
        action = {
            'idempotency_key': 'PLAT-6167-v1',
            'expected_sha': sha,
            'action': 'apply-origin-ci-deployer-rbac',
        }
        with self.captureOnCommitCallbacks(execute=True):
            consumed = self.client.post(
                f'/api/jit-elevations/{grant.pk}/consume-kubernetes/', action, format='json',
            )
        self.assertEqual(consumed.status_code, status.HTTP_202_ACCEPTED)
        use = JITElevatedAccessGrantUse.objects.get(grant=grant)
        dispatch.assert_called_once_with(use.pk)
        grant.refresh_from_db()
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_REVOKED)
        self.assertEqual(grant.uses_consumed, 1)
        self.assertEqual(use.dispatch_status, 'pending')

        # Same immutable request replays; changed payload and fresh use fail closed.
        replay = self.client.post(
            f'/api/jit-elevations/{grant.pk}/consume-kubernetes/', action, format='json',
        )
        self.assertEqual(replay.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(replay.data['use_id'], use.pk)
        conflict = self.client.post(
            f'/api/jit-elevations/{grant.pk}/consume-kubernetes/',
            {**action, 'expected_sha': 'b' * 40}, format='json',
        )
        self.assertEqual(conflict.status_code, status.HTTP_409_CONFLICT)
        exhausted = self.client.post(
            f'/api/jit-elevations/{grant.pk}/consume-kubernetes/',
            {**action, 'idempotency_key': 'PLAT-6167-v2'}, format='json',
        )
        self.assertEqual(exhausted.status_code, status.HTTP_403_FORBIDDEN)

        self._auth(user_id=11, email='peer@shizuha.com')
        wrong_requester = self.client.post(
            f'/api/jit-elevations/{grant.pk}/consume-kubernetes/', action, format='json',
        )
        self.assertEqual(wrong_requester.status_code, status.HTTP_403_FORBIDDEN)

        # Expiry is evaluated before creating authority or an outbox use.
        expired = JITElevatedAccessGrant.objects.create(
            organization=self.org, requester_user_id=10,
            requester_email='requester@shizuha.com',
            scope=JITElevatedAccessGrant.KUBERNETES_RBAC_APPLY_SCOPE,
            requested_role='admin', reason='expired', task_key='PLAT-6167',
            ttl_seconds=600, status=JITElevatedAccessGrant.STATUS_APPROVED,
            approval_path=JITElevatedAccessGrant.APPROVAL_TEAM,
            approver_team=platform, owning_team='Platform',
            policy_key=grant.policy_key, policy_version=grant.policy_version,
            policy_digest=grant.policy_digest, target_constraints=grant.target_constraints,
            constraint_digest=grant.constraint_digest, max_uses=1,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self._auth(user_id=10, email='requester@shizuha.com')
        expired_result = self.client.post(
            f'/api/jit-elevations/{expired.pk}/consume-kubernetes/', action, format='json',
        )
        self.assertEqual(expired_result.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(expired.uses.exists())

    def test_verified_policy_org_member_add_auto_approves(self):
        self._auth(user_id=2, email='admin-platform@shizuha.com', is_staff=True)
        response = self.client.post('/api/jit-elevations/', {
            'org_slug': self.org.slug,
            'scope': 'org.members.add',
            'requested_role': 'admin',
            'reason': 'PLAT-1346 regression: machine-verified IT audit passed',
            'task_key': 'PLAT-1346',
            'ttl_seconds': 1800,
            'policy_slug': 'passed-it-audit-org-member-add',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['auto_approved'])
        grant = JITElevatedAccessGrant.objects.get()
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_APPROVED)
        self.assertTrue(grant.is_active_now())
        self.assertEqual(grant.approval_path, JITElevatedAccessGrant.APPROVAL_POLICY)
        self.assertEqual(grant.policy_slug, 'passed-it-audit-org-member-add')
        self.assertEqual(grant.decided_by_email, 'policy:passed-it-audit-org-member-add')

    def test_expired_grant_does_not_project_or_authorize(self):
        grant = JITElevatedAccessGrant.objects.create(
            organization=self.org,
            requester_user_id=3,
            requester_email='agent@acme.com',
            scope='org.members.add',
            requested_role='admin',
            reason='expired grant regression',
            task_key='PLAT-1346',
            ttl_seconds=60,
            status=JITElevatedAccessGrant.STATUS_APPROVED,
            approval_path=JITElevatedAccessGrant.APPROVAL_POLICY,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertFalse(grant.is_active_now())

        factory = APIRequestFactory()
        request = factory.get('/api/internal/users/3/memberships/', {'email': 'agent@acme.com'})
        response = InternalUserMembershipsView.as_view()(request, user_id=3)
        self.assertEqual(response.data['memberships'][str(self.org.id)], 'member')

        self._auth()
        with patch('requests.get') as mock_get:
            mock_get.return_value = Mock(status_code=404, json=lambda: {})
            invite_response = self.client.post(
                f'/api/organizations/{self.org.slug}/members/',
                {'user_email': 'blocked@acme.com', 'role': 'member'},
                format='json',
            )
        self.assertEqual(invite_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_high_risk_owner_request_is_pending_for_owning_team_not_operator(self):
        self._auth()
        response = self.client.post('/api/jit-elevations/', {
            'org_slug': self.org.slug,
            'scope': 'org.members.owner_transfer',
            'requested_role': 'owner',
            'reason': 'needs owning-team review',
            'task_key': 'PLAT-1346',
            'ttl_seconds': 1800,
            'owning_team': 'security',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data['auto_approved'])
        grant = JITElevatedAccessGrant.objects.get()
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_PENDING)
        self.assertEqual(grant.approval_path, JITElevatedAccessGrant.APPROVAL_TEAM)
        self.assertEqual(grant.owning_team, 'security')
        self.assertNotEqual(grant.owning_team, 'operator')

    def test_scoped_jit_grant_does_not_inflate_generic_org_membership(self):
        # P1 regression: a scoped JIT grant (org.members.add) must NOT appear in
        # the memberships dict — that dict drives JWT org-role claims and must
        # reflect only real OrganizationMembership rows.
        grant = JITElevatedAccessGrant.objects.create(
            organization=self.org,
            requester_user_id=3,
            requester_email='agent@acme.com',
            scope='org.members.add',
            requested_role='admin',
            reason='projection regression',
            task_key='PLAT-1346',
            ttl_seconds=3600,
            status=JITElevatedAccessGrant.STATUS_APPROVED,
            approval_path=JITElevatedAccessGrant.APPROVAL_POLICY,
            expires_at=timezone.now() + timedelta(minutes=30),
        )

        factory = APIRequestFactory()
        request = factory.get('/api/internal/users/3/memberships/', {'email': 'agent@acme.com'})
        response = InternalUserMembershipsView.as_view()(request, user_id=3)
        # memberships must reflect only the real OrganizationMembership row (role='member'),
        # not the JIT grant's requested_role ('admin').
        self.assertEqual(response.data['memberships'][str(self.org.id)], 'member')
        # The grant must appear in jit_scoped_grants instead.
        self.assertEqual(len(response.data['jit_scoped_grants']), 1)
        jit = response.data['jit_scoped_grants'][0]
        self.assertEqual(jit['scope'], 'org.members.add')
        self.assertEqual(jit['role'], 'admin')

        # After revocation the scoped grants list is empty; membership unchanged.
        grant.revoke(actor_user_id=1, actor_email='owner@acme.com', note='done')
        response = InternalUserMembershipsView.as_view()(request, user_id=3)
        self.assertEqual(response.data['memberships'][str(self.org.id)], 'member')
        self.assertEqual(response.data['jit_scoped_grants'], [])

    def test_self_approval_blocked(self):
        # P1 regression: the requester must not be able to approve their own grant.
        grant = JITElevatedAccessGrant.objects.create(
            organization=self.org,
            requester_user_id=3,
            requester_email='agent@acme.com',
            scope='org.members.add',
            requested_role='admin',
            reason='self-approval regression',
            task_key='PLAT-1346',
            ttl_seconds=1800,
            status=JITElevatedAccessGrant.STATUS_PENDING,
            approval_path=JITElevatedAccessGrant.APPROVAL_TEAM,
            risk_level=JITElevatedAccessGrant.RISK_LOW,
        )
        # Authenticate as the requester (user_id=3) who is also an org member
        self._auth(user_id=3, email='agent@acme.com')
        response = self.client.post(
            f'/api/jit-elevations/{grant.pk}/approve/',
            {'note': 'self-approving'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('own', response.data['error'])
        grant.refresh_from_db()
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_PENDING)

    def test_high_risk_grant_requires_staff_approval(self):
        # P1 regression: an ordinary org admin must not be able to approve a
        # high-risk JIT grant; only staff may do so.
        grant = JITElevatedAccessGrant.objects.create(
            organization=self.org,
            requester_user_id=3,
            requester_email='agent@acme.com',
            scope='org.members.owner_transfer',
            requested_role='owner',
            reason='owner transfer request',
            task_key='PLAT-1346',
            ttl_seconds=3600,
            status=JITElevatedAccessGrant.STATUS_PENDING,
            approval_path=JITElevatedAccessGrant.APPROVAL_TEAM,
            risk_level=JITElevatedAccessGrant.RISK_HIGH,
            owning_team='security',
        )
        # Authenticate as the org owner (user_id=1), a non-staff org admin
        self._auth(user_id=1, email='owner@acme.com', is_staff=False)
        response = self.client.post(
            f'/api/jit-elevations/{grant.pk}/approve/',
            {'note': 'approve by org owner'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('staff', response.data['error'])
        grant.refresh_from_db()
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_PENDING)

        # Staff can approve it
        self._auth(user_id=2, email='staff@shizuha.com', is_staff=True)
        response = self.client.post(
            f'/api/jit-elevations/{grant.pk}/approve/',
            {'note': 'staff approving high-risk grant'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        grant.refresh_from_db()
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_APPROVED)

    def test_plat5079_detail_reads_grant_and_decision_events(self):
        """PLAT-5079: an entitled MCP seat can read the stored requester id and
        the actor identity recorded on each decision event."""
        grant = JITElevatedAccessGrant.objects.create(
            organization=self.org,
            requester_user_id=3,
            requester_email='agent@acme.com',
            scope='org.members.owner_transfer',
            requested_role='owner',
            reason='owner transfer request',
            task_key='PLAT-5079',
            ttl_seconds=3600,
            status=JITElevatedAccessGrant.STATUS_PENDING,
            approval_path=JITElevatedAccessGrant.APPROVAL_TEAM,
            risk_level=JITElevatedAccessGrant.RISK_HIGH,
            owning_team='security',
        )
        # A decision writes the actor identity to the event history.
        self._auth(user_id=2, email='staff@shizuha.com', is_staff=True)
        response = self.client.post(
            f'/api/jit-elevations/{grant.pk}/approve/',
            {'note': 'staff approving for PLAT-5079'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # The requester (entitled) can read the grant + events.
        self._auth(user_id=3, email='agent@acme.com', is_staff=False)
        detail = self.client.get(f'/api/jit-elevations/{grant.pk}/')
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data['grant']['requester_user_id'], 3)
        self.assertEqual(detail.data['grant']['requester_email'], 'agent@acme.com')
        events = detail.data['events']
        self.assertTrue(events, 'decision event rows must be returned')
        self.assertEqual(events[-1]['event_type'], 'approved')
        self.assertEqual(events[-1]['actor_user_id'], 2)
        self.assertEqual(events[-1]['actor_email'], 'staff@shizuha.com')

    def test_plat5079_detail_negative_control_unentitled_seat_404(self):
        """PLAT-5079: a seat NOT entitled to the grant still cannot read it —
        the fix must not widen visibility."""
        grant = JITElevatedAccessGrant.objects.create(
            organization=self.org,
            requester_user_id=3,
            requester_email='agent@acme.com',
            scope='org.members.owner_transfer',
            requested_role='owner',
            reason='owner transfer request',
            task_key='PLAT-5079',
            ttl_seconds=3600,
            status=JITElevatedAccessGrant.STATUS_PENDING,
            approval_path=JITElevatedAccessGrant.APPROVAL_TEAM,
            risk_level=JITElevatedAccessGrant.RISK_HIGH,
            owning_team='security',
        )
        # An unrelated user (not requester, not org admin, not staff) cannot read.
        self._auth(user_id=999, email='outsider@example.com', is_staff=False)
        detail = self.client.get(f'/api/jit-elevations/{grant.pk}/')
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)

    @patch('organizations.views.fleet_agent_write_denial', return_value=None)
    @patch('organizations.views.record_jit_invariant_failure')
    @patch('organizations.views.emit_boundary_denial')
    def test_plat4878_production_order_exact_team_peer_approval_and_consumption(
        self, emit_failure, record_failure, _fleet_denial,
    ):
        """Aoi request -> Hiro peer approval -> exact ORIG-120 roster action."""
        identities = (
            (10, 'aoi@shizuha.com'),
            (11, 'hiro@shizuha.com'),
            (12, 'unrelated@shizuha.com'),
            (13, 'ryo@shizuha.com'),
            (14, 'removed-lead@shizuha.com'),
        )
        for user_id, email in identities:
            OrganizationMembership.objects.create(
                organization=self.org,
                user_id=user_id,
                user_email=email,
                role='member',
                is_pending=False,
            )
        platform = Team.objects.create(
            organization=self.org,
            name='Platform',
            lead_id=14,
            lead_email='removed-lead@shizuha.com',
        )
        merge = Team.objects.create(organization=self.org, name='Merge')
        aoi_profile = EmployeeProfile.objects.get(membership__user_id=10, membership__organization=self.org)
        hiro_profile = EmployeeProfile.objects.get(membership__user_id=11, membership__organization=self.org)
        ryo_profile = EmployeeProfile.objects.get(membership__user_id=13, membership__organization=self.org)
        TeamMembership.objects.create(team=platform, employee_profile=aoi_profile, role='lead')
        hiro_team_membership = TeamMembership.objects.create(
            team=platform,
            employee_profile=hiro_profile,
            role='member',
        )

        self._auth(user_id=10, email='aoi@shizuha.com')
        requested = self.client.post('/api/jit-elevations/', {
            'org_slug': self.org.slug,
            'scope': JITElevatedAccessGrant.TEAM_MEMBER_ADD_SCOPE,
            'requested_role': 'admin',
            'reason': 'ORIG-120 exact merge-roster recovery',
            'task_key': 'PLAT-4842',
            'ttl_seconds': 900,
            'target_team_id': merge.id,
            'target_user_id': 13,
            'target_role': 'member',
            # Compatibility metadata cannot widen the provider-owned policy.
            'owning_team': 'admin-platform',
        }, format='json')
        self.assertEqual(requested.status_code, status.HTTP_201_CREATED)
        grant = JITElevatedAccessGrant.objects.get(pk=requested.data['grant']['id'])
        self.assertEqual(grant.approver_team, platform)
        self.assertEqual(grant.target_team, merge)
        self.assertEqual(grant.target_user_id, 13)
        self.assertEqual(grant.target_role, 'member')
        self.assertTrue(grant.has_complete_current_exact_authority())

        # A stale Team.lead_id is not authority after the lead leaves the org.
        removed_lead_membership = OrganizationMembership.objects.get(
            organization=self.org,
            user_id=14,
        )
        removed_lead_membership.is_active = False
        removed_lead_membership.save(update_fields=['is_active', 'updated_at'])
        self._auth(user_id=14, email='removed-lead@shizuha.com')
        removed_lead_list = self.client.get('/api/jit-elevations/', {'status': 'pending'})
        self.assertEqual(removed_lead_list.data['count'], 0)
        removed_lead_decision = self.client.post(
            f'/api/jit-elevations/{grant.pk}/approve/',
            {'note': 'stale lead must fail'},
            format='json',
        )
        self.assertEqual(removed_lead_decision.status_code, status.HTTP_403_FORBIDDEN)

        # Emergency policy disable blocks admission and decision immediately;
        # the stored snapshot is audit evidence, never executable authority.
        disabled_policy = grant.exact_policy_for_scope(grant.scope)
        disabled_policy['enabled'] = False
        with patch.dict(
            JITElevatedAccessGrant.EXACT_SCOPE_POLICIES,
            {grant.scope: disabled_policy},
        ):
            self._auth(user_id=11, email='hiro@shizuha.com')
            with self.captureOnCommitCallbacks(execute=True):
                disabled_decision = self.client.post(
                    f'/api/jit-elevations/{grant.pk}/approve/',
                    {'note': 'must fail while policy is disabled'},
                    format='json',
                )
            self.assertEqual(disabled_decision.status_code, status.HTTP_409_CONFLICT)
            self._auth(user_id=10, email='aoi@shizuha.com')
            with self.captureOnCommitCallbacks(execute=True):
                disabled_admission = self.client.post('/api/jit-elevations/', {
                    'org_slug': self.org.slug,
                    'scope': grant.scope,
                    'reason': 'disabled policy must reject admission',
                    'task_key': 'PLAT-4878',
                    'target_team_id': merge.id,
                    'target_user_id': 13,
                    'target_role': 'member',
                }, format='json')
            self.assertEqual(disabled_admission.status_code, status.HTTP_403_FORBIDDEN)

        # The requester can inspect but never approve, even as Platform lead.
        self_approval = self.client.post(
            f'/api/jit-elevations/{grant.pk}/approve/',
            {'note': 'self approval must fail'},
            format='json',
        )
        self.assertEqual(self_approval.status_code, status.HTTP_403_FORBIDDEN)

        # An unrelated same-org peer cannot discover or decide the grant.
        self._auth(user_id=12, email='unrelated@shizuha.com')
        hidden = self.client.get('/api/jit-elevations/', {'status': 'pending'})
        self.assertEqual(hidden.status_code, status.HTTP_200_OK)
        self.assertEqual(hidden.data['count'], 0)
        unauthorized = self.client.post(
            f'/api/jit-elevations/{grant.pk}/approve/',
            {'note': 'unrelated peer'},
            format='json',
        )
        self.assertEqual(unauthorized.status_code, status.HTTP_403_FORBIDDEN)

        # Hiro's active membership in the exact stored approver Team is the
        # authority.  No blanket staff or target-org-admin relay is involved.
        self._auth(user_id=11, email='hiro@shizuha.com')
        hiro_team_membership.is_active = False
        hiro_team_membership.left_at = timezone.now()
        hiro_team_membership.save(update_fields=['is_active', 'left_at'])
        inactive_hidden = self.client.get('/api/jit-elevations/', {'status': 'pending'})
        self.assertEqual(inactive_hidden.data['count'], 0)
        inactive_decision = self.client.post(
            f'/api/jit-elevations/{grant.pk}/approve/',
            {'note': 'stale roster membership must fail'},
            format='json',
        )
        self.assertEqual(inactive_decision.status_code, status.HTTP_403_FORBIDDEN)
        hiro_team_membership.is_active = True
        hiro_team_membership.left_at = None
        hiro_team_membership.save(update_fields=['is_active', 'left_at'])
        visible = self.client.get('/api/jit-elevations/', {'status': 'pending'})
        self.assertEqual([row['id'] for row in visible.data['results']], [grant.id])
        approval = self.client.post(
            f'/api/jit-elevations/{grant.pk}/approve/',
            {'note': 'independent Platform peer approval'},
            format='json',
        )
        self.assertEqual(approval.status_code, status.HTTP_200_OK)
        grant.refresh_from_db()
        self.assertTrue(grant.is_active_now())
        self.assertLessEqual(grant.expires_at, grant.decided_at + timedelta(seconds=900))

        # The exact target-constrained action is consumed transactionally and
        # auto-revokes at its one-use bound.  Generic JWT projection remains
        # permanently empty for this scope.
        self._auth(user_id=10, email='aoi@shizuha.com')
        internal_request = APIRequestFactory().get(
            '/api/internal/users/10/memberships/',
            {'email': 'aoi@shizuha.com'},
        )
        projection = InternalUserMembershipsView.as_view()(internal_request, user_id=10)
        self.assertEqual(projection.data['jit_scoped_grants'], [])

        action = {
            'employee_profile_id': ryo_profile.id,
            'role': 'member',
            'jit_grant_id': grant.id,
            'jit_idempotency_key': 'ORIG-120-merge-roster-v1',
        }
        disabled_policy = grant.exact_policy_for_scope(grant.scope)
        disabled_policy['enabled'] = False
        with patch.dict(
            JITElevatedAccessGrant.EXACT_SCOPE_POLICIES,
            {grant.scope: disabled_policy},
        ):
            with self.captureOnCommitCallbacks(execute=True):
                disabled_consumption = self.client.post(
                    f'/api/organizations/{self.org.slug}/teams/{merge.id}/members/',
                    action,
                    format='json',
                )
            self.assertEqual(disabled_consumption.status_code, status.HTTP_403_FORBIDDEN)

        mismatched_target = self.client.post(
            f'/api/organizations/{self.org.slug}/teams/{merge.id}/members/',
            {**action, 'role': 'lead', 'jit_idempotency_key': 'ORIG-120-wrong-target'},
            format='json',
        )
        self.assertEqual(mismatched_target.status_code, status.HTTP_403_FORBIDDEN)
        consumed = self.client.post(
            f'/api/organizations/{self.org.slug}/teams/{merge.id}/members/',
            action,
            format='json',
        )
        self.assertEqual(consumed.status_code, status.HTTP_201_CREATED)
        membership_id = consumed.data['id']
        self.assertTrue(TeamMembership.objects.filter(
            pk=membership_id,
            team=merge,
            employee_profile=ryo_profile,
            role='member',
            is_active=True,
        ).exists())
        grant.refresh_from_db()
        self.assertEqual(grant.uses_consumed, 1)
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_REVOKED)
        self.assertIsNotNone(grant.revoked_at)

        self._auth(user_id=12, email='unrelated@shizuha.com')
        unauthorized_replay = self.client.post(
            f'/api/organizations/{self.org.slug}/teams/{merge.id}/members/',
            action,
            format='json',
        )
        self.assertEqual(unauthorized_replay.status_code, status.HTTP_403_FORBIDDEN)

        # A consume that commits first wins the revoke race; a later revoke
        # cannot rewrite the audit history as revoked-before-use.
        self._auth(user_id=11, email='hiro@shizuha.com')
        revoke_after_use = self.client.post(
            f'/api/jit-elevations/{grant.pk}/revoke/',
            {'note': 'too late: consumption already committed'},
            format='json',
        )
        self.assertEqual(revoke_after_use.status_code, status.HTTP_400_BAD_REQUEST)

        # Replay is checked before lifecycle/use-count rejection.  The same
        # key+digest returns the committed result; a changed digest conflicts.
        self._auth(user_id=10, email='aoi@shizuha.com')
        replay = self.client.post(
            f'/api/organizations/{self.org.slug}/teams/{merge.id}/members/',
            action,
            format='json',
        )
        self.assertEqual(replay.status_code, status.HTTP_201_CREATED)
        self.assertEqual(replay.data['id'], membership_id)
        conflicting_replay = self.client.post(
            f'/api/organizations/{self.org.slug}/teams/{merge.id}/members/',
            {**action, 'role': 'lead'},
            format='json',
        )
        self.assertEqual(conflicting_replay.status_code, status.HTTP_409_CONFLICT)
        fresh_after_exhaustion = self.client.post(
            f'/api/organizations/{self.org.slug}/teams/{merge.id}/members/',
            {**action, 'jit_idempotency_key': 'ORIG-120-fresh-retry'},
            format='json',
        )
        self.assertEqual(fresh_after_exhaustion.status_code, status.HTTP_403_FORBIDDEN)

        self.assertEqual(JITElevatedAccessGrantUse.objects.filter(grant=grant).count(), 1)
        event_types = list(
            JITElevatedAccessGrantEvent.objects.filter(grant=grant)
            .order_by('created_at', 'id')
            .values_list('event_type', flat=True)
        )
        # PLAT-5042: identity denials are now recorded with the compared pair, so
        # this exact-sequence audit gains a row. The trailing 'identity_denied' is
        # actor 12 (unrelated@shizuha.com) being correctly refused this grant,
        # whose requester is 10 (aoi) — a legitimate refusal that previously left
        # no evidence at all, which is the defect this ticket exists to fix.
        self.assertEqual(event_types, [
            'requested', 'invariant_failed',
            'requester_self_decide_denied',
            'approved', 'invariant_failed',
            'consumed', 'auto_revoked', 'identity_denied',
        ])
        # The row must carry BOTH compared values — an event that records the
        # denial without the pair reinstates the ~40h-undiagnosable state.
        denial = JITElevatedAccessGrantEvent.objects.filter(
            grant=grant, event_type='identity_denied',
        ).latest('created_at', 'id')
        self.assertEqual(denial.detail['actor_user_id'], 12)
        self.assertEqual(denial.detail['grant_requester_user_id'], 10)
        self.assertFalse(denial.detail['identity_match'])
        self.assertEqual(denial.detail['actor_user_id_source'], 'request.user.id')
        self.assertEqual(
            JITElevatedAccessGrantEvent.objects.filter(
                event_type='invariant_failed',
            ).count(),
            3,
        )
        self.assertEqual(
            [call.kwargs['reason'] for call in emit_failure.call_args_list],
            [
                'jit_exact_contract_stale',
                'jit_exact_policy_disabled',
                'jit_exact_contract_stale',
            ],
        )
        self.assertEqual(record_failure.call_count, 3)

    @override_settings(CONNECT_SECURITY_EVENT_ORIGIN_SECRET='boundary-secret')
    @patch('organizations.security_events.requests.post')
    @patch('organizations.security_events._metrics_redis_client')
    def test_jit_invariant_failure_is_persisted_deduped_and_exposed(self, redis_client, post):
        """PLAT-1254: failures persist, alert once per window, and expose liveness."""
        redis = Mock()
        redis.set.side_effect = [True, False]
        redis.mget.return_value = ['0'] * 8 + ['2']
        redis_client.return_value = redis
        post.return_value.status_code = status.HTTP_202_ACCEPTED
        self._auth(user_id=3, email='agent@acme.com')
        payload = {
            'org_slug': self.org.slug,
            'scope': JITElevatedAccessGrant.TEAM_MEMBER_ADD_SCOPE,
            'reason': 'prove fail-loud invariant',
            'task_key': 'PLAT-4878',
            'target_team_id': Team.objects.create(
                organization=self.org,
                name='Merge',
            ).id,
            'target_user_id': 3,
            'target_role': 'member',
        }

        with self.captureOnCommitCallbacks(execute=True):
            first = self.client.post('/api/jit-elevations/', payload, format='json')
        with self.captureOnCommitCallbacks(execute=True):
            second = self.client.post('/api/jit-elevations/', payload, format='json')

        self.assertEqual(first.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            JITElevatedAccessGrantEvent.objects.filter(
                grant__isnull=True,
                event_type='invariant_failed',
                detail__code='jit_approver_team_not_unique',
            ).count(),
            2,
        )
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs['json']['data']['owner_team'], 'platform')

        metrics = self.client.get('/api/metrics/security-events/')
        self.assertEqual(metrics.status_code, status.HTTP_200_OK)
        self.assertIn(
            'platform_jit_approval_invariant_failures_total{service="admin"} 2',
            metrics.content.decode('utf-8'),
        )

    def test_exact_scope_legacy_free_form_team_never_mints_peer_authority(self):
        """A uniquely matching old owning_team string is still not authority."""
        for user_id, email in ((20, 'requester@shizuha.com'), (21, 'peer@shizuha.com')):
            OrganizationMembership.objects.create(
                organization=self.org,
                user_id=user_id,
                user_email=email,
                role='member',
                is_pending=False,
            )
        platform = Team.objects.create(organization=self.org, name='Platform')
        peer_profile = EmployeeProfile.objects.get(
            membership__organization=self.org,
            membership__user_id=21,
        )
        TeamMembership.objects.create(team=platform, employee_profile=peer_profile, role='member')
        legacy = JITElevatedAccessGrant.objects.create(
            organization=self.org,
            requester_user_id=20,
            requester_email='requester@shizuha.com',
            scope=JITElevatedAccessGrant.TEAM_MEMBER_ADD_SCOPE,
            requested_role='admin',
            reason='legacy row lacks canonical target and policy snapshot',
            task_key='PLAT-4842',
            ttl_seconds=900,
            owning_team='Platform',
            status=JITElevatedAccessGrant.STATUS_PENDING,
        )

        self._auth(user_id=21, email='peer@shizuha.com')
        hidden = self.client.get('/api/jit-elevations/', {'status': 'pending'})
        self.assertEqual(hidden.data['count'], 0)
        rejected = self.client.post(
            f'/api/jit-elevations/{legacy.pk}/approve/',
            {'note': 'free-form team must not mint authority'},
            format='json',
        )
        self.assertEqual(rejected.status_code, status.HTTP_403_FORBIDDEN)
        legacy.refresh_from_db()
        self.assertEqual(legacy.status, JITElevatedAccessGrant.STATUS_PENDING)

        # The incomplete row remains requester-visible so the requester can
        # diagnose and re-request it under the current registered policy.
        self._auth(user_id=20, email='requester@shizuha.com')
        requester_view = self.client.get('/api/jit-elevations/', {'status': 'pending'})
        self.assertEqual([row['id'] for row in requester_view.data['results']], [legacy.id])
        requester_revoke = self.client.post(
            f'/api/jit-elevations/{legacy.pk}/revoke/',
            {'note': 'replace incomplete legacy row with a current request'},
            format='json',
        )
        self.assertEqual(requester_revoke.status_code, status.HTTP_200_OK)
        legacy.refresh_from_db()
        self.assertEqual(legacy.status, JITElevatedAccessGrant.STATUS_REVOKED)

    @patch('organizations.views.fleet_agent_write_denial', return_value=None)
    def test_plat5042_string_user_id_claim_still_consumes_own_grant(self, _fleet_denial):
        """Requester with str-typed user.id can consume their own approved grant.

        Regression for the production identity-mismatch class: JWT/FederatedUser
        may surface user_id as str while the grant stores IntegerField. Bare
        ``!=`` then fails for every legitimate requester. Normalisation lives
        in ``_actor_identity`` (and FederatedUser.__init__) so all five
        store/compare sites share one boundary.
        """
        from organizations.views import _normalize_user_id, _actor_identity

        self.assertEqual(_normalize_user_id('110'), 110)
        self.assertEqual(_normalize_user_id(110), 110)
        self.assertIsNone(_normalize_user_id(None))
        self.assertIsNone(_normalize_user_id(True))
        self.assertIsNone(_normalize_user_id('not-an-id'))

        for user_id, email in (
            (30, 'req@shizuha.com'),
            (31, 'peer@shizuha.com'),
            (32, 'target@shizuha.com'),
        ):
            OrganizationMembership.objects.create(
                organization=self.org,
                user_id=user_id,
                user_email=email,
                role='member',
                is_pending=False,
            )
        platform = Team.objects.create(organization=self.org, name='Platform')
        merge = Team.objects.create(organization=self.org, name='Merge')
        peer_profile = EmployeeProfile.objects.get(
            membership__organization=self.org, membership__user_id=31,
        )
        target_profile = EmployeeProfile.objects.get(
            membership__organization=self.org, membership__user_id=32,
        )
        TeamMembership.objects.create(
            team=platform, employee_profile=peer_profile, role='member',
        )

        # Create as int-id principal (normal path) — store site.
        self._auth(user_id=30, email='req@shizuha.com')
        requested = self.client.post('/api/jit-elevations/', {
            'org_slug': self.org.slug,
            'scope': JITElevatedAccessGrant.TEAM_MEMBER_ADD_SCOPE,
            'requested_role': 'admin',
            'reason': 'PLAT-5042 string-id consume regression',
            'task_key': 'PLAT-5042',
            'ttl_seconds': 900,
            'target_team_id': merge.id,
            'target_user_id': 32,
            'target_role': 'member',
        }, format='json')
        self.assertEqual(requested.status_code, status.HTTP_201_CREATED)
        grant = JITElevatedAccessGrant.objects.get(pk=requested.data['grant']['id'])
        self.assertEqual(grant.requester_user_id, 30)
        self.assertIsInstance(grant.requester_user_id, int)

        # Peer approves (decision path).
        self._auth(user_id=31, email='peer@shizuha.com')
        approval = self.client.post(
            f'/api/jit-elevations/{grant.pk}/approve/',
            {'note': 'peer approve'},
            format='json',
        )
        self.assertEqual(approval.status_code, status.HTTP_200_OK)

        # Consume with a FederatedUser-like principal whose .id is a STRING.
        # This is the production shape that previously 403'd every consume.
        string_id_user = MockUser(id='30', email='req@shizuha.com')
        self.client.force_authenticate(user=string_id_user)
        factory_request = APIRequestFactory().post('/')
        factory_request.user = string_id_user
        actor_id, actor_email = _actor_identity(factory_request)
        self.assertEqual(actor_id, 30)
        self.assertIsInstance(actor_id, int)
        self.assertEqual(actor_email, 'req@shizuha.com')

        consumed = self.client.post(
            f'/api/organizations/{self.org.slug}/teams/{merge.id}/members/',
            {
                'employee_profile_id': target_profile.id,
                'role': 'member',
                'jit_grant_id': grant.id,
                'jit_idempotency_key': 'plat-5042-string-id-v1',
            },
            format='json',
        )
        self.assertEqual(
            consumed.status_code,
            status.HTTP_201_CREATED,
            msg=getattr(consumed, 'data', consumed.content),
        )
        grant.refresh_from_db()
        self.assertEqual(grant.uses_consumed, 1)

    def test_pls1350_merge_scope_is_visible_to_devops_peer_not_requester_decision(self):
        OrganizationMembership.objects.create(
            organization=self.org, user_id=20, user_email='req-merge@shizuha.com',
            role='member', is_pending=False,
        )
        OrganizationMembership.objects.create(
            organization=self.org, user_id=21, user_email='devops-peer@shizuha.com',
            role='member', is_pending=False,
        )
        devops = Team.objects.create(organization=self.org, name='DevOps')
        peer = EmployeeProfile.objects.get(
            membership__organization=self.org, membership__user_id=21,
        )
        TeamMembership.objects.create(team=devops, employee_profile=peer, role='member')

        self._auth(user_id=20, email='req-merge@shizuha.com')
        requested = self.client.post('/api/jit-elevations/', {
            'org_slug': self.org.slug,
            'scope': JITElevatedAccessGrant.ORIGIN_REPOSITORY_MERGE_SCOPE,
            'reason': 'PLS-1350 merge rung',
            'task_key': 'PLS-1350',
            'ttl_seconds': 3600,
            'owning_team': 'devops',
            'repository': 'shizuha-labs/pulse',
            'pr_number': 792,
        }, format='json')
        self.assertEqual(requested.status_code, status.HTTP_201_CREATED, requested.data)
        grant = JITElevatedAccessGrant.objects.get(pk=requested.data['grant']['id'])
        self.assertEqual(grant.approver_team, devops)
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_PENDING)
        self.assertEqual(grant.target_constraints['repository'], 'shizuha-labs/pulse')
        self.assertEqual(grant.target_constraints['pr_number'], 792)
        self.assertNotIn(grant.scope, JITElevatedAccessGrant.LOW_RISK_AUTO_SCOPES)

        self_decision = self.client.post(
            f'/api/jit-elevations/{grant.pk}/approve/',
            {'note': 'requester must not self-approve'},
            format='json',
        )
        self.assertEqual(self_decision.status_code, status.HTTP_403_FORBIDDEN)

        self._auth(user_id=21, email='devops-peer@shizuha.com')
        listed = self.client.get('/api/jit-elevations/', {'status': 'pending'})
        self.assertEqual([row['id'] for row in listed.data['results']], [grant.id])
        fetched = self.client.get(f'/api/jit-elevations/{grant.pk}/')
        self.assertEqual(fetched.status_code, status.HTTP_200_OK)

    def test_plat5042_uncited_grant_message_and_sod_self_decision(self):
        """Bare call names the uncited grant; requester still cannot self-approve.

        AC1: uncited approved grant → code jit_grant_not_cited (not bare
        "Permission denied").
        AC4: SoD negative control — after id normalisation the requester still
        cannot approve/deny their own grant, and the refusal is audited with
        the compared pair (not via the paging invariant helper).
        """
        for user_id, email in (
            (40, 'req2@shizuha.com'),
            (41, 'peer2@shizuha.com'),
            (42, 'tgt2@shizuha.com'),
        ):
            OrganizationMembership.objects.create(
                organization=self.org,
                user_id=user_id,
                user_email=email,
                role='member',
                is_pending=False,
            )
        # Policy locks approver_team_name='Platform' (EXACT_SCOPE_POLICIES).
        platform = Team.objects.create(organization=self.org, name='Platform')
        merge = Team.objects.create(organization=self.org, name='Merge')
        peer_profile = EmployeeProfile.objects.get(
            membership__organization=self.org, membership__user_id=41,
        )
        target_profile = EmployeeProfile.objects.get(
            membership__organization=self.org, membership__user_id=42,
        )
        TeamMembership.objects.create(
            team=platform, employee_profile=peer_profile, role='member',
        )

        self._auth(user_id=40, email='req2@shizuha.com')
        requested = self.client.post('/api/jit-elevations/', {
            'org_slug': self.org.slug,
            'scope': JITElevatedAccessGrant.TEAM_MEMBER_ADD_SCOPE,
            'requested_role': 'admin',
            'reason': 'PLAT-5042 uncited + SoD regression',
            'task_key': 'PLAT-5042',
            'ttl_seconds': 900,
            'target_team_id': merge.id,
            'target_user_id': 42,
            'target_role': 'member',
        }, format='json')
        self.assertEqual(requested.status_code, status.HTTP_201_CREATED)
        grant = JITElevatedAccessGrant.objects.get(pk=requested.data['grant']['id'])

        # AC4 SoD negative control: requester cannot approve own grant.
        self_approve = self.client.post(
            f'/api/jit-elevations/{grant.pk}/approve/',
            {'note': 'must fail SoD'},
            format='json',
        )
        self.assertEqual(self_approve.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('cannot approve or deny their own', self_approve.data['error'])
        sod = JITElevatedAccessGrantEvent.objects.filter(
            grant=grant, event_type='requester_self_decide_denied',
        ).latest('created_at', 'id')
        self.assertEqual(sod.detail['actor_user_id'], 40)
        self.assertEqual(sod.detail['grant_requester_user_id'], 40)
        self.assertTrue(sod.detail['identity_match'])
        # Must NOT page: identity/SoD denials go through _audit_jit only.
        self.assertFalse(
            JITElevatedAccessGrantEvent.objects.filter(
                grant=grant, event_type='invariant_failed',
                detail__code='requester_self_decide_denied',
            ).exists(),
        )

        # Peer approves so the grant becomes active.
        self._auth(user_id=41, email='peer2@shizuha.com')
        approval = self.client.post(
            f'/api/jit-elevations/{grant.pk}/approve/',
            {'note': 'peer approve'},
            format='json',
        )
        self.assertEqual(approval.status_code, status.HTTP_200_OK)

        # AC1: bare call (no jit_grant_id) must name the uncited grant.
        self._auth(user_id=40, email='req2@shizuha.com')
        bare = self.client.post(
            f'/api/organizations/{self.org.slug}/teams/{merge.id}/members/',
            {'employee_profile_id': target_profile.id, 'role': 'member'},
            format='json',
        )
        self.assertEqual(bare.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(bare.data.get('code'), 'jit_grant_not_cited')
        self.assertIn('not cited', bare.data['error'])
        self.assertNotEqual(bare.data['error'], 'Permission denied')


class JITFleetRosterForwardTests(TestCase):
    """PLAT-6071 Option A: fleet-agent JIT consume forwards the roster mutation
    to Pulse's internal endpoint and consumes the grant only after Pulse
    confirms. A stale expected_version fails WITHOUT consuming the grant or
    partially mutating either store (acceptance #4).
    """

    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(
            name='Acme Corp',
            slug='acme-corp',
            owner_id=1,
        )
        OrganizationMembership.objects.create(
            organization=self.org,
            user_id=1,
            user_email='owner@acme.com',
            role='owner',
            is_pending=False,
        )
        for user_id, email in (
            (40, 'req@shizuha.com'),
            (41, 'peer@shizuha.com'),
            (42, 'target@shizuha.com'),
        ):
            OrganizationMembership.objects.create(
                organization=self.org,
                user_id=user_id,
                user_email=email,
                role='member',
                is_pending=False,
            )
        self.platform = Team.objects.create(organization=self.org, name='Platform')
        self.merge = Team.objects.create(organization=self.org, name='Merge')
        peer_profile = EmployeeProfile.objects.get(
            membership__organization=self.org, membership__user_id=41,
        )
        self.target_profile = EmployeeProfile.objects.get(
            membership__organization=self.org, membership__user_id=42,
        )
        TeamMembership.objects.create(
            team=self.platform, employee_profile=peer_profile, role='member',
        )

    def _approved_grant(self):
        self.client.force_authenticate(user=MockUser(id=40, email='req@shizuha.com'))
        requested = self.client.post('/api/jit-elevations/', {
            'org_slug': self.org.slug,
            'scope': JITElevatedAccessGrant.TEAM_MEMBER_ADD_SCOPE,
            'requested_role': 'admin',
            'reason': 'PLAT-6071 fleet-agent roster forward',
            'task_key': 'PLAT-6071',
            'ttl_seconds': 900,
            'target_team_id': self.merge.id,
            'target_user_id': 42,
            'target_role': 'member',
        }, format='json')
        self.assertEqual(requested.status_code, status.HTTP_201_CREATED)
        grant = JITElevatedAccessGrant.objects.get(pk=requested.data['grant']['id'])
        self.client.force_authenticate(user=MockUser(id=41, email='peer@shizuha.com'))
        approval = self.client.post(
            f'/api/jit-elevations/{grant.pk}/approve/',
            {'note': 'peer approve'},
            format='json',
        )
        self.assertEqual(approval.status_code, status.HTTP_200_OK)
        grant.refresh_from_db()
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_APPROVED)
        return grant

    def _consume(self, grant, idempotency_key='plat-6071-fleet-v1'):
        self.client.force_authenticate(user=MockUser(id=40, email='req@shizuha.com'))
        return self.client.post(
            f'/api/organizations/{self.org.slug}/teams/{self.merge.id}/members/',
            {
                'employee_profile_id': self.target_profile.id,
                'role': 'member',
                'jit_grant_id': grant.id,
                'jit_idempotency_key': idempotency_key,
            },
            format='json',
        )

    @patch('organizations.views.TeamViewSet._forward_fleet_roster_mutation')
    @patch('organizations.views.fleet_agent_write_denial')
    def test_fleet_consume_forwards_and_consumes_after_pulse_confirms(
        self, _fleet_denial, mock_forward,
    ):
        _fleet_denial.return_value = {
            'error': 'pulse_team_roster_authority',
            'detail': 'fleet agent',
            'email': 'target@shizuha.com',
        }
        pulse_receipt = {
            'command_id': '11111111-2222-3333-4444-555555555555',
            'action': 'add',
            'email': 'target@shizuha.com',
            'version': 7,
        }
        mock_forward.return_value = (pulse_receipt, None)

        grant = self._approved_grant()
        response = self._consume(grant)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['command_id'], pulse_receipt['command_id'])
        # Forward was called with the exact command contract.
        self.assertEqual(mock_forward.call_count, 1)
        _, kwargs = mock_forward.call_args
        self.assertEqual(kwargs['org'], self.org)
        self.assertEqual(kwargs['team_name'], 'Merge')
        self.assertEqual(kwargs['email'], 'target@shizuha.com')
        self.assertEqual(kwargs['idempotency_key'], 'plat-6071-fleet-v1')
        # Grant consumed exactly once.
        grant.refresh_from_db()
        self.assertEqual(grant.uses_consumed, 1)
        # No local Admin membership edge was created (Pulse owns the roster).
        self.assertFalse(TeamMembership.objects.filter(
            team=self.merge,
            employee_profile=self.target_profile,
            is_active=True,
        ).exists())

    @patch('organizations.views.TeamViewSet._forward_fleet_roster_mutation')
    @patch('organizations.views.fleet_agent_write_denial')
    def test_fleet_stale_version_409_does_not_consume_grant(
        self, _fleet_denial, mock_forward,
    ):
        from rest_framework.response import Response as DRFResponse
        _fleet_denial.return_value = {
            'error': 'pulse_team_roster_authority',
            'detail': 'fleet agent',
            'email': 'target@shizuha.com',
        }
        mock_forward.return_value = (
            None,
            DRFResponse(
                {'error': 'pulse_roster_version_conflict'},
                status=status.HTTP_409_CONFLICT,
            ),
        )

        grant = self._approved_grant()
        response = self._consume(grant)

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.data)
        self.assertEqual(response.data['error'], 'pulse_roster_version_conflict')
        # Grant left approved and unconsumed — no partial mutation.
        grant.refresh_from_db()
        self.assertEqual(grant.uses_consumed, 0)
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_APPROVED)
        self.assertIsNone(grant.revoked_at)
        self.assertFalse(TeamMembership.objects.filter(
            team=self.merge,
            employee_profile=self.target_profile,
            is_active=True,
        ).exists())

    @patch('organizations.views.TeamViewSet._forward_fleet_roster_mutation')
    @patch('organizations.views.fleet_agent_write_denial')
    def test_fleet_forward_unavailable_leaves_grant_approved(
        self, _fleet_denial, mock_forward,
    ):
        from rest_framework.response import Response as DRFResponse
        _fleet_denial.return_value = {
            'error': 'pulse_team_roster_authority',
            'detail': 'fleet agent',
            'email': 'target@shizuha.com',
        }
        mock_forward.return_value = (
            None,
            DRFResponse(
                {'error': 'pulse_team_roster_unavailable'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            ),
        )

        grant = self._approved_grant()
        response = self._consume(grant)

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        grant.refresh_from_db()
        self.assertEqual(grant.uses_consumed, 0)
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_APPROVED)

    @patch('organizations.views.TeamViewSet._forward_fleet_roster_mutation')
    @patch('organizations.views.fleet_agent_write_denial')
    def test_fleet_identity_unavailable_fails_closed_without_consuming(
        self, _fleet_denial, mock_forward,
    ):
        from organizations.services.team_roster_authority import FleetIdentityUnavailable
        _fleet_denial.side_effect = FleetIdentityUnavailable('identity unavailable')

        grant = self._approved_grant()
        response = self._consume(grant)

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data['error'], 'fleet_identity_unavailable')
        mock_forward.assert_not_called()
        grant.refresh_from_db()
        self.assertEqual(grant.uses_consumed, 0)
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_APPROVED)
