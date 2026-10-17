from types import SimpleNamespace
from urllib.parse import urlsplit

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from organizations.models import Organization, OrganizationMembership, Team


class AdminPaginationPrefixTests(TestCase):
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
        for idx in range(25):
            Team.objects.create(
                organization=self.org,
                name=f"Team {idx:02d}",
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

    @override_settings(ALLOWED_HOSTS=["shizuha.com", "testserver"])
    def test_nested_team_pagination_uses_public_admin_prefix(self):
        """Regression for PLAT-1139: DRF next/previous must be public URLs."""
        response = self.client.get(
            f"/api/organizations/{self.org.slug}/teams/",
            HTTP_HOST="shizuha.com",
            HTTP_X_FORWARDED_PROTO="https",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 25)
        self.assertEqual(len(data["results"]), 20)
        self.assertEqual(
            data["next"],
            "https://shizuha.com/admin/api/organizations/shizuha/teams/?page=2",
        )

        public_next = urlsplit(data["next"])
        self.assertEqual(public_next.scheme, "https")
        self.assertEqual(public_next.netloc, "shizuha.com")
        self.assertTrue(public_next.path.startswith("/admin/api/"))

        # The public proxy strips /admin before the Django app receives the
        # follow-up request; emulate that rewrite so the emitted URL remains the
        # page-2 probe without needing nginx in the unit test.
        upstream_path = public_next.path.removeprefix("/admin")
        page_2 = self.client.get(
            f"{upstream_path}?{public_next.query}",
            HTTP_HOST="shizuha.com",
            HTTP_X_FORWARDED_PROTO="https",
        )
        self.assertEqual(page_2.status_code, 200)
        page_2_data = page_2.json()
        self.assertEqual(len(page_2_data["results"]), 5)
        self.assertEqual(
            page_2_data["previous"],
            "https://shizuha.com/admin/api/organizations/shizuha/teams/",
        )
