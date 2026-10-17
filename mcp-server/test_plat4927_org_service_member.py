"""PLAT-4927 regression: admin_add_org_service_member must send the backend's
MemberServiceAccessSerializer contract — {"service_slugs": [...], "action":
'grant'|'revoke'} — never the legacy {"services": [...]} body with no action
(which 400'd every call, so org service membership could not be provisioned
via MCP; personal-3 had zero Pulse service members for 57h+).

Run: SHIZUHA_ADMIN_URL=http://x python -m unittest test_plat4927_org_service_member -v
"""
import unittest
from unittest.mock import patch

import admin_server


class OrgServiceMemberPayloadContract(unittest.TestCase):

    def test_explicit_slugs_send_service_slugs_and_action(self):
        calls = []

        def fake_api(method, path, data=None, params=None):
            calls.append((method, path, data, params))
            return {"ok": True}

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            out = admin_server.add_org_service_member(
                org_slug="personal-3", user_id="3", service_slugs="pulse")

        self.assertEqual(len(calls), 1)
        method, path, data, _ = calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/organizations/personal-3/services/members/3/")
        self.assertEqual(data, {"service_slugs": ["pulse"], "action": "grant"})
        self.assertNotIn("services", data)
        self.assertIn("pulse", out)

    def test_no_slugs_resolves_org_enabled_services_first(self):
        calls = []

        def fake_api(method, path, data=None, params=None):
            calls.append((method, path, data, params))
            if method == "GET":
                return {"organization": "personal-3",
                        "org_services": ["books", "pulse"], "members": []}
            return {"ok": True}

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            admin_server.add_org_service_member(org_slug="personal-3", user_id="3")

        post = next(c for c in calls if c[0] == "POST")
        self.assertEqual(
            post[2], {"service_slugs": ["books", "pulse"], "action": "grant"})

    def test_revoke_action_is_forwarded(self):
        calls = []

        def fake_api(method, path, data=None, params=None):
            calls.append((method, path, data, params))
            return {"ok": True}

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            out = admin_server.add_org_service_member(
                org_slug="personal-3", user_id="3",
                service_slugs="pulse", action="revoke")

        self.assertEqual(calls[0][2], {"service_slugs": ["pulse"], "action": "revoke"})
        self.assertIn("revoked", out)

    def test_invalid_action_fails_before_any_request(self):
        with patch.object(admin_server.base, "api_request") as api:
            out = admin_server.add_org_service_member(
                org_slug="personal-3", user_id="3",
                service_slugs="pulse", action="destroy")
        api.assert_not_called()
        self.assertIn("must be 'grant' or 'revoke'", out)

    def test_empty_org_services_is_actionable_not_a_400(self):
        def fake_api(method, path, data=None, params=None):
            return {"organization": "personal-3", "org_services": [], "members": []}

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            out = admin_server.add_org_service_member(org_slug="personal-3", user_id="3")
        self.assertIn("no enabled services", out)

class OrgServiceMemberListVerification(unittest.TestCase):
    """The pinned acceptance verifies a grant through admin_list_org_service_members,
    so the list tool must parse the backend's real {organization, org_services,
    members} shape and surface per-member grants."""

    def test_list_parses_backend_shape_and_shows_grants(self):
        calls = []

        def fake_api(method, path, data=None, params=None):
            calls.append((method, path, data, params))
            return {
                "organization": "personal-3",
                "org_services": ["books", "pulse"],
                "members": [
                    {"user_id": 3, "user_email": "test-owner@shizuha.com",
                     "role": "owner", "services": ["pulse"]},
                    {"user_id": 9, "user_email": "empty@shizuha.com",
                     "role": "member", "services": []},
                ],
            }

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            out = admin_server.list_org_service_members(org_slug="personal-3")

        self.assertNotIn("No service members found", out)
        self.assertIn("test-owner@shizuha.com", out)
        self.assertIn("Services: pulse", out)
        self.assertIn("Services: (none)", out)
        self.assertIn("Org services enabled: books, pulse", out)
        self.assertEqual(
            calls,
            [("GET", "/organizations/personal-3/services/members/", None,
              {"limit": 32, "offset": 0})],
        )

    def test_list_reports_identity_lookup_failure_instead_of_claiming_empty(self):
        def fake_api(method, path, data=None, params=None):
            return {
                "organization": "personal-3",
                "org_services": ["pulse"],
                "members": [
                    {"user_id": 3, "user_email": "test-owner@shizuha.com",
                     "role": "owner", "services": None,
                     "services_error": "identity service unavailable"},
                ],
            }

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            out = admin_server.list_org_service_members(org_slug="personal-3")

        self.assertIn("unknown — identity service unavailable", out)
        self.assertNotIn("Services: (none)", out)

    def test_grant_is_observable_through_the_list_tool(self):
        """End-to-end at the MCP layer: a grant issued via the add tool becomes
        visible in the list tool's output (stateful fake backend)."""
        grants = {3: set()}

        def fake_api(method, path, data=None, params=None):
            if method == "POST":
                uid = int(path.rstrip("/").rsplit("/", 1)[1])
                if data["action"] == "grant":
                    grants.setdefault(uid, set()).update(data["service_slugs"])
                else:
                    grants.setdefault(uid, set()).difference_update(data["service_slugs"])
                return {"ok": True}
            return {
                "organization": "personal-3",
                "org_services": ["pulse"],
                "members": [
                    {"user_id": 3, "user_email": "test-owner@shizuha.com",
                     "role": "owner", "services": sorted(grants[3])},
                ],
            }

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            before = admin_server.list_org_service_members(org_slug="personal-3")
            admin_server.add_org_service_member(
                org_slug="personal-3", user_id="3", service_slugs="pulse")
            after = admin_server.list_org_service_members(org_slug="personal-3")

        self.assertIn("Services: (none)", before)
        self.assertIn("Services: pulse", after)

    def test_list_exposes_bounded_pagination_cursor(self):
        def fake_api(method, path, data=None, params=None):
            return {
                "organization": "personal-3",
                "org_services": ["pulse"],
                "count": 40,
                "limit": 10,
                "offset": 20,
                "next_offset": 30,
                "members": [
                    {"user_id": 3, "user_email": "test-owner@shizuha.com",
                     "role": "owner", "services": ["pulse"]},
                ],
            }

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            out = admin_server.list_org_service_members(
                org_slug="personal-3", limit=10, offset=20)

        self.assertIn("of 40 from offset 20", out)
        self.assertIn("offset=30 for the next page", out)

    def test_list_org_services_reads_services_key_and_slug_rows(self):
        def fake_api(method, path, data=None, params=None):
            return {
                "organization": "personal-3",
                "services": [
                    {"slug": "pulse", "name": "Pulse", "is_enabled": True},
                    "books",
                    {"slug": "hive", "name": "Hive", "is_enabled": False},
                ],
            }

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            out = admin_server.list_org_services(org_slug="personal-3")

        self.assertIn("**Pulse**", out)
        self.assertIn("**books**", out)
        self.assertIn("**Hive**", out)
        self.assertIn("[disabled]", out)
        self.assertNotIn("No services enabled", out)

    def test_list_rejects_unbounded_or_negative_pages_before_request(self):
        with patch.object(admin_server.base, "api_request") as api:
            too_large = admin_server.list_org_service_members(
                org_slug="personal-3", limit=33)
            negative = admin_server.list_org_service_members(
                org_slug="personal-3", offset=-1)

        api.assert_not_called()
        self.assertIn("between 1 and 32", too_large)
        self.assertIn("zero or greater", negative)
