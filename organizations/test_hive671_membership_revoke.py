"""HIVE-671: Admin membership POST/DELETE Hive-signed + provenance-scoped."""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory

from organizations.internal_urls import InternalOrgMembershipCheckView, InternalOrgMembersView


@override_settings(ADMIN_INTERNAL_SERVICE_TOKEN="tok")
class MembershipRevokeProvenanceTests(SimpleTestCase):
    def setUp(self):
        self.rf = APIRequestFactory()

    def _delete(self, org_id, user_id, operation_id, membership):
        req = self.rf.delete(
            f"/api/internal/organizations/{org_id}/members/{user_id}/",
            data={"operation_id": operation_id},
            format="json",
            HTTP_X_INTERNAL_SERVICE="shizuha-hive",
            HTTP_X_INTERNAL_SERVICE_TOKEN="tok",
            HTTP_X_HIVE_OPERATION_ID=operation_id,
        )
        with patch(
            "organizations.internal_urls.HiveSignedInternalPermission.has_permission",
            return_value=True,
        ), patch(
            "organizations.internal_urls.OrganizationMembership.objects"
        ) as objs:
            objs.filter.return_value.first.return_value = membership
            return InternalOrgMembershipCheckView.as_view()(
                req, org_id=org_id, user_id=user_id
            )

    def test_delete_requires_matching_operation_id(self):
        m = MagicMock(is_active=True, source_operation_id="op-hive-1")
        resp = self._delete(7, 74, "op-hive-1", m)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data.get("status"), "revoked")
        m.save.assert_called()

    def test_delete_rejects_foreign_membership(self):
        m = MagicMock(is_active=True, source_operation_id="other-op")
        resp = self._delete(7, 74, "op-hive-1", m)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data.get("code"), "membership_not_hive_owned")
        m.save.assert_not_called()

    def test_delete_absent_is_idempotent(self):
        resp = self._delete(7, 74, "op-hive-1", None)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data.get("already_revoked"))

    def test_delete_without_signed_permission_denied(self):
        req = self.rf.delete(
            "/api/internal/organizations/7/members/74/",
            HTTP_X_INTERNAL_SERVICE="other-svc",
            HTTP_X_INTERNAL_SERVICE_TOKEN="tok",
        )
        with patch(
            "organizations.internal_urls.HiveSignedInternalPermission.has_permission",
            return_value=False,
        ):
            resp = InternalOrgMembershipCheckView.as_view()(req, org_id=7, user_id=74)
        self.assertIn(resp.status_code, (401, 403))


@override_settings(ADMIN_INTERNAL_SERVICE_TOKEN="tok")
class MembershipCreateInactiveConflictTests(SimpleTestCase):
    def setUp(self):
        self.rf = APIRequestFactory()

    def test_inactive_membership_conflict_not_reactivated(self):
        org = MagicMock(id=7, is_active=True)
        membership = MagicMock(is_active=False, role="member", source_operation_id="old-op")
        req = self.rf.post(
            "/api/internal/organizations/7/members/",
            data={"user_id": 74, "operation_id": "new-op"},
            format="json",
            HTTP_X_INTERNAL_SERVICE="shizuha-hive",
            HTTP_X_INTERNAL_SERVICE_TOKEN="tok",
        )
        with patch(
            "organizations.internal_urls.HiveSignedInternalPermission.has_permission",
            return_value=True,
        ), patch(
            "organizations.internal_urls.Organization.objects"
        ) as orgs, patch(
            "organizations.internal_urls.OrganizationMembership.objects"
        ) as mems:
            orgs.get.return_value = org
            mems.get_or_create.return_value = (membership, False)
            resp = InternalOrgMembersView.as_view()(req, org_id=7)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data.get("code"), "membership_inactive_conflict")
        membership.save.assert_not_called()

    def test_same_operation_inactive_is_idempotent(self):
        org = MagicMock(id=7, is_active=True)
        membership = MagicMock(is_active=False, role="member", source_operation_id="same-op")
        req = self.rf.post(
            "/api/internal/organizations/7/members/",
            data={"user_id": 74, "operation_id": "same-op"},
            format="json",
            HTTP_X_INTERNAL_SERVICE="shizuha-hive",
            HTTP_X_INTERNAL_SERVICE_TOKEN="tok",
        )
        with patch(
            "organizations.internal_urls.HiveSignedInternalPermission.has_permission",
            return_value=True,
        ), patch(
            "organizations.internal_urls.Organization.objects"
        ) as orgs, patch(
            "organizations.internal_urls.OrganizationMembership.objects"
        ) as mems:
            orgs.get.return_value = org
            mems.get_or_create.return_value = (membership, False)
            resp = InternalOrgMembersView.as_view()(req, org_id=7)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data.get("already_applied"))
        membership.save.assert_not_called()
