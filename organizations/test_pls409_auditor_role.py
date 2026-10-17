"""PLS-409: Tests for the auditor role grant endpoint and role assignment."""

from unittest.mock import patch

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from .models import MembershipChange, Organization, OrganizationMembership
from .tests import MockUser


class MembershipPatchAuditorRoleTests(TestCase):
    """Test the PATCH endpoint for granting the auditor role (PLS-409)."""

    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(
            name='Test Org',
            slug='test-org',
            owner_id=1,
        )
        # Owner membership
        OrganizationMembership.objects.create(
            organization=self.org,
            user_id=1,
            user_email='owner@test.com',
            role='owner',
            is_active=True,
            is_pending=False,
        )
        # Admin membership
        OrganizationMembership.objects.create(
            organization=self.org,
            user_id=2,
            user_email='admin@test.com',
            role='admin',
            is_active=True,
            is_pending=False,
        )
        # Plain member
        OrganizationMembership.objects.create(
            organization=self.org,
            user_id=3,
            user_email='member@test.com',
            role='member',
            is_active=True,
            is_pending=False,
        )
        # Target user (viewer, to be upgraded to auditor)
        OrganizationMembership.objects.create(
            organization=self.org,
            user_id=4,
            user_email='target@test.com',
            role='viewer',
            is_active=True,
            is_pending=False,
        )

    def _url(self, user_id=4):
        return f'/api/organizations/{self.org.slug}/members/{user_id}/auditor-role/'

    def test_owner_can_grant_auditor_role(self):
        """Org owner can grant the auditor role to another member."""
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        response = self.client.patch(self._url(), {'role': 'auditor'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['updated'])
        self.assertEqual(response.data['role'], 'auditor')
        # Verify DB
        membership = OrganizationMembership.objects.get(user_id=4, organization=self.org)
        self.assertEqual(membership.role, 'auditor')
        change = MembershipChange.objects.get(
            organization=self.org,
            target_user_id=4,
            action='role_changed',
        )
        self.assertEqual(change.target_user_email, 'target@test.com')
        self.assertEqual(change.actor_user_id, 1)
        self.assertEqual(change.actor_user_email, 'owner@test.com')
        self.assertEqual(change.previous_role, 'viewer')
        self.assertEqual(change.new_role, 'auditor')

    def test_admin_can_grant_auditor_role(self):
        """Org admin can grant the auditor role to another member."""
        self.client.force_authenticate(user=MockUser(id=2, email='admin@test.com'))
        response = self.client.patch(self._url(), {'role': 'auditor'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['updated'])
        membership = OrganizationMembership.objects.get(user_id=4, organization=self.org)
        self.assertEqual(membership.role, 'auditor')

    def test_plain_member_cannot_grant_auditor(self):
        """Plain member cannot grant the auditor role."""
        self.client.force_authenticate(user=MockUser(id=3, email='member@test.com'))
        response = self.client.patch(self._url(), {'role': 'auditor'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # Verify DB unchanged
        membership = OrganizationMembership.objects.get(user_id=4, organization=self.org)
        self.assertEqual(membership.role, 'viewer')

    def test_unauthenticated_cannot_grant_auditor(self):
        """Unauthenticated request is rejected."""
        response = self.client.patch(self._url(), {'role': 'auditor'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_cannot_grant_owner_role(self):
        """Cannot grant owner role through this endpoint."""
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        response = self.client.patch(self._url(), {'role': 'owner'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('Only auditor grants', response.data['error'])
        # Verify DB unchanged
        membership = OrganizationMembership.objects.get(user_id=4, organization=self.org)
        self.assertEqual(membership.role, 'viewer')

    def test_cannot_grant_admin_role(self):
        """Cannot grant admin role through this endpoint."""
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        response = self.client.patch(self._url(), {'role': 'admin'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        membership = OrganizationMembership.objects.get(user_id=4, organization=self.org)
        self.assertEqual(membership.role, 'viewer')

    def test_cannot_grant_member_role(self):
        """Cannot use the revoke operation to mutate a non-auditor."""
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        response = self.client.patch(self._url(), {'role': 'member'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_nonexistent_membership_returns_404(self):
        """PATCH for a non-existent membership returns 404."""
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        response = self.client.patch(
            self._url(999),
            {'role': 'auditor'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_auditor_role_appears_in_get_membership(self):
        """After granting auditor, the GET endpoint reflects the new role."""
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        self.client.patch(self._url(), {'role': 'auditor'}, format='json')
        # Verify via GET
        get_response = self.client.get(
            f'/api/internal/organizations/{self.org.id}/members/4/'
        )
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        self.assertEqual(get_response.data['role'], 'auditor')
        self.assertTrue(get_response.data['is_member'])

    def test_auditor_role_in_org_members_list(self):
        """After granting auditor, the member appears in the org members list."""
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        self.client.patch(self._url(), {'role': 'auditor'}, format='json')
        # Verify via org members list
        list_response = self.client.get(f'/api/internal/organizations/{self.org.id}/members/')
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        members = list_response.data['members']
        emails = [m['user_email'] for m in members]
        self.assertIn('target@test.com', emails)
        target = next(m for m in members if m['user_email'] == 'target@test.com')
        self.assertEqual(target['role'], 'auditor')

    def test_auditor_role_is_projected_by_internal_jwt_memberships_endpoint(self):
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        self.client.patch(self._url(), {'role': 'auditor'}, format='json')

        response = self.client.get(
            '/api/internal/users/4/memberships/',
            {'email': 'target@test.com'},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['memberships'][str(self.org.id)], 'auditor')

    def test_duplicate_membership_projection_prefers_auditor_over_member(self):
        OrganizationMembership.objects.create(
            organization=self.org,
            user_id=40,
            user_email='target@test.com',
            role='member',
            is_active=True,
            is_pending=False,
        )
        OrganizationMembership.objects.filter(
            organization=self.org, user_id=4,
        ).update(role='auditor')

        response = self.client.get(
            '/api/internal/users/4/memberships/',
            {'email': 'target@test.com'},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['memberships'][str(self.org.id)], 'auditor')

    def test_mismatched_email_rejected(self):
        """Supplying an email that does not match the path user_id is rejected."""
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        response = self.client.patch(
            self._url(),
            {'role': 'auditor', 'email': 'wrong@test.com'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Email does not match', response.data['error'])
        # Verify DB unchanged
        membership = OrganizationMembership.objects.get(user_id=4, organization=self.org)
        self.assertEqual(membership.role, 'viewer')

    def test_matching_email_succeeds(self):
        """Supplying the correct email for the path user_id succeeds."""
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        response = self.client.patch(
            self._url(),
            {'role': 'auditor', 'email': 'target@test.com'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        membership = OrganizationMembership.objects.get(user_id=4, organization=self.org)
        self.assertEqual(membership.role, 'auditor')

    def test_single_row_mutation_only(self):
        """Only the targeted membership is updated, not other members."""
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        self.client.patch(self._url(), {'role': 'auditor'}, format='json')
        # Target should be auditor
        target = OrganizationMembership.objects.get(user_id=4, organization=self.org)
        self.assertEqual(target.role, 'auditor')
        # Other members unchanged
        owner = OrganizationMembership.objects.get(user_id=1, organization=self.org)
        self.assertEqual(owner.role, 'owner')
        admin = OrganizationMembership.objects.get(user_id=2, organization=self.org)
        self.assertEqual(admin.role, 'admin')
        member = OrganizationMembership.objects.get(user_id=3, organization=self.org)
        self.assertEqual(member.role, 'member')

    def test_admin_cannot_demote_owner_to_auditor(self):
        self.client.force_authenticate(user=MockUser(id=2, email='admin@test.com'))
        response = self.client.patch(self._url(1), {'role': 'auditor'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        membership = OrganizationMembership.objects.get(user_id=1, organization=self.org)
        self.assertEqual(membership.role, 'owner')
        self.assertFalse(MembershipChange.objects.filter(
            organization=self.org, target_user_id=1, action='role_changed',
        ).exists())

    def test_owner_cannot_demote_admin_to_auditor(self):
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        response = self.client.patch(self._url(2), {'role': 'auditor'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        membership = OrganizationMembership.objects.get(user_id=2, organization=self.org)
        self.assertEqual(membership.role, 'admin')
        self.assertFalse(MembershipChange.objects.filter(
            organization=self.org, target_user_id=2, action='role_changed',
        ).exists())

    def test_actor_demoted_before_locked_authorization_cannot_grant(self):
        """Authorization uses the actor row as locked inside the transaction."""
        self.client.force_authenticate(user=MockUser(id=2, email='admin@test.com'))
        real_select_for_update = OrganizationMembership.objects.select_for_update
        demoted = False

        def demote_then_lock(*args, **kwargs):
            nonlocal demoted
            if not demoted:
                OrganizationMembership.objects.filter(
                    organization=self.org, user_id=2,
                ).update(role='member')
                demoted = True
            return real_select_for_update(*args, **kwargs)

        with patch.object(
            OrganizationMembership.objects,
            'select_for_update',
            side_effect=demote_then_lock,
        ):
            response = self.client.patch(self._url(), {'role': 'auditor'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        target = OrganizationMembership.objects.get(user_id=4, organization=self.org)
        self.assertEqual(target.role, 'viewer')
        self.assertFalse(MembershipChange.objects.filter(
            organization=self.org, target_user_id=4, action='role_changed',
        ).exists())

    def test_audit_failure_rolls_back_role_grant(self):
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        with patch('organizations.views.MembershipChange.objects.create', side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.client.patch(self._url(), {'role': 'auditor'}, format='json')
        membership = OrganizationMembership.objects.get(user_id=4, organization=self.org)
        self.assertEqual(membership.role, 'viewer')

    def test_identical_retry_is_idempotent(self):
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        first = self.client.patch(self._url(), {'role': 'auditor'}, format='json')
        second = self.client.patch(self._url(), {'role': 'auditor'}, format='json')
        self.assertTrue(first.data['updated'])
        self.assertFalse(second.data['updated'])
        self.assertEqual(MembershipChange.objects.filter(
            organization=self.org, target_user_id=4, action='role_changed',
        ).count(), 1)

    def test_owner_can_revoke_auditor_to_safe_prior_role(self):
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        self.client.patch(self._url(), {'role': 'auditor'}, format='json')
        before = OrganizationMembership.objects.get(
            organization=self.org, user_id=4,
        ).updated_at

        response = self.client.patch(self._url(), {'role': 'viewer'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['updated'])
        membership = OrganizationMembership.objects.get(organization=self.org, user_id=4)
        self.assertEqual(membership.role, 'viewer')
        self.assertGreater(membership.updated_at, before)
        change = MembershipChange.objects.get(
            organization=self.org,
            target_user_id=4,
            previous_role='auditor',
            new_role='viewer',
        )
        self.assertEqual(change.actor_user_id, 1)

    def test_admin_can_revoke_auditor_to_member(self):
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        self.client.patch(self._url(), {'role': 'auditor'}, format='json')
        self.client.force_authenticate(user=MockUser(id=2, email='admin@test.com'))

        response = self.client.patch(self._url(), {'role': 'member'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        membership = OrganizationMembership.objects.get(organization=self.org, user_id=4)
        self.assertEqual(membership.role, 'member')

    def test_plain_member_cannot_revoke_auditor(self):
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        self.client.patch(self._url(), {'role': 'auditor'}, format='json')
        self.client.force_authenticate(user=MockUser(id=3, email='member@test.com'))

        response = self.client.patch(self._url(), {'role': 'viewer'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        membership = OrganizationMembership.objects.get(organization=self.org, user_id=4)
        self.assertEqual(membership.role, 'auditor')

    def test_identical_revoke_retry_is_idempotent(self):
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        self.client.patch(self._url(), {'role': 'auditor'}, format='json')
        first = self.client.patch(self._url(), {'role': 'member'}, format='json')
        second = self.client.patch(self._url(), {'role': 'member'}, format='json')

        self.assertTrue(first.data['updated'])
        self.assertFalse(second.data['updated'])
        self.assertEqual(MembershipChange.objects.filter(
            organization=self.org,
            target_user_id=4,
            previous_role='auditor',
            new_role='member',
        ).count(), 1)

    def test_audit_failure_rolls_back_auditor_revoke(self):
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        self.client.patch(self._url(), {'role': 'auditor'}, format='json')
        with patch(
            'organizations.views.MembershipChange.objects.create',
            side_effect=RuntimeError('audit unavailable'),
        ):
            with self.assertRaises(RuntimeError):
                self.client.patch(self._url(), {'role': 'viewer'}, format='json')
        membership = OrganizationMembership.objects.get(organization=self.org, user_id=4)
        self.assertEqual(membership.role, 'auditor')

    def test_inactive_organization_rejects_role_mutation(self):
        Organization.objects.filter(pk=self.org.pk).update(is_active=False)
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))

        response = self.client.patch(self._url(), {'role': 'auditor'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        membership = OrganizationMembership.objects.get(organization=self.org, user_id=4)
        self.assertEqual(membership.role, 'viewer')

    def test_organization_deactivated_before_locked_lookup_cannot_grant(self):
        """Authorization resolves active state from the locked org row."""
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))
        real_select_for_update = Organization.objects.select_for_update
        deactivated = False

        def deactivate_then_lock(*args, **kwargs):
            nonlocal deactivated
            if not deactivated:
                Organization.objects.filter(pk=self.org.pk).update(is_active=False)
                deactivated = True
            return real_select_for_update(*args, **kwargs)

        with patch.object(
            Organization.objects,
            'select_for_update',
            side_effect=deactivate_then_lock,
        ):
            response = self.client.patch(self._url(), {'role': 'auditor'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        membership = OrganizationMembership.objects.get(organization=self.org, user_id=4)
        self.assertEqual(membership.role, 'viewer')
        self.assertFalse(MembershipChange.objects.filter(
            organization=self.org, target_user_id=4, action='role_changed',
        ).exists())

    def test_pending_target_cannot_receive_auditor_role(self):
        OrganizationMembership.objects.filter(
            organization=self.org, user_id=4,
        ).update(is_pending=True)
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))

        response = self.client.patch(self._url(), {'role': 'auditor'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        membership = OrganizationMembership.objects.get(organization=self.org, user_id=4)
        self.assertEqual(membership.role, 'viewer')
        self.assertFalse(MembershipChange.objects.filter(
            organization=self.org, target_user_id=4, action='role_changed',
        ).exists())

    def test_pending_actor_cannot_grant_auditor_role(self):
        OrganizationMembership.objects.filter(
            organization=self.org, user_id=2,
        ).update(is_pending=True)
        self.client.force_authenticate(user=MockUser(id=2, email='admin@test.com'))

        response = self.client.patch(self._url(), {'role': 'auditor'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        membership = OrganizationMembership.objects.get(organization=self.org, user_id=4)
        self.assertEqual(membership.role, 'viewer')
        self.assertFalse(MembershipChange.objects.filter(
            organization=self.org, target_user_id=4, action='role_changed',
        ).exists())

    def test_generic_invite_path_rejects_auditor_role(self):
        self.client.force_authenticate(user=MockUser(id=1, email='owner@test.com'))

        response = self.client.post(
            f'/api/organizations/{self.org.slug}/members/',
            {'user_email': 'invitee@test.com', 'role': 'auditor'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(OrganizationMembership.objects.filter(
            organization=self.org, user_email='invitee@test.com',
        ).exists())
