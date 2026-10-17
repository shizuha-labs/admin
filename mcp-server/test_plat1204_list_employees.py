"""PLAT-1204 regression: admin_list_employees must render EmployeeProfileSerializer
rows (display_name / user_email / user_id / position_title), not the stale
first_name/last_name/email keys that made every row show Unknown / N/A and hid
the user IDs needed for admin_add_team_member.

Recovers the renderer hunk from PR #24 (closed as duplicate of #23 for the
write path, but its list_employees fix was real). See PLAT-1171.

Run: SHIZUHA_ADMIN_URL=http://x python -m unittest test_plat1204_list_employees -v
"""
import unittest
from unittest.mock import patch

import admin_server


def _profile_row(pid, user_id, display_name, email, position="Engineer"):
    """Shape emitted by EmployeeProfileSerializer (organizations/serializers.py)."""
    return {
        "id": pid,
        "user_id": user_id,
        "user_email": email,
        "display_name": display_name,
        "department_name": "Engineering",
        "position_title": position,
        "employment_status": "active",
    }


def _live_list_row(pid, user_id, display_name, email, job_title=None):
    """Shape observed on the LIVE list endpoint 2026-07-02 (lighter serializer):
    job_title instead of position_title, department/position keys absent or
    null."""
    return {
        "id": pid,
        "user_id": user_id,
        "user_email": email,
        "display_name": display_name,
        "job_title": job_title,
        "position_title": None,
        "department_name": None,
        "employment_status": "active",
        "role": "member",
        "avatar_url": None,
    }


class ListEmployeesRenderer(unittest.TestCase):

    def test_employee_profile_rows_render_name_email_and_user_id(self):
        """The 2026-07-02 live failure: every row was Unknown / N/A."""
        page = {"count": 2, "next": None, "results": [
            _profile_row(73, 15, "zen", "zen@shizuha.com"),
            _profile_row(74, 16, "kai", "kai@shizuha.com", position="Reviewer"),
        ]}
        with patch.object(admin_server.base, "api_request", return_value=page):
            out = admin_server.list_employees(org_slug="shizuha")

        self.assertNotIn("Unknown", out)
        self.assertNotIn("N/A", out)
        self.assertIn("**zen**", out)
        self.assertIn("User ID: 15", out)
        self.assertIn("zen@shizuha.com", out)
        self.assertIn("Position: Reviewer", out)
        self.assertIn("Department: Engineering", out)

    def test_live_list_row_shape_renders_with_null_fields(self):
        """Live list serializer: job_title carries the position; department/
        position keys present but null must fall back to N/A, not print None."""
        page = {"count": 1, "next": None, "results": [
            _live_list_row(74, 17, "Akira", "akira@shizuha.com", job_title="Security"),
        ]}
        with patch.object(admin_server.base, "api_request", return_value=page):
            out = admin_server.list_employees(org_slug="shizuha")

        self.assertIn("**Akira**", out)
        self.assertIn("User ID: 17", out)
        self.assertIn("akira@shizuha.com", out)
        self.assertIn("Position: Security", out)
        self.assertIn("Department: N/A", out)
        self.assertNotIn("None", out)

    def test_legacy_row_shape_still_renders(self):
        page = {"count": 1, "next": None, "results": [{
            "id": 5,
            "first_name": "Old",
            "last_name": "Shape",
            "email": "old@shizuha.com",
            "department": "Ops",
            "position": "Admin",
            "status": "inactive",
        }]}
        with patch.object(admin_server.base, "api_request", return_value=page):
            out = admin_server.list_employees(org_slug="shizuha")

        self.assertIn("**Old Shape**", out)
        self.assertIn("old@shizuha.com", out)
        self.assertIn("Position: Admin", out)
        self.assertIn("Status: inactive", out)
        self.assertNotIn("User ID:", out)  # legacy rows have no user_id

    def test_limit_enforced_client_side(self):
        """Backend paginator ignores page_size; limit must truncate locally."""
        page = {"count": 20, "next": None, "results": [
            _profile_row(i, 100 + i, f"agent-{i}", f"a{i}@shizuha.com")
            for i in range(20)
        ]}
        with patch.object(admin_server.base, "api_request", return_value=page):
            out = admin_server.list_employees(org_slug="shizuha", limit=5)

        self.assertIn("# Employees (5)", out)
        self.assertIn("agent-4", out)
        self.assertNotIn("agent-5", out)


if __name__ == "__main__":
    unittest.main()
