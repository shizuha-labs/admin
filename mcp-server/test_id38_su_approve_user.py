"""ID-38 regression: admin_su_approve_user must send status/review_note.

The superuser approve endpoint proxies straight to the id-service
UserApprovalReviewSerializer, which requires `status` ('approved'|'denied')
+ optional `review_note`. The tool previously sent NO body, so the id
serializer rejected it with HTTP 400 "status: This field is required" and no
superuser could approve a pending registration via MCP.

Run: SHIZUHA_ADMIN_URL=http://x python -m unittest test_id38_su_approve_user -v
"""
import unittest
from unittest.mock import patch

import admin_server


class SuApproveUserPayload(unittest.TestCase):
    def _posted_data(self, **kwargs):
        captured = {}

        def fake_api(method, path, data=None, params=None):
            captured["method"] = method
            captured["path"] = path
            captured["data"] = data
            return {"ok": True}

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            admin_server.su_approve_user(**kwargs)
        self.assertEqual(captured["method"], "PATCH")
        self.assertEqual(captured["path"], f"/superuser/users/{kwargs['uid']}/approve/")
        return captured["data"]

    def test_default_sends_status_approved(self):
        data = self._posted_data(uid="253")
        self.assertEqual(data.get("status"), "approved")
        self.assertNotIn("review_note", data)

    def test_deny_sends_status_denied_with_note(self):
        data = self._posted_data(uid="9", approved=False, reason="spam")
        self.assertEqual(data.get("status"), "denied")
        self.assertEqual(data.get("review_note"), "spam")

    def test_no_empty_body_is_sent(self):
        # The bug was an empty/None body; a status must always be present.
        data = self._posted_data(uid="253")
        self.assertTrue(data)
        self.assertIn("status", data)


if __name__ == "__main__":
    unittest.main()
