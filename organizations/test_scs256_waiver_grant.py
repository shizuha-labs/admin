"""SCS-256: standing waiver-issuance grants.

An owner can grant a named seat the deploy-verify waiver type. A member
cannot. A revoked grant is no longer active. Receipts already minted are
not touched by revocation.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Organization, OrganizationMembership, WaiverIssuanceGrant


class WaiverIssuanceGrantTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Acme', slug='acme-256', owner_id=1)
        self.owner = User.objects.create_user('owner256', email='owner@shizuha.com', password='x')
        self.member = User.objects.create_user('member256', email='member@shizuha.com', password='x')
        OrganizationMembership.objects.create(
            organization=self.org, user_id=self.owner.id, user_email=self.owner.email,
            role='owner', is_active=True,
        )
        OrganizationMembership.objects.create(
            organization=self.org, user_id=self.member.id, user_email=self.member.email,
            role='member', is_active=True,
        )
        self.client = APIClient()

    def test_owner_issues_and_member_is_refused(self):
        self.client.force_authenticate(self.member)
        refused = self.client.post('/api/waiver-grants/', {
            'organization_id': self.org.id,
            'subject_email': 'seat@shizuha.com',
            'subject_user_id': 42,
        }, format='json')
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(refused.json()['code'], 'waiver_grant_forbidden')
        self.assertEqual(WaiverIssuanceGrant.objects.count(), 0)

        self.client.force_authenticate(self.owner)
        issued = self.client.post('/api/waiver-grants/', {
            'organization_id': self.org.id,
            'subject_email': 'Seat@shizuha.com',
            'subject_user_id': 42,
        }, format='json')
        self.assertEqual(issued.status_code, 201, issued.content)
        grant = WaiverIssuanceGrant.objects.get()
        self.assertEqual(grant.subject_email, 'seat@shizuha.com')
        self.assertEqual(grant.waiver_type, 'receipt.deploy_verify_waiver')
        self.assertTrue(grant.is_active(timezone.now()))
        self.assertEqual(issued.json()['grant_id'], grant.id)

    def test_revoked_grant_is_inactive_and_row_remains(self):
        self.client.force_authenticate(self.owner)
        issued = self.client.post('/api/waiver-grants/', {
            'organization_id': self.org.id,
            'subject_email': 'seat@shizuha.com',
            'subject_user_id': 42,
        }, format='json')
        grant_id = issued.json()['grant_id']
        revoked = self.client.post(f'/api/waiver-grants/{grant_id}/revoke/', {}, format='json')
        self.assertEqual(revoked.status_code, 200)
        grant = WaiverIssuanceGrant.objects.get(pk=grant_id)
        self.assertFalse(grant.is_active(timezone.now()))
        self.assertIsNotNone(grant.revoked_at)
