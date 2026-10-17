"""PLAT-5096 regression: admin_su_set_user_services must send the backend's
AdminUserServiceGrantSerializer contract — {"service_slugs": [...], "action":
'grant'|'revoke'} — never the legacy {"services": [...]} body with no action
(which 400'd every call, so superuser service-set via MCP silently no-opped,
the same defect class PLAT-4927 fixed on the org-member sibling).

Run: SHIZUHA_ADMIN_URL=http://x python -m unittest test_plat5096_su_set_user_services -v
"""
import unittest
from unittest.mock import patch

import admin_server


class SuSetUserServicesPayloadContract(unittest.TestCase):

    def test_grant_sends_service_slugs_and_action(self):
        calls = []

        def fake_api(method, path, data=None, params=None):
            calls.append((method, path, data, params))
            return {"ok": True}

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            out = admin_server.su_set_user_services(
                uid="42", service_slugs="pulse,books")

        self.assertEqual(len(calls), 1)
        method, path, data, _ = calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/superuser/users/42/services/")
        self.assertEqual(data, {"service_slugs": ["pulse", "books"], "action": "grant"})
        self.assertNotIn("services", data)
        self.assertIn("granted", out)
        self.assertIn("pulse, books", out)

    def test_revoke_action_is_forwarded(self):
        calls = []

        def fake_api(method, path, data=None, params=None):
            calls.append((method, path, data, params))
            return {"ok": True}

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            out = admin_server.su_set_user_services(
                uid="42", service_slugs="pulse", action="revoke")

        self.assertEqual(calls[0][2], {"service_slugs": ["pulse"], "action": "revoke"})
        self.assertIn("revoked", out)

    def test_invalid_action_fails_before_any_request(self):
        with patch.object(admin_server.base, "api_request") as api:
            out = admin_server.su_set_user_services(
                uid="42", service_slugs="pulse", action="destroy")
        api.assert_not_called()
        self.assertIn("must be 'grant' or 'revoke'", out)

    def test_empty_slugs_fails_before_any_request(self):
        with patch.object(admin_server.base, "api_request") as api:
            out = admin_server.su_set_user_services(uid="42", service_slugs=" , ")
        api.assert_not_called()
        self.assertIn("at least one service slug", out)

    def test_backend_error_is_surfaced(self):
        def fake_api(method, path, data=None, params=None):
            return {"error": "service_slugs: This field is required."}

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            out = admin_server.su_set_user_services(uid="42", service_slugs="pulse")
        self.assertIn("service_slugs", out)


class SuSetUserServicesGrantReadback(unittest.TestCase):
    """A grant issued through the set tool becomes visible in the get tool's
    output (stateful fake backend), proving the contract round-trips."""

    def test_grant_is_observable_through_the_get_tool(self):
        grants = {42: set()}

        def fake_api(method, path, data=None, params=None):
            uid = int(path.split("/users/")[1].split("/")[0])
            if method == "POST":
                if data["action"] == "grant":
                    grants.setdefault(uid, set()).update(data["service_slugs"])
                else:
                    grants.setdefault(uid, set()).difference_update(data["service_slugs"])
                return {"ok": True}
            return {
                "results": [
                    {"slug": slug, "name": slug, "is_enabled": True}
                    for slug in sorted(grants[uid])
                ],
            }

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            before = admin_server.su_get_user_services(uid="42")
            admin_server.su_set_user_services(uid="42", service_slugs="pulse")
            after = admin_server.su_get_user_services(uid="42")

        self.assertIn("No services found", before)
        self.assertIn("pulse", after)


if __name__ == "__main__":
    unittest.main()
