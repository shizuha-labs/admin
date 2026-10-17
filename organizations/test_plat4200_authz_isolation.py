"""PLAT-4200 deny-by-default invariants for Admin's authority boundary.

Admin is the source of truth for organization membership and role claims.  The
tests in this module deliberately exercise the HTTP routes (rather than only
permission helpers) so a router, queryset, action, or middleware regression
cannot silently expose another tenant.
"""

import re
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import resolve
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from organizations.internal_urls import urlpatterns as internal_urlpatterns
from organizations.models import (
    Department,
    EmployeeProfile,
    JITElevatedAccessGrant,
    MembershipChange,
    Organization,
    OrganizationMembership,
    OrganizationServiceAccess,
    Position,
    Team,
    TeamMembership,
)


def _user(user_id, email, *, is_staff=False, is_superuser=False):
    """Federated-user shaped principal without a shizuha-id dependency."""
    return SimpleNamespace(
        id=user_id,
        pk=user_id,
        email=email,
        username=email.split("@", 1)[0],
        first_name="",
        last_name="",
        is_staff=is_staff,
        is_superuser=is_superuser,
        is_active=True,
        is_authenticated=True,
        is_anonymous=False,
        enabled_services=None,
    )


class _OfflineResponse:
    """Deterministic upstream response for code paths that fail soft."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    @staticmethod
    def json():
        return {}


class OrganizationIsolationFixture(TestCase):
    """Two real tenants plus principals with deliberately disjoint access."""

    maxDiff = None

    def setUp(self):
        self.client = APIClient()

        self.owner_a = _user(101, "owner-a@plat4200.test")
        self.admin_a = _user(102, "admin-a@plat4200.test")
        self.member_a = _user(103, "member-a@plat4200.test")
        self.owner_b = _user(201, "owner-b@plat4200.test")
        self.member_b = _user(202, "private-member-b@plat4200.test")

        self.org_a = Organization.objects.create(
            name="PLAT4200 Tenant A",
            slug="plat4200-tenant-a",
            owner_id=self.owner_a.id,
        )
        self.org_b = Organization.objects.create(
            name="PLAT4200 PRIVATE Tenant B",
            slug="plat4200-tenant-b",
            description="PLAT4200-PRIVATE-ORG-DESCRIPTION",
            owner_id=self.owner_b.id,
        )

        self.owner_a_membership = OrganizationMembership.objects.create(
            organization=self.org_a,
            user_id=self.owner_a.id,
            user_email=self.owner_a.email,
            role="owner",
            is_pending=False,
        )
        self.admin_a_membership = OrganizationMembership.objects.create(
            organization=self.org_a,
            user_id=self.admin_a.id,
            user_email=self.admin_a.email,
            role="admin",
            is_pending=False,
        )
        self.member_a_membership = OrganizationMembership.objects.create(
            organization=self.org_a,
            user_id=self.member_a.id,
            user_email=self.member_a.email,
            role="member",
            is_pending=False,
        )
        self.owner_b_membership = OrganizationMembership.objects.create(
            organization=self.org_b,
            user_id=self.owner_b.id,
            user_email=self.owner_b.email,
            role="owner",
            is_pending=False,
        )
        self.member_b_membership = OrganizationMembership.objects.create(
            organization=self.org_b,
            user_id=self.member_b.id,
            user_email=self.member_b.email,
            role="member",
            is_pending=False,
        )

        self.department_a = Department.objects.create(
            organization=self.org_a,
            name="Tenant A Engineering",
            code="AENG",
        )
        self.department_b = Department.objects.create(
            organization=self.org_b,
            name="PLAT4200 PRIVATE Department B",
            code="BPRIV",
        )
        self.team_b = Team.objects.create(
            organization=self.org_b,
            name="PLAT4200 PRIVATE Team B",
            department=self.department_b,
        )
        self.position_b = Position.objects.create(
            organization=self.org_b,
            title="PLAT4200 PRIVATE Position B",
            code="B-PRIVATE-POSITION",
            department=self.department_b,
            level=7,
        )

        # Membership signals create an EmployeeProfile for every accepted user.
        self.profile_a = EmployeeProfile.objects.get(
            membership=self.admin_a_membership,
        )
        self.profile_b = EmployeeProfile.objects.get(
            membership=self.member_b_membership,
        )
        self.profile_b.department = self.department_b
        self.profile_b.position = self.position_b
        self.profile_b.job_title = "PLAT4200 PRIVATE Employee B"
        self.profile_b.employee_id = "B-PRIVATE-EMPLOYEE"
        self.profile_b.save()
        self.team_membership_b = TeamMembership.objects.create(
            team=self.team_b,
            employee_profile=self.profile_b,
            role="member",
        )
        OrganizationServiceAccess.objects.update_or_create(
            organization=self.org_b,
            service_slug="plat4200-private-service",
            defaults={"is_enabled": True},
        )

    def authenticate(self, principal):
        self.client.force_authenticate(user=principal)

    @staticmethod
    def _request(client, method, path, data=None, **headers):
        caller = getattr(client, method.lower())
        if method.lower() == "get":
            return caller(path, data=data or {}, **headers)
        return caller(path, data=data or {}, format="json", **headers)

    def tenant_state(self, org):
        """Security-relevant state used to prove a rejected write was inert."""
        return {
            "organization": list(
                Organization.objects.filter(pk=org.pk).values(
                    "id", "name", "slug", "description", "owner_id", "is_active"
                )
            ),
            "memberships": list(
                OrganizationMembership.objects.filter(organization=org)
                .order_by("id")
                .values(
                    "id", "user_id", "user_email", "role", "is_pending", "is_active"
                )
            ),
            "departments": list(
                Department.objects.filter(organization=org)
                .order_by("id")
                .values("id", "name", "code", "parent_id", "is_active")
            ),
            "teams": list(
                Team.objects.filter(organization=org)
                .order_by("id")
                .values("id", "name", "department_id", "is_active")
            ),
            "positions": list(
                Position.objects.filter(organization=org)
                .order_by("id")
                .values("id", "title", "code", "department_id", "is_active")
            ),
            "employees": list(
                EmployeeProfile.objects.filter(membership__organization=org)
                .order_by("id")
                .values(
                    "id",
                    "membership_id",
                    "department_id",
                    "position_id",
                    "job_title",
                    "employee_id",
                )
            ),
            "team_memberships": list(
                TeamMembership.objects.filter(team__organization=org)
                .order_by("id")
                .values("id", "team_id", "employee_profile_id", "role", "is_active")
            ),
            "services": list(
                OrganizationServiceAccess.objects.filter(organization=org)
                .order_by("id")
                .values("id", "service_slug", "is_enabled", "granted_by_id")
            ),
            "jit_grants": list(
                JITElevatedAccessGrant.objects.filter(organization=org)
                .order_by("id")
                .values(
                    "id",
                    "requester_user_id",
                    "scope",
                    "requested_role",
                    "status",
                    "expires_at",
                )
            ),
            "membership_audit": list(
                MembershipChange.objects.filter(organization=org)
                .order_by("id")
                .values(
                    "id",
                    "target_user_id",
                    "target_user_email",
                    "action",
                    "previous_role",
                    "new_role",
                )
            ),
        }

    def all_database_state(self):
        """Small global checksum for privileged-route negative tests."""
        return {
            "organizations": Organization.objects.count(),
            "memberships": OrganizationMembership.objects.count(),
            "departments": Department.objects.count(),
            "teams": Team.objects.count(),
            "positions": Position.objects.count(),
            "employees": EmployeeProfile.objects.count(),
            "team_memberships": TeamMembership.objects.count(),
            "services": OrganizationServiceAccess.objects.count(),
            "jit_grants": JITElevatedAccessGrant.objects.count(),
            "membership_audit": MembershipChange.objects.count(),
            "tenant_b": self.tenant_state(self.org_b),
        }


class CrossTenantOrganizationIsolationTests(OrganizationIsolationFixture):
    """A member/admin of tenant A has no authority over tenant B."""

    PRIVATE_MARKERS = (
        "plat4200-private",
        "private-member-b@plat4200.test",
        "b-private-employee",
    )

    def assert_scoped_or_denied(self, response):
        """A scoped list may be an empty 200; all other access must deny/hide."""
        if response.status_code == status.HTTP_200_OK:
            payload = response.json()
            if isinstance(payload, list):
                self.assertEqual(payload, [])
            elif isinstance(payload, dict) and "results" in payload:
                self.assertEqual(payload["results"], [])
                self.assertEqual(payload.get("count"), 0)
            else:
                self.fail(f"foreign-tenant route returned an unscoped 200: {payload!r}")
        else:
            self.assertIn(
                response.status_code,
                (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
            )

        body = response.content.decode("utf-8", errors="replace").lower()
        for marker in self.PRIVATE_MARKERS:
            self.assertNotIn(marker, body)

    def test_nonmember_cannot_read_any_foreign_org_member_hr_chart_or_service_surface(self):
        self.authenticate(self.admin_a)
        slug = self.org_b.slug
        reads = (
            ("organization", f"/api/organizations/{slug}/", None),
            ("members", f"/api/organizations/{slug}/members/", None),
            ("departments-list", f"/api/organizations/{slug}/departments/", None),
            ("department-detail", f"/api/organizations/{slug}/departments/{self.department_b.pk}/", None),
            ("department-tree", f"/api/organizations/{slug}/departments/tree/", None),
            ("department-employees", f"/api/organizations/{slug}/departments/{self.department_b.pk}/employees/", None),
            ("teams-list", f"/api/organizations/{slug}/teams/", None),
            ("team-detail", f"/api/organizations/{slug}/teams/{self.team_b.pk}/", None),
            ("team-members", f"/api/organizations/{slug}/teams/{self.team_b.pk}/members/", None),
            ("positions-list", f"/api/organizations/{slug}/positions/", None),
            ("position-detail", f"/api/organizations/{slug}/positions/{self.position_b.pk}/", None),
            ("employees-list", f"/api/organizations/{slug}/employees/", None),
            ("employee-detail", f"/api/organizations/{slug}/employees/{self.profile_b.pk}/", None),
            # DRF action url_path defaults to the Python method name; these two
            # routes therefore use underscores even though their url_name uses
            # dashes.
            ("direct-reports", f"/api/organizations/{slug}/employees/{self.profile_b.pk}/direct_reports/", None),
            ("management-chain", f"/api/organizations/{slug}/employees/{self.profile_b.pk}/management_chain/", None),
            ("org-chart", f"/api/organizations/{slug}/org-chart/", None),
            ("org-chart-stats", f"/api/organizations/{slug}/org-chart/stats/", None),
            (
                "org-chart-department",
                f"/api/organizations/{slug}/org-chart/by-department/",
                {"department_id": self.department_b.pk},
            ),
            (
                "org-chart-department-legacy",
                f"/api/organizations/{slug}/org-chart/by_department/",
                {"department_id": self.department_b.pk},
            ),
            ("org-services", f"/api/organizations/{slug}/services/", None),
            ("member-services", f"/api/organizations/{slug}/services/members/", None),
        )

        before = self.tenant_state(self.org_b)
        with patch("requests.get", return_value=_OfflineResponse()):
            for label, path, query in reads:
                with self.subTest(surface=label):
                    # A typo/non-existent route returning 404 is not isolation
                    # evidence.  Prove the intended production route resolves.
                    resolve(path)
                    response = self.client.get(path, data=query or {})
                    self.assert_scoped_or_denied(response)
        self.assertEqual(self.tenant_state(self.org_b), before)

    def test_nonmember_cannot_mutate_foreign_org_members_roles_hr_or_services(self):
        self.authenticate(self.admin_a)
        slug = self.org_b.slug
        writes = (
            ("org-update", "patch", f"/api/organizations/{slug}/", {"name": "hijacked"}),
            ("org-delete", "delete", f"/api/organizations/{slug}/", None),
            (
                "self-add-as-owner",
                "post",
                f"/api/organizations/{slug}/members/",
                {"user_email": self.admin_a.email, "role": "owner"},
            ),
            (
                "role-patch",
                "patch",
                f"/api/organizations/{slug}/members/{self.member_b_membership.pk}/",
                {"role": "owner"},
            ),
            (
                "member-remove",
                "delete",
                f"/api/organizations/{slug}/members/{self.member_b_membership.pk}/",
                None,
            ),
            (
                "department-create",
                "post",
                f"/api/organizations/{slug}/departments/",
                {"name": "hijacked", "code": "HIJACK"},
            ),
            (
                "department-update",
                "patch",
                f"/api/organizations/{slug}/departments/{self.department_b.pk}/",
                {"name": "hijacked"},
            ),
            (
                "department-delete",
                "delete",
                f"/api/organizations/{slug}/departments/{self.department_b.pk}/",
                None,
            ),
            (
                "team-create",
                "post",
                f"/api/organizations/{slug}/teams/",
                {"name": "hijacked"},
            ),
            (
                "team-update",
                "patch",
                f"/api/organizations/{slug}/teams/{self.team_b.pk}/",
                {"name": "hijacked"},
            ),
            (
                "team-delete",
                "delete",
                f"/api/organizations/{slug}/teams/{self.team_b.pk}/",
                None,
            ),
            (
                "team-member-add",
                "post",
                f"/api/organizations/{slug}/teams/{self.team_b.pk}/members/",
                {"employee_profile_id": self.profile_a.pk, "role": "member"},
            ),
            (
                "team-member-remove",
                "delete",
                f"/api/organizations/{slug}/teams/{self.team_b.pk}/members/{self.team_membership_b.pk}/",
                None,
            ),
            (
                "position-create",
                "post",
                f"/api/organizations/{slug}/positions/",
                {"title": "hijacked", "code": "HIJACK", "level": 1},
            ),
            (
                "position-update",
                "patch",
                f"/api/organizations/{slug}/positions/{self.position_b.pk}/",
                {"title": "hijacked"},
            ),
            (
                "position-delete",
                "delete",
                f"/api/organizations/{slug}/positions/{self.position_b.pk}/",
                None,
            ),
            (
                "employee-create",
                "post",
                f"/api/organizations/{slug}/employees/",
                {"membership_id": self.member_b_membership.pk, "job_title": "hijacked"},
            ),
            (
                "employee-update",
                "patch",
                f"/api/organizations/{slug}/employees/{self.profile_b.pk}/",
                {"job_title": "hijacked"},
            ),
            (
                "employee-delete",
                "delete",
                f"/api/organizations/{slug}/employees/{self.profile_b.pk}/",
                None,
            ),
            (
                "member-service-toggle",
                "post",
                f"/api/organizations/{slug}/services/members/{self.member_b.id}/",
                {"service_slugs": ["admin"], "action": "revoke"},
            ),
        )

        with (
            patch("requests.get", return_value=_OfflineResponse()) as upstream_get,
            patch("requests.post", return_value=_OfflineResponse()) as upstream_post,
            patch("requests.patch", return_value=_OfflineResponse()) as upstream_patch,
            patch("requests.delete", return_value=_OfflineResponse()) as upstream_delete,
        ):
            for label, method, path, data in writes:
                with self.subTest(surface=label):
                    resolve(path)
                    before = self.tenant_state(self.org_b)
                    response = self._request(self.client, method, path, data)
                    self.assertIn(
                        response.status_code,
                        (
                            status.HTTP_403_FORBIDDEN,
                            status.HTTP_404_NOT_FOUND,
                            status.HTTP_405_METHOD_NOT_ALLOWED,
                        ),
                    )
                    self.assertEqual(self.tenant_state(self.org_b), before)

        # Authorization must happen before any identity-service proxy call.
        self.assertFalse(upstream_get.called)
        self.assertFalse(upstream_post.called)
        self.assertFalse(upstream_patch.called)
        self.assertFalse(upstream_delete.called)

    def test_plain_org_member_cannot_delete_a_peer_employee_profile(self):
        """Regression for an inherited ModelViewSet.destroy authorization gap."""
        self.authenticate(self.member_a)
        before = self.tenant_state(self.org_a)

        response = self.client.delete(
            f"/api/organizations/{self.org_a.slug}/employees/{self.profile_a.pk}/"
        )

        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )
        self.assertEqual(self.tenant_state(self.org_a), before)

    def test_legitimate_member_reads_and_org_admin_write_are_positive_controls(self):
        self.authenticate(self.member_a)
        with patch("requests.get", return_value=_OfflineResponse()):
            member_responses = (
                self.client.get(f"/api/organizations/{self.org_a.slug}/"),
                self.client.get(f"/api/organizations/{self.org_a.slug}/members/"),
                self.client.get(f"/api/organizations/{self.org_a.slug}/departments/"),
                self.client.get(f"/api/organizations/{self.org_a.slug}/employees/"),
                self.client.get(f"/api/organizations/{self.org_a.slug}/org-chart/"),
                self.client.get(f"/api/organizations/{self.org_a.slug}/services/"),
            )
        for response in member_responses:
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.authenticate(self.admin_a)
        response = self.client.post(
            f"/api/organizations/{self.org_a.slug}/departments/",
            {"name": "Positive Control", "code": "POSCTL"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            Department.objects.filter(
                organization=self.org_a,
                code="POSCTL",
                name="Positive Control",
            ).exists()
        )


class SuperuserToolBoundaryTests(OrganizationIsolationFixture):
    """Every MCP ``admin_su_*`` HTTP target requires a real superuser claim."""

    SU_HTTP_SURFACES = (
        ("dashboard", "get", "/api/superuser/dashboard/", None),
        ("users-list", "get", "/api/superuser/users/", None),
        ("users-create", "post", "/api/superuser/users/create/", {"email": "x@example.test"}),
        ("user-detail", "get", "/api/superuser/users/777/", None),
        ("user-update", "patch", "/api/superuser/users/777/update/", {"is_superuser": True}),
        ("user-delete-preview", "get", "/api/superuser/users/777/delete-preview/", None),
        ("user-delete", "delete", "/api/superuser/users/777/delete/", None),
        ("organizations-list", "get", "/api/superuser/organizations/", None),
        (
            "organization-create",
            "post",
            "/api/superuser/organizations/create/",
            {"name": "unauthorized", "slug": "unauthorized", "owner_id": 777},
        ),
        (
            "organization-update",
            "patch",
            "/api/superuser/organizations/plat4200-tenant-b/update/",
            {"name": "unauthorized"},
        ),
        (
            "organization-detail",
            "get",
            "/api/superuser/organizations/plat4200-tenant-b/detail/",
            None,
        ),
        ("system-health", "get", "/api/superuser/system/health/", None),
        ("services-list", "get", "/api/superuser/services/", None),
        (
            "organization-services-list",
            "get",
            "/api/superuser/organizations/plat4200-tenant-b/services/",
            None,
        ),
        (
            "organization-services-write",
            "post",
            "/api/superuser/organizations/plat4200-tenant-b/services/",
            {"service_slugs": ["admin"], "action": "revoke"},
        ),
        ("user-services-list", "get", "/api/superuser/users/777/services/", None),
        (
            "user-services-write",
            "post",
            "/api/superuser/users/777/services/",
            {"service_slugs": ["admin"], "action": "grant"},
        ),
        ("requests-list", "get", "/api/superuser/requests/", None),
        ("request-review", "patch", "/api/superuser/requests/777/", {"status": "approved"}),
        ("pending-users", "get", "/api/superuser/users/pending/", None),
        ("pending-count", "get", "/api/superuser/users/pending/count/", None),
        (
            "user-approval",
            "patch",
            "/api/superuser/users/777/approve/",
            {"status": "active", "review_note": "unauthorized"},
        ),
    )

    def test_tenant_user_and_staff_without_superuser_are_denied_before_side_effects(self):
        principals = (
            ("tenant", self.admin_a),
            ("staff-not-superuser", _user(800, "staff@plat4200.test", is_staff=True)),
        )

        with (
            patch("requests.get", return_value=_OfflineResponse()) as upstream_get,
            patch("requests.post", return_value=_OfflineResponse()) as upstream_post,
            patch("requests.patch", return_value=_OfflineResponse()) as upstream_patch,
            patch("requests.delete", return_value=_OfflineResponse()) as upstream_delete,
        ):
            for principal_label, principal in principals:
                self.authenticate(principal)
                for surface, method, path, data in self.SU_HTTP_SURFACES:
                    with self.subTest(principal=principal_label, surface=surface):
                        resolve(path)
                        before = self.all_database_state()
                        response = self._request(self.client, method, path, data)
                        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                        self.assertEqual(self.all_database_state(), before)

        self.assertFalse(upstream_get.called)
        self.assertFalse(upstream_post.called)
        self.assertFalse(upstream_patch.called)
        self.assertFalse(upstream_delete.called)

    def test_superuser_can_read_and_mutate_local_superuser_surfaces(self):
        superuser = _user(
            900,
            "platform-superuser@plat4200.test",
            is_staff=True,
            is_superuser=True,
        )
        self.authenticate(superuser)

        list_response = self.client.get("/api/superuser/organizations/")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertIn(
            self.org_b.slug,
            {org["slug"] for org in list_response.json()["results"]},
        )

        update_response = self.client.patch(
            f"/api/superuser/organizations/{self.org_b.slug}/update/",
            {"description": "updated by positive-control superuser"},
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.org_b.refresh_from_db()
        self.assertEqual(
            self.org_b.description,
            "updated by positive-control superuser",
        )

        service_response = self.client.post(
            f"/api/superuser/organizations/{self.org_b.slug}/services/",
            {"service_slugs": ["plat4200-superuser-positive"], "action": "grant"},
            format="json",
        )
        self.assertEqual(service_response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            OrganizationServiceAccess.objects.filter(
                organization=self.org_b,
                service_slug="plat4200-superuser-positive",
                is_enabled=True,
                granted_by_id=superuser.id,
            ).exists()
        )


class JITElevationIsolationContractTests(OrganizationIsolationFixture):
    """JIT is scoped, approved out-of-band, and never a generic role write."""

    REQUEST = {
        "scope": "org.members.add",
        "requested_role": "admin",
        "reason": "PLAT-4200 authorization invariant",
        "task_key": "PLAT-4200",
        "ttl_seconds": 1800,
        # A caller assertion is not policy proof.
        "policy_slug": "passed-it-audit-org-member-add",
    }

    def test_nonmember_cannot_request_jit_for_foreign_org(self):
        self.authenticate(self.admin_a)
        before = self.tenant_state(self.org_b)

        response = self.client.post(
            "/api/jit-elevations/",
            {"org_slug": self.org_b.slug, **self.REQUEST},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.tenant_state(self.org_b), before)

    def _grant_for(self, principal, *, organization=None, scope='org.members.add',
                   requested_role='admin', status_value=JITElevatedAccessGrant.STATUS_APPROVED,
                   expires_at=None, revoked_at=None):
        return JITElevatedAccessGrant.objects.create(
            organization=organization or self.org_b,
            requester_user_id=principal.id,
            requester_email=principal.email,
            scope=scope,
            requested_role=requested_role,
            reason='PLAT-4843 cross-org projection regression',
            task_key='PLAT-4843',
            ttl_seconds=1800,
            status=status_value,
            approval_path=JITElevatedAccessGrant.APPROVAL_TEAM,
            expires_at=expires_at or timezone.now() + timedelta(minutes=30),
            revoked_at=revoked_at,
        )

    def test_nonmember_active_grant_projects_exact_org_and_authorizes_only_member_add(self):
        grantee = _user(301, 'jit-grantee@plat4200.test')
        grant = self._grant_for(grantee)
        self.authenticate(grantee)

        listed = self.client.get('/api/organizations/')
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {org['slug'] for org in listed.json()['results']},
            {self.org_b.slug, f'personal-{grantee.id}'},
        )

        with patch('requests.get', return_value=_OfflineResponse()):
            invite = self.client.post(
                f'/api/organizations/{self.org_b.slug}/members/',
                {'user_email': 'jit-added@plat4200.test', 'role': 'member'},
                format='json',
            )
        self.assertEqual(invite.status_code, status.HTTP_201_CREATED)
        self.assertTrue(OrganizationMembership.objects.filter(
            organization=self.org_b,
            user_email='jit-added@plat4200.test',
            is_pending=True,
        ).exists())

        forbidden_update = self.client.patch(
            f'/api/organizations/{self.org_b.slug}/',
            {'name': 'JIT scope escaped'},
            format='json',
        )
        self.assertEqual(forbidden_update.status_code, status.HTTP_403_FORBIDDEN)
        self.org_b.refresh_from_db()
        self.assertEqual(self.org_b.name, 'PLAT4200 PRIVATE Tenant B')

        # Production-order boundary: the same caller immediately loses lookup
        # and member-add authority when the grant expires or is revoked.
        grant.expires_at = timezone.now() - timedelta(seconds=1)
        grant.save(update_fields=['expires_at'])
        after_expiry = self.client.get('/api/organizations/')
        self.assertNotIn(
            self.org_b.slug,
            {org['slug'] for org in after_expiry.json()['results']},
        )
        expired_invite = self.client.post(
            f'/api/organizations/{self.org_b.slug}/members/',
            {'user_email': 'expired-denied@plat4200.test', 'role': 'member'},
            format='json',
        )
        self.assertEqual(expired_invite.status_code, status.HTTP_404_NOT_FOUND)

        grant.expires_at = timezone.now() + timedelta(minutes=30)
        grant.revoked_at = timezone.now()
        grant.save(update_fields=['expires_at', 'revoked_at'])
        revoked_invite = self.client.post(
            f'/api/organizations/{self.org_b.slug}/members/',
            {'user_email': 'revoked-denied@plat4200.test', 'role': 'member'},
            format='json',
        )
        self.assertEqual(revoked_invite.status_code, status.HTTP_404_NOT_FOUND)

    def test_nonmember_inactive_and_mismatched_grants_fail_closed(self):
        cases = (
            ('pending', {
                'status_value': JITElevatedAccessGrant.STATUS_PENDING,
            }, status.HTTP_404_NOT_FOUND),
            ('expired', {
                'expires_at': timezone.now() - timedelta(seconds=1),
            }, status.HTTP_404_NOT_FOUND),
            ('revoked', {
                'revoked_at': timezone.now(),
            }, status.HTTP_404_NOT_FOUND),
            ('wrong-scope', {
                'scope': 'org.members.owner_transfer',
            }, status.HTTP_404_NOT_FOUND),
            ('insufficient-role', {
                'requested_role': 'viewer',
            }, status.HTTP_404_NOT_FOUND),
        )

        for index, (label, grant_kwargs, expected_status) in enumerate(cases):
            with self.subTest(grant=label):
                grantee = _user(400 + index, f'{label}@plat4200.test')
                self._grant_for(grantee, **grant_kwargs)
                self.authenticate(grantee)
                before = self.tenant_state(self.org_b)

                listed = self.client.get('/api/organizations/')
                self.assertEqual(listed.status_code, status.HTTP_200_OK)
                self.assertNotIn(
                    self.org_b.slug,
                    {org['slug'] for org in listed.json()['results']},
                )

                with patch('requests.get', return_value=_OfflineResponse()) as upstream_get:
                    response = self.client.post(
                        f'/api/organizations/{self.org_b.slug}/members/',
                        {'user_email': f'{label}-denied@plat4200.test', 'role': 'member'},
                        format='json',
                    )

                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(self.tenant_state(self.org_b), before)
                self.assertFalse(upstream_get.called)

    def test_nonmember_active_grant_does_not_project_or_authorize_wrong_org(self):
        grantee = _user(501, 'wrong-org@plat4200.test')
        self._grant_for(grantee, organization=self.org_a)
        self.authenticate(grantee)

        listed = self.client.get('/api/organizations/')
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {org['slug'] for org in listed.json()['results']},
            {self.org_a.slug, f'personal-{grantee.id}'},
        )

        with patch('requests.get', return_value=_OfflineResponse()) as upstream_get:
            response = self.client.post(
                f'/api/organizations/{self.org_b.slug}/members/',
                {'user_email': 'wrong-org-denied@plat4200.test', 'role': 'member'},
                format='json',
            )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(upstream_get.called)

    def test_pending_approval_and_scoped_grant_are_the_accepted_jit_contract(self):
        self.authenticate(self.member_a)
        membership_count = OrganizationMembership.objects.filter(
            organization=self.org_a
        ).count()
        original_org_name = self.org_a.name

        request_response = self.client.post(
            "/api/jit-elevations/",
            {"org_slug": self.org_a.slug, **self.REQUEST},
            format="json",
        )
        self.assertEqual(request_response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(request_response.json()["auto_approved"])

        grant = JITElevatedAccessGrant.objects.get(
            organization=self.org_a,
            requester_user_id=self.member_a.id,
        )
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_PENDING)
        self.assertFalse(grant.is_active_now())
        self.assertEqual(grant.policy_slug, "")
        self.member_a_membership.refresh_from_db()
        self.assertEqual(self.member_a_membership.role, "member")

        # Pending is not authority, and a requester may not self-approve.
        with patch("requests.get", return_value=_OfflineResponse()) as upstream_get:
            invite_while_pending = self.client.post(
                f"/api/organizations/{self.org_a.slug}/members/",
                {"user_email": "pending-denied@plat4200.test", "role": "member"},
                format="json",
            )
        self.assertEqual(invite_while_pending.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(upstream_get.called)
        self.assertEqual(
            OrganizationMembership.objects.filter(organization=self.org_a).count(),
            membership_count,
        )

        self_approval = self.client.post(
            f"/api/jit-elevations/{grant.pk}/approve/",
            {"note": "self approval must fail"},
            format="json",
        )
        self.assertEqual(self_approval.status_code, status.HTTP_403_FORBIDDEN)
        grant.refresh_from_db()
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_PENDING)

        # An independent org owner may approve this low-risk, scoped request.
        self.authenticate(self.owner_a)
        approval = self.client.post(
            f"/api/jit-elevations/{grant.pk}/approve/",
            {"note": "approved by owning org"},
            format="json",
        )
        self.assertEqual(approval.status_code, status.HTTP_200_OK)
        grant.refresh_from_db()
        self.assertTrue(grant.is_active_now())

        # The grant enables only member-add, not generic org administration.
        self.authenticate(self.member_a)
        with patch("requests.get", return_value=_OfflineResponse()):
            scoped_invite = self.client.post(
                f"/api/organizations/{self.org_a.slug}/members/",
                {"user_email": "scoped-add@plat4200.test", "role": "member"},
                format="json",
            )
        self.assertEqual(scoped_invite.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            OrganizationMembership.objects.filter(
                organization=self.org_a,
                user_email="scoped-add@plat4200.test",
                is_pending=True,
                role="member",
            ).exists()
        )

        org_update = self.client.patch(
            f"/api/organizations/{self.org_a.slug}/",
            {"name": "JIT escaped its scope"},
            format="json",
        )
        self.assertEqual(org_update.status_code, status.HTTP_403_FORBIDDEN)
        self.org_a.refresh_from_db()
        self.assertEqual(self.org_a.name, original_org_name)
        self.member_a_membership.refresh_from_db()
        self.assertEqual(self.member_a_membership.role, "member")


class SagaOrgDeleteRouteTests(SimpleTestCase):
    def test_saga_org_delete_is_not_shadowed_by_org_lookup(self):
        match = resolve("/api/internal/organizations/1053/delete/")
        self.assertEqual(match.url_name, "internal-org-delete")
        self.assertEqual(match.kwargs.get("org_id"), 1053)


@override_settings(
    ADMIN_INTERNAL_SERVICE_TOKEN="plat4200-internal-test-token",
    ADMIN_INTERNAL_SERVICE_TOKEN_ENFORCE=True,
)
class InternalRouteIsolationTests(TestCase):
    """The internal control plane is service-authenticated and ingress-dark."""

    EXPECTED_INTERNAL_ROUTES = {
        "internal-permission-check": "permissions/check/",
        "internal-user-organizations": "users/<int:user_id>/organizations/",
        "internal-user-memberships": "users/<int:user_id>/memberships/",
        "internal-user-project-memberships": "users/<int:user_id>/project-memberships/",
        # PLAT-5343 slice 1: acyclic v2 composition route (fail-closed
        # subject-assertion auth in-view; reviewed under HLD v12 §4.1/§4.3).
        # No trailing slash — the HLD §4.1 wire contract is
        # POST /api/internal/v2/project-memberships:resolve.
        "internal-v2-project-memberships-resolve": "v2/project-memberships:resolve",
        "internal-user-projects": "users/<int:user_id>/projects/",
        "internal-user-agent-profile": "users/<int:user_id>/agent-profile/",
        "internal-project": "projects/<int:project_id>/",
        "internal-next-item-key": "projects/<int:project_id>/next-item-key/",
        "internal-organization": "organizations/<str:org_identifier>/",
        # HIVE-2715: saga provisioning surface (least-privilege; reviewed
        # under HIVE-320/HIVE-418 — atomic create-or-attach keyed on the
        # unique slug, HIVE-671 signed envelope, 409 on immutable conflict).
        "internal-org-create": "organizations/",
        # HIVE-2697 cleanup contract extended to the minted org:
        # provenance-refusing saga teardown (refuses without the marker
        # or with members beyond the minted owner row).
        "internal-org-delete": "organizations/<int:org_id>/delete/",
        "internal-org-members": "organizations/<int:org_id>/members/",
        "internal-org-membership-check": "organizations/<int:org_id>/members/<int:user_id>/",
        "internal-org-services": "organizations/<int:org_id>/services/",
    }
    CONVERTER = re.compile(r"<(?:int|str):[^>]+>")

    def setUp(self):
        self.client = APIClient()
        self.user_id = 42001
        self.personal_org = Organization.objects.create(
            name="Internal Consumer Positive Control",
            slug=f"personal-{self.user_id}",
            owner_id=self.user_id,
            is_personal=True,
        )
        OrganizationMembership.objects.create(
            organization=self.personal_org,
            user_id=self.user_id,
            user_email="internal-user@plat4200.test",
            role="owner",
            is_pending=False,
        )

    @classmethod
    def concrete_path(cls, relative_pattern):
        return "/api/internal/" + cls.CONVERTER.sub("1", relative_pattern)

    def test_internal_route_manifest_is_complete_unique_and_reviewed(self):
        manifest = [
            (pattern.name, str(pattern.pattern))
            for pattern in internal_urlpatterns
        ]
        names = [name for name, _pattern in manifest]
        patterns = [pattern for _name, pattern in manifest]

        # Duplicate names/paths create shadowed endpoints that a future audit may
        # inspect while Django resolves a different implementation.
        self.assertEqual(len(names), len(set(names)), manifest)
        self.assertEqual(len(patterns), len(set(patterns)), manifest)
        self.assertEqual(dict(manifest), self.EXPECTED_INTERNAL_ROUTES)

    def test_every_manifest_route_is_forbidden_through_public_ingress(self):
        with patch("requests.get", return_value=_OfflineResponse()):
            for route_name, relative_pattern in self.EXPECTED_INTERNAL_ROUTES.items():
                with self.subTest(route=route_name):
                    path = self.concrete_path(relative_pattern)
                    self.assertEqual(resolve(path).url_name, route_name)
                    response = self.client.get(
                        path,
                        HTTP_X_FORWARDED_FOR="203.0.113.42",
                        HTTP_AUTHORIZATION="Bearer tenant-jwt-must-not-help",
                        HTTP_X_INTERNAL_SERVICE="shizuha-id",
                        HTTP_X_INTERNAL_SERVICE_TOKEN="plat4200-internal-test-token",
                    )
                    self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_public_prefix_variant_is_also_guarded(self):
        response = self.client.get(
            f"/admin/api/internal/users/{self.user_id}/memberships/",
            HTTP_X_FORWARDED_FOR="203.0.113.42",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_tenant_bearer_or_spoofed_service_name_is_not_internal_auth(self):
        attempts = (
            {"HTTP_AUTHORIZATION": "Bearer tenant-jwt"},
            {"HTTP_X_INTERNAL_SERVICE": "shizuha-id"},
            {
                "HTTP_X_INTERNAL_SERVICE": "shizuha-id",
                "HTTP_X_INTERNAL_SERVICE_TOKEN": "wrong-token",
            },
        )
        path = f"/api/internal/users/{self.user_id}/memberships/"
        for headers in attempts:
            with self.subTest(headers=headers):
                response = self.client.get(path, **headers)
                self.assertIn(
                    response.status_code,
                    (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
                )

    def test_authenticated_internal_consumer_still_gets_exact_membership_projection(self):
        response = self.client.get(
            f"/api/internal/users/{self.user_id}/memberships/",
            {"email": "internal-user@plat4200.test"},
            HTTP_X_INTERNAL_SERVICE="shizuha-id",
            HTTP_X_INTERNAL_SERVICE_TOKEN="plat4200-internal-test-token",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "memberships": {str(self.personal_org.pk): "owner"},
                "jit_scoped_grants": [],
            },
        )

    def test_internal_org_member_list_does_not_resolve_profiles_per_member(self):
        """The control-plane list is bounded to Admin's local projection."""
        with patch("organizations.internal_urls.http_requests.get") as id_get:
            response = self.client.get(
                f"/api/internal/organizations/{self.personal_org.pk}/members/",
                HTTP_X_INTERNAL_SERVICE="shizuha-hive",
                HTTP_X_INTERNAL_SERVICE_TOKEN="plat4200-internal-test-token",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        id_get.assert_not_called()
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(
            response.json()["members"][0],
            {
                "user_id": self.user_id,
                "user_email": "internal-user@plat4200.test",
                "user_name": "internal-user",
                "role": "owner",
                "is_pending": False,
            },
        )

    def test_ingress_guard_is_wired_before_service_access(self):
        guard = "organizations.middleware.InternalApiIngressGuardMiddleware"
        service_access = "organizations.middleware.ServiceAccessMiddleware"
        self.assertIn(guard, settings.MIDDLEWARE)
        self.assertIn(service_access, settings.MIDDLEWARE)
        self.assertLess(
            settings.MIDDLEWARE.index(guard),
            settings.MIDDLEWARE.index(service_access),
        )
