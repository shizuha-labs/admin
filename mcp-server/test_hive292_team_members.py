"""HIVE-292 regression: admin_list_team_members must parse the real
TeamViewSet.members response shape {"team", "count", "members": [...]}
(TeamMembershipSerializer rows) — not a bare list or DRF "results" page.

Run: python -m unittest test_hive292_team_members -v  (from mcp-server/)
"""
import unittest
from unittest.mock import patch

import admin_server


def _membership_row(mid, name, email, role="member", title="Engineer", profile=7):
    """A row exactly as TeamMembershipSerializer emits it."""
    return {
        "id": mid,
        "team": 5,
        "team_name": "Engineering",
        "employee_profile": profile,
        "employee_name": name,
        "employee_email": email,
        "employee_title": title,
        "role": role,
        "joined_at": "2026-06-10T12:07:32Z",
        "left_at": None,
        "is_active": True,
    }


# Live response shapes captured for teams 5 (Engineering), 8 (QA),
# 9 (Architecture) — the three IDs from the HIVE-292 report.
TEAM_FIXTURES = {
    "5": {
        "team": "Engineering",
        "count": 2,
        "members": [
            _membership_row(8, "ryo", "ryo@shizuha.com", role="lead"),
            _membership_row(9, "sara", "sara@shizuha.com"),
        ],
    },
    "8": {
        "team": "QA",
        "count": 2,
        "members": [
            _membership_row(18, "rin", "rin@shizuha.com", role="lead", title="QA Engineer"),
            _membership_row(19, "yui", "yui@shizuha.com", title="QA Engineer"),
        ],
    },
    "9": {
        "team": "Architecture",
        "count": 2,
        "members": [
            _membership_row(13, "aoi", "aoi@shizuha.com", role="lead", title="Architect"),
            _membership_row(14, "sora", "sora@shizuha.com", title="Architect"),
        ],
    },
}


class ListTeamMembersParsesMembersKey(unittest.TestCase):
    """The regression: {"members": [...]} responses were read via
    result.get("results") and always rendered "No team members found."."""

    def _call(self, team_id):
        with patch.object(admin_server.base, "api_request",
                          return_value=TEAM_FIXTURES[team_id]):
            return admin_server.list_team_members(
                org_slug="shizuha", team_id=team_id)

    def test_team_5_engineering_not_empty(self):
        out = self._call("5")
        self.assertNotIn("No team members found", out)
        self.assertIn("Team Members (2)", out)
        self.assertIn("ryo", out)
        self.assertIn("(lead)", out)
        self.assertIn("sara", out)

    def test_team_8_qa_not_empty(self):
        out = self._call("8")
        self.assertNotIn("No team members found", out)
        self.assertIn("rin", out)
        self.assertIn("yui", out)

    def test_team_9_architecture_not_empty(self):
        out = self._call("9")
        self.assertNotIn("No team members found", out)
        self.assertIn("aoi", out)
        self.assertIn("sora", out)

    def test_member_detail_fields_rendered(self):
        out = self._call("5")
        self.assertIn("ryo@shizuha.com", out)     # employee_email
        self.assertIn("Member ID: 8", out)        # membership id
        self.assertIn("Employee Profile ID: 7", out)

    def test_summary_and_member_list_agree(self):
        """Contract (sora, HIVE-292): member count in the summary must match
        the rows the member-list tool renders."""
        for team_id, fixture in TEAM_FIXTURES.items():
            out = self._call(team_id)
            self.assertIn(f"Team Members ({fixture['count']})", out)


class ListTeamMembersLegacyShapes(unittest.TestCase):
    """Older/bare shapes must keep working as fallbacks."""

    def test_bare_list_shape(self):
        rows = [_membership_row(1, "kai", "kai@shizuha.com")]
        with patch.object(admin_server.base, "api_request", return_value=rows):
            out = admin_server.list_team_members(org_slug="shizuha", team_id="5")
        self.assertIn("kai", out)

    def test_drf_results_page_shape(self):
        page = {"results": [_membership_row(1, "kai", "kai@shizuha.com")]}
        with patch.object(admin_server.base, "api_request", return_value=page):
            out = admin_server.list_team_members(org_slug="shizuha", team_id="5")
        self.assertIn("kai", out)

    def test_genuinely_empty_team(self):
        with patch.object(admin_server.base, "api_request",
                          return_value={"team": "Empty", "count": 0, "members": []}):
            out = admin_server.list_team_members(org_slug="shizuha", team_id="99")
        self.assertIn("No team members found", out)

    def test_api_error_passthrough(self):
        with patch.object(admin_server.base, "api_request",
                          return_value={"error": "boom"}), \
             patch.object(admin_server.base, "format_error",
                          return_value="Error: boom"):
            out = admin_server.list_team_members(org_slug="shizuha", team_id="5")
        self.assertIn("Error", out)


if __name__ == "__main__":
    unittest.main()
