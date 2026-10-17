from types import SimpleNamespace

from django.test import TestCase
from rest_framework.test import APIClient

from organizations.models import Department, Organization, OrganizationMembership


class OrgChartByDepartmentRouteTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(
            name="Shizuha Global",
            slug="shizuha",
            owner_id=1,
        )
        OrganizationMembership.objects.create(
            organization=self.org,
            user_id=1,
            user_email="owner@shizuha.com",
            role="owner",
            is_pending=False,
        )
        self.department = Department.objects.create(
            organization=self.org,
            name="Engineering",
            code="ENG",
        )
        self.client.force_authenticate(
            user=SimpleNamespace(
                id=1,
                email="owner@shizuha.com",
                is_staff=False,
                is_superuser=False,
                is_authenticated=True,
                enabled_services=None,
            )
        )

    def test_frontend_hyphen_route_returns_department_org_chart(self):
        response = self.client.get(
            f"/api/organizations/{self.org.slug}/org-chart/by-department/",
            {"department_id": self.department.id},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["department"]["id"], self.department.id)
        self.assertEqual(data["department"]["name"], "Engineering")
        self.assertEqual(data["count"], 0)

    def test_legacy_underscore_route_still_works(self):
        response = self.client.get(
            f"/api/organizations/{self.org.slug}/org-chart/by_department/",
            {"department_id": self.department.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["department"]["id"], self.department.id)
