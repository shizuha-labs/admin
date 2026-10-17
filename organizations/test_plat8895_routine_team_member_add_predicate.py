"""PLAT-8895: durable policy-predicate fix for routine target-constrained
org.teams.members.add JIT requests — stop the lane stranding on one inactive
member.

PLS-1165 andon need (c). The resolver derives ALL JIT approvals for routine
target-constrained `org.teams.members.add` requests to approver team
Platform/admin-platform, whose one routing-capable member reads inactive —
every pending grant strands on one inactive member (sole-approver SPOF ×
availability-map desync). The ruled fix (PLAT-1346 tier): a trusted internal
policy predicate — verified fail-closed by the Admin service (actor/policy
verification) — so the lane stops stranding.

These tests pin the enforced contract:
  - AUTO-APPROVE: staff actor + allowlisted predicate slug + the admission
    adapter's validated exact target constraints + ttl within the scope
    policy's ceiling → grant approved via APPROVAL_POLICY, no owning-team
    pending request.
  - FAIL-CLOSED legs: non-staff actor, wrong slug, missing exact-target
    proof, ttl over the scope policy ceiling, and absence of the predicate
    (no slug) — each lands pending (today's behavior byte-for-byte).
  - ORG-LEVEL path unchanged: 'org.members.add' + the existing slug behaves
    byte-identically; the kubernetes.rbac.apply scope never auto-approves.
"""
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from .models import (
    EmployeeProfile,
    JITElevatedAccessGrant,
    Organization,
    OrganizationMembership,
    Team,
    TeamMembership,
)
from .tests import MockUser


class Plat8895RoutineTeamMemberAddPredicateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(
            name='Predicate Corp',
            slug='predicate-corp',
            owner_id=1,
        )
        # routing-capable members of the org (requester + staff actor)
        OrganizationMembership.objects.create(
            organization=self.org,
            user_id=3,
            user_email='agent@predicate.com',
            role='member',
            is_pending=False,
        )
        OrganizationMembership.objects.create(
            organization=self.org,
            user_id=10,
            user_email='staff@predicate.com',
            role='member',
            is_pending=False,
        )
        # the target roster user (active employee)
        OrganizationMembership.objects.create(
            organization=self.org,
            user_id=13,
            user_email='nova@predicate.com',
            role='member',
            is_pending=False,
        )
        self.platform = Team.objects.create(
            organization=self.org,
            name='Platform',
        )
        self.merge = Team.objects.create(organization=self.org, name='Merge')
        staff_profile = EmployeeProfile.objects.get(
            membership__user_id=10, membership__organization=self.org)
        nova_profile = EmployeeProfile.objects.get(
            membership__user_id=13, membership__organization=self.org)
        TeamMembership.objects.create(
            team=self.platform, employee_profile=staff_profile, role='lead')
        # nova is NOT yet on Merge — the grant adds her there.

    def _auth(self, user_id=3, email='agent@predicate.com', is_staff=False):
        self.client.force_authenticate(
            user=MockUser(id=user_id, email=email, is_staff=is_staff))

    def _payload(self, **overrides):
        data = {
            'org_slug': self.org.slug,
            'scope': JITElevatedAccessGrant.TEAM_MEMBER_ADD_SCOPE,
            'requested_role': 'admin',
            'reason': 'ORIG-120 exact merge-roster recovery (routine)',
            'task_key': 'PLAT-8895',
            'ttl_seconds': 900,
            'owning_team': 'admin-platform',
            'target_team_id': self.merge.id,
            'target_user_id': 13,
            'target_role': 'member',
            'policy_slug': 'routine-target-constrained-team-member-add',
        }
        data.update(overrides)
        return {key: value for key, value in data.items() if value is not None}

    def test_predicate_auto_approves_routine_target_constrained_request(self):
        """The ruled discharge: staff actor + allowlisted slug + validated exact
        target → approved via APPROVAL_POLICY. No owning-team pending request."""
        self._auth(user_id=10, email='staff@predicate.com', is_staff=True)
        resp = self.client.post('/api/jit-elevations/', self._payload(), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertTrue(resp.data.get('auto_approved'), resp.data)
        grant = JITElevatedAccessGrant.objects.get(pk=resp.data['grant']['id'])
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_APPROVED)
        self.assertEqual(
            grant.approval_path, JITElevatedAccessGrant.APPROVAL_POLICY)
        self.assertEqual(grant.target_team, self.merge)
        self.assertEqual(grant.target_user_id, 13)
        self.assertEqual(grant.target_role, 'member')
        self.assertTrue(grant.has_complete_current_exact_authority())
        self.assertIsNotNone(grant.expires_at)

    def test_non_staff_actor_fails_closed_to_pending(self):
        """A non-staff requester asserting the predicate lands pending — the
        actor leg is Admin-verified, not caller-asserted."""
        self._auth(user_id=3, email='agent@predicate.com', is_staff=False)
        resp = self.client.post('/api/jit-elevations/', self._payload(), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertFalse(resp.data.get('auto_approved'), resp.data)
        grant = JITElevatedAccessGrant.objects.get(pk=resp.data['grant']['id'])
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_PENDING)
        self.assertEqual(
            grant.approval_path, JITElevatedAccessGrant.APPROVAL_TEAM)

    def test_wrong_slug_fails_closed_to_pending(self):
        """A staff actor with an unallowlisted slug lands pending — the policy
        leg is the code-reviewed allowlist, not caller vocabulary."""
        self._auth(user_id=10, email='staff@predicate.com', is_staff=True)
        resp = self.client.post('/api/jit-elevations/', self._payload(
            policy_slug='blanket-team-member-add'), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertFalse(resp.data.get('auto_approved'), resp.data)
        grant = JITElevatedAccessGrant.objects.get(pk=resp.data['grant']['id'])
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_PENDING)

    def test_ttl_over_scope_policy_ceiling_is_rejected_at_admission(self):
        """The scope policy's 1h ceiling binds the predicate leg — ttl above it
        is rejected at admission (400), not silently downgraded."""
        self._auth(user_id=10, email='staff@predicate.com', is_staff=True)
        resp = self.client.post('/api/jit-elevations/', self._payload(
            ttl_seconds=3601), format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)

    def test_absence_of_predicate_preserves_pending_byte_for_byte(self):
        """No slug → today's behavior byte-for-byte: pending on the owning
        team (the stranding class the predicate exists to end for future
        grants — this leg proves the mechanism is purely additive)."""
        self._auth(user_id=3, email='agent@predicate.com', is_staff=False)
        payload = self._payload()
        payload.pop('policy_slug')
        resp = self.client.post('/api/jit-elevations/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertFalse(resp.data.get('auto_approved'), resp.data)
        grant = JITElevatedAccessGrant.objects.get(pk=resp.data['grant']['id'])
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_PENDING)
        self.assertEqual(
            grant.approval_path, JITElevatedAccessGrant.APPROVAL_TEAM)
        self.assertEqual(grant.owning_team, 'Platform')

    def test_model_level_missing_exact_target_proof_fails_closed(self):
        """Model contract: can_auto_approve with has_exact_constraints=False
        (the proof the admission adapter produces) is False even with a staff
        actor and the allowlisted slug — the exact-target proof is not
        optional."""
        self.assertFalse(JITElevatedAccessGrant.can_auto_approve(
            scope=JITElevatedAccessGrant.TEAM_MEMBER_ADD_SCOPE,
            requested_role='admin',
            ttl_seconds=900,
            policy_slug='routine-target-constrained-team-member-add',
            policy_verified=True,
            has_exact_constraints=False,
        ))

    def test_org_level_low_risk_path_unchanged(self):
        """Byte-identical org-level behavior: the existing slug + staff actor
        auto-approves org.members.add; a non-staff actor lands pending."""
        self._auth(user_id=10, email='staff@predicate.com', is_staff=True)
        resp = self.client.post('/api/jit-elevations/', {
            'org_slug': self.org.slug,
            'scope': 'org.members.add',
            'requested_role': 'admin',
            'reason': 'org-level positive control (unchanged)',
            'task_key': 'PLAT-8895',
            'ttl_seconds': 1800,
            'policy_slug': 'passed-it-audit-org-member-add',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertTrue(resp.data.get('auto_approved'), resp.data)
        grant = JITElevatedAccessGrant.objects.get(pk=resp.data['grant']['id'])
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_APPROVED)
        self.assertEqual(
            grant.approval_path, JITElevatedAccessGrant.APPROVAL_POLICY)

    def test_kubernetes_rbac_apply_scope_never_auto_approves(self):
        """kubernetes.rbac.apply stays outside every predicate path — the
        fallback leg requires scope in LOW_RISK_AUTO_SCOPES, which excludes
        it; the target-constrained leg matches only org.teams.members.add."""
        self.assertFalse(JITElevatedAccessGrant.can_auto_approve(
            scope=JITElevatedAccessGrant.KUBERNETES_RBAC_APPLY_SCOPE,
            requested_role='admin',
            ttl_seconds=900,
            policy_slug='routine-target-constrained-team-member-add',
            policy_verified=True,
            has_exact_constraints=True,
        ))
