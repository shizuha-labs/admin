"""HIVE-671 P1 #2 — admin production-order suite on REAL PostgreSQL + REAL signed auth.

Reviewer P1 #2 (revi/ichi): the admin HIVE-671 modules are SimpleTestCase that
patch ``HiveSignedInternalPermission.has_permission=True`` and mock the managers,
so premerge never exercised the real signed envelope or the real membership DB
effects. This suite drives the ACTUAL signed endpoints (personal-agent membership
create → provenance-scoped revoke) through the Django test client against a real
PG database (TransactionTestCase) with the REAL ``HiveSignedInternalPermission``
(no auth mock): real X-Hive-* signature, real single-use nonce cache, real
`operation_id`-bound-in-signed-body provenance, and real `OrganizationMembership`
row effects.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

from django.core.cache import cache
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from organizations.models import Organization, OrganizationMembership, MembershipChange
from organizations.signals import set_membership_audit_actor, clear_membership_audit_actor


ADMIN_TOKEN = "admin-hive-svc-token"
ORG_OWNER = 5001
AGENT_UID = 10_600_001


def _wire(body):
    return json.dumps(body or {}, sort_keys=True, separators=(",", ":")).encode()


def _sign(method, path, body, token, ts=None, nonce="adm-nonce-1"):
    ts = str(ts or int(time.time()))
    body_sha = hashlib.sha256(_wire(body)).hexdigest()
    signing_input = "\n".join([method.upper(), path, ts, nonce, body_sha])
    sig = hmac.new(token.encode(), signing_input.encode(), hashlib.sha256).hexdigest()
    return {
        "HTTP_X_INTERNAL_SERVICE": "shizuha-hive",
        "HTTP_X_INTERNAL_SERVICE_TOKEN": token,
        "HTTP_X_HIVE_TIMESTAMP": ts,
        "HTTP_X_HIVE_NONCE": nonce,
        "HTTP_X_HIVE_BODY_SHA256": body_sha,
        "HTTP_X_HIVE_SIGNATURE": sig,
    }


@override_settings(ADMIN_INTERNAL_SERVICE_TOKEN=ADMIN_TOKEN)
class Hive671MembershipSignedLifecyclePGTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        cache.clear()
        self._n = 0
        self.org = Organization.objects.create(
            name="Owner Personal", slug=f"personal-{ORG_OWNER}", owner_id=ORG_OWNER,
        )

    def _nonce(self):
        self._n += 1
        return f"adm-nonce-{self._n:04d}"

    def _members_url(self):
        return reverse("internal-org-members", args=[self.org.id])

    def _member_url(self, uid):
        return reverse("internal-org-membership-check", args=[self.org.id, uid])

    def _create(self, uid=AGENT_UID, op="op-mem-1", role="member", nonce=None, token=ADMIN_TOKEN):
        body = {"user_id": uid, "role": role, "operation_id": op}
        path = self._members_url()
        headers = _sign("POST", path, body, token, nonce=nonce or self._nonce())
        return self.client.post(path, data=_wire(body), content_type="application/json", **headers)

    def _revoke(self, uid=AGENT_UID, op="op-mem-1", nonce=None, token=ADMIN_TOKEN):
        body = {"operation_id": op}
        path = self._member_url(uid)
        headers = _sign("DELETE", path, body, token, nonce=nonce or self._nonce())
        return self.client.delete(path, data=_wire(body), content_type="application/json", **headers)

    def test_signed_create_makes_exactly_one_active_membership(self):
        r = self._create()
        self.assertEqual(r.status_code, 201, r.content)
        rows = OrganizationMembership.objects.filter(organization=self.org, user_id=AGENT_UID)
        self.assertEqual(rows.count(), 1)
        m = rows.get()
        self.assertTrue(m.is_active)
        self.assertEqual(m.source_operation_id, "op-mem-1")
        # Idempotent same-operation create — still exactly one row, no duplicate.
        r2 = self._create()
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(
            OrganizationMembership.objects.filter(organization=self.org, user_id=AGENT_UID).count(), 1)

    def test_provenance_scoped_revoke(self):
        self.assertEqual(self._create().status_code, 201)
        # Wrong operation_id must NOT revoke a foreign/unmatched-provenance membership.
        r_bad = self._revoke(op="op-WRONG")
        self.assertEqual(r_bad.status_code, 403, r_bad.content)
        self.assertEqual(r_bad.json().get("code"), "membership_not_hive_owned")
        self.assertTrue(
            OrganizationMembership.objects.get(organization=self.org, user_id=AGENT_UID).is_active)
        # Matching operation_id revokes exactly that membership.
        r_ok = self._revoke(op="op-mem-1")
        self.assertEqual(r_ok.status_code, 200, r_ok.content)
        self.assertEqual(r_ok.json().get("status"), "revoked")
        self.assertFalse(
            OrganizationMembership.objects.get(organization=self.org, user_id=AGENT_UID).is_active)

    def test_revoke_absent_is_idempotent(self):
        r = self._revoke(uid=999999, op="op-any")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json().get("status"), "absent")

    def test_inactive_membership_not_silently_reactivated(self):
        self.assertEqual(self._create(op="op-A").status_code, 201)
        self.assertEqual(self._revoke(op="op-A").status_code, 200)
        # A NEW operation must not reopen the withdrawn row.
        r_new = self._create(op="op-B")
        self.assertEqual(r_new.status_code, 409, r_new.content)
        self.assertEqual(r_new.json().get("code"), "membership_inactive_conflict")
        self.assertFalse(
            OrganizationMembership.objects.get(organization=self.org, user_id=AGENT_UID).is_active)
        # The exact same original operation is idempotent success (no reopen).
        r_same = self._create(op="op-A")
        self.assertEqual(r_same.status_code, 200, r_same.content)
        self.assertTrue(r_same.json().get("already_applied"))

    def test_unsigned_revoke_denied_real_permission(self):
        # No auth mock: the real HiveSignedInternalPermission must reject.
        self.assertEqual(self._create().status_code, 201)
        path = self._member_url(AGENT_UID)
        r = self.client.delete(path, data=_wire({"operation_id": "op-mem-1"}),
                               content_type="application/json")
        self.assertIn(r.status_code, (401, 403), r.content)
        self.assertTrue(
            OrganizationMembership.objects.get(organization=self.org, user_id=AGENT_UID).is_active)

    def test_bad_signature_denied(self):
        self.assertEqual(self._create().status_code, 201)
        path = self._member_url(AGENT_UID)
        headers = _sign("DELETE", path, {"operation_id": "op-mem-1"}, "WRONG-TOKEN", nonce=self._nonce())
        r = self.client.delete(path, data=_wire({"operation_id": "op-mem-1"}),
                               content_type="application/json", **headers)
        self.assertIn(r.status_code, (401, 403), r.content)

    def test_nonce_single_use_replay_denied(self):
        # First signed create consumes the nonce; identical replay is rejected.
        r1 = self._create(op="op-mem-1", nonce="adm-fixed-nonce")
        self.assertEqual(r1.status_code, 201, r1.content)
        r2 = self._create(op="op-mem-1", nonce="adm-fixed-nonce")
        self.assertIn(r2.status_code, (401, 403), r2.content)


@override_settings(ADMIN_INTERNAL_SERVICE_TOKEN=ADMIN_TOKEN)
class OrganizationCascadeAuditPGTests(TransactionTestCase):
    """Real signed create→delete→COMMIT, plus surviving-org audit controls.

    TransactionTestCase is essential: the production failure is PostgreSQL's
    deferred FK check at COMMIT, after post_delete creates a fresh audit row.
    A TestCase savepoint can hide that failure until unrelated test cleanup.
    """

    def setUp(self):
        self.assertEqual(connection.vendor, 'postgresql')
        cache.clear()
        clear_membership_audit_actor()
        self.addCleanup(clear_membership_audit_actor)
        self.addCleanup(cache.clear)
        self._n = 0

    def _post(self, path, body):
        self._n += 1
        return self.client.post(
            path, data=_wire(body), content_type='application/json',
            **_sign('POST', path, body, ADMIN_TOKEN,
                    nonce=f'cascade-audit-{self._n}'),
        )

    def _create_org(self, suffix):
        response = self._post(reverse('internal-org-create'), {
            'name': f'Cascade {suffix}', 'slug': f'cascade-{suffix}',
            'owner_id': ORG_OWNER, 'owner_email': 'owner@qafixture.shizuha.com',
            'operation_id': f'cascade:{suffix}:create',
        })
        self.assertEqual(response.status_code, 201, response.content)
        return Organization.objects.get(pk=response.json()['id'])

    def test_signed_saga_delete_commits_across_two_cycles(self):
        for suffix in ('first', 'second'):
            org = self._create_org(suffix)
            org_id = org.pk
            self.assertTrue(MembershipChange.objects.filter(organization=org).exists())
            response = self._post(reverse('internal-org-delete', args=[org_id]), {
                'operation_id': f'cascade:{suffix}:delete',
            })
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()['status'], 'deleted')
            self.assertTrue(connection.get_autocommit())
            self.assertFalse(Organization.objects.filter(pk=org_id).exists())
            self.assertFalse(OrganizationMembership.objects.filter(organization_id=org_id).exists())
            self.assertFalse(MembershipChange.objects.filter(organization_id=org_id).exists())

    def test_queryset_org_cascade_commits_without_touching_other_org_audit(self):
        removed = [self._create_org(suffix).pk for suffix in ('bulk-a', 'bulk-b')]
        kept = self._create_org('kept')
        kept_audit = list(MembershipChange.objects.filter(organization=kept).values())
        Organization.objects.filter(pk__in=removed).delete()
        self.assertTrue(connection.get_autocommit())
        self.assertFalse(Organization.objects.filter(pk__in=removed).exists())
        self.assertFalse(MembershipChange.objects.filter(organization_id__in=removed).exists())
        self.assertEqual(list(MembershipChange.objects.filter(organization=kept).values()), kept_audit)
        self.assertTrue(OrganizationMembership.objects.filter(organization=kept).exists())

    def test_member_instance_and_queryset_deletes_keep_tombstones(self):
        org = self._create_org('membership-only')
        set_membership_audit_actor(ORG_OWNER, 'owner@qafixture.shizuha.com', 'api')
        for offset, bulk in enumerate((False, True), start=1):
            member = OrganizationMembership.objects.create(
                organization=org, user_id=ORG_OWNER + offset,
                user_email=f'member{offset}@qafixture.shizuha.com',
                role='member', is_active=True, is_pending=False,
            )
            uid, email = member.user_id, member.user_email
            if bulk:
                OrganizationMembership.objects.filter(pk=member.pk).delete()
            else:
                member.delete()
            self.assertTrue(connection.get_autocommit())
            tombstone = MembershipChange.objects.get(
                organization=org, target_user_id=uid, action='deleted',
            )
            self.assertEqual(tombstone.target_user_email, email)
            self.assertEqual(tombstone.previous_role, 'member')
            self.assertIsNone(tombstone.new_role)
            self.assertEqual(tombstone.actor_user_id, ORG_OWNER)
            self.assertEqual(tombstone.actor_source, 'api')
        self.assertTrue(Organization.objects.filter(pk=org.pk).exists())
        self.assertEqual(MembershipChange.objects.filter(organization=org, action='deleted').count(), 2)

    def test_unsigned_delete_still_refuses_and_retains_org(self):
        org = self._create_org('unsigned')
        response = self.client.post(reverse('internal-org-delete', args=[org.pk]),
                                    data=_wire({'operation_id': 'unsigned'}),
                                    content_type='application/json')
        self.assertIn(response.status_code, (401, 403), response.content)
        self.assertTrue(Organization.objects.filter(pk=org.pk).exists())

    def test_delete_with_additional_active_member_still_refuses(self):
        org = self._create_org('active-member')
        OrganizationMembership.objects.create(
            organization=org, user_id=ORG_OWNER + 1,
            user_email='active@qafixture.shizuha.com', role='member',
            is_active=True, is_pending=False,
        )
        response = self._post(reverse('internal-org-delete', args=[org.pk]),
                              {'operation_id': 'must-not-delete'})
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(OrganizationMembership.objects.filter(organization=org).count(), 2)
