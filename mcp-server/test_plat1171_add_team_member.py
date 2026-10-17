"""PLAT-1171 regression: admin_add_team_member must send employee_profile_id
(the field TeamMemberAddSerializer requires), never a raw user_id payload.

Run: SHIZUHA_ADMIN_URL=http://x python -m unittest test_plat1171_add_team_member -v
"""
import unittest
from unittest.mock import patch

import admin_server


EMPLOYEES_PAGE = {
    "count": 2,
    "next": None,
    "results": [
        {"id": 73, "user_id": 15, "display_name": "zen", "user_email": "zen@shizuha.com"},
        {"id": 74, "user_id": 16, "display_name": "kai", "user_email": "kai@shizuha.com"},
    ],
}


class AddTeamMemberPayloadMapping(unittest.TestCase):

    def test_user_id_resolved_to_employee_profile_id(self):
        """The 2026-07-02 game-day failure: user_id=15 must become
        employee_profile_id=73 in the POST payload."""
        calls = []

        def fake_api(method, path, data=None, params=None):
            calls.append((method, path, data, params))
            if method == "GET":
                return EMPLOYEES_PAGE
            return {"id": 99, "employee_profile": 73, "employee_name": "zen", "role": "member"}

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            out = admin_server.add_team_member(
                org_slug="shizuha", team_id="29", user_id="15")

        post = next(c for c in calls if c[0] == "POST")
        self.assertEqual(post[2], {"employee_profile_id": 73, "role": "member"})
        self.assertNotIn("user_id", post[2])
        self.assertIn("zen", out)

    def test_explicit_employee_profile_id_skips_resolution(self):
        calls = []

        def fake_api(method, path, data=None, params=None):
            calls.append((method, path, data, params))
            return {"id": 99, "employee_name": "kai", "role": "lead"}

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            admin_server.add_team_member(
                org_slug="shizuha", team_id="29",
                employee_profile_id="74", role="lead")

        self.assertEqual(len(calls), 1)  # no GET /employees/ round-trip
        self.assertEqual(calls[0][2], {"employee_profile_id": 74, "role": "lead"})

    def test_unknown_user_id_gives_actionable_error(self):
        with patch.object(admin_server.base, "api_request",
                          return_value=EMPLOYEES_PAGE):
            out = admin_server.add_team_member(
                org_slug="shizuha", team_id="29", user_id="9999")
        self.assertIn("no employee profile found", out)
        self.assertIn("admin_create_employee", out)

    def test_no_reference_at_all_errors(self):
        out = admin_server.add_team_member(org_slug="shizuha", team_id="29")
        self.assertIn("pass user_id or employee_profile_id", out)


if __name__ == "__main__":
    unittest.main()
