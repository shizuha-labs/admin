"""PLAT-1341 regression: admin_invite_member must send `user_email` (the field
OrganizationMemberInviteSerializer requires), never `email` — sending `email`
always 400s ("user_email: This field is required"), so no agent could invite an
org member via MCP and org-membership work mis-escalated to the operator.

Run: SHIZUHA_ADMIN_URL=http://x python -m unittest test_plat1341_invite_member -v
"""
import unittest
from unittest.mock import patch

import admin_server


class InviteMemberPayloadMapping(unittest.TestCase):

    def test_email_arg_is_sent_as_user_email(self):
        """The MCP arg stays `email`, but the wire payload key must be
        `user_email` (the serializer contract) or the API returns 400."""
        calls = []

        def fake_api(method, path, data=None, params=None):
            calls.append((method, path, data, params))
            return {"user_email": "new@shizuha.com", "role": "member", "status": "invited"}

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            out = admin_server.invite_member(
                org_slug="shizuha", email="new@shizuha.com", role="member")

        post = next(c for c in calls if c[0] == "POST")
        self.assertEqual(post[1], "/organizations/shizuha/members/")
        # The load-bearing assertion: payload uses user_email, not email.
        self.assertEqual(post[2], {"user_email": "new@shizuha.com", "role": "member"})
        self.assertNotIn("email", post[2])
        self.assertIn("new@shizuha.com", out)

    def test_default_role_is_member(self):
        calls = []

        def fake_api(method, path, data=None, params=None):
            calls.append((method, path, data, params))
            return {"user_email": "x@shizuha.com", "role": "member"}

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            admin_server.invite_member(org_slug="shizuha", email="x@shizuha.com")

        post = next(c for c in calls if c[0] == "POST")
        self.assertEqual(post[2], {"user_email": "x@shizuha.com", "role": "member"})

    def test_api_error_is_surfaced(self):
        with patch.object(admin_server.base, "api_request",
                          return_value={"error": "boom"}):
            out = admin_server.invite_member(
                org_slug="shizuha", email="y@shizuha.com", role="admin")
        # format_error output is returned rather than a success string.
        self.assertNotIn("Invitation sent", out)


if __name__ == "__main__":
    unittest.main()
