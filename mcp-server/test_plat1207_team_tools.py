"""PLAT-1207 regression: team tools must match the backend API contract.

1. admin_create_team / admin_update_team must send ``lead_id`` (and pass
   ``lead_email`` through) — the old ``lead`` payload key is not a
   TeamSerializer/TeamCreateSerializer field, so DRF silently dropped it and
   teams were created with Lead: None even when a lead was supplied.
2. admin_list_teams must follow DRF pagination (PAGE_SIZE=20, page_size query
   param ignored) instead of rendering only page 1 — the 2026-07-02 failure
   reported "# Teams (20)" while the Admin DB held 35 active teams.

Run: SHIZUHA_ADMIN_URL=http://x python -m unittest test_plat1207_team_tools -v
"""
import unittest
from unittest.mock import patch

import admin_server


def _team_row(tid, name, lead_email=None):
    return {
        "id": tid,
        "name": name,
        "description": "",
        "member_count": 1,
        "lead_email": lead_email,
        "lead_name": lead_email.split("@")[0] if lead_email else None,
    }


def _page(rows, count, next_link):
    return {"count": count, "next": next_link, "previous": None, "results": rows}


class CreateTeamPayloadMapping(unittest.TestCase):

    def test_lead_id_sent_as_lead_id(self):
        calls = []

        def fake_api(method, path, data=None, params=None):
            calls.append((method, path, data))
            return {"id": 41, "name": "Research", "lead_id": 15, "lead_name": "zen"}

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            out = admin_server.create_team(
                org_slug="shizuha", name="Research", lead_id="15")

        self.assertEqual(calls[0][2], {"name": "Research", "lead_id": "15"})
        self.assertNotIn("lead", calls[0][2])
        self.assertIn("zen", out)

    def test_lead_email_passed_through(self):
        calls = []

        def fake_api(method, path, data=None, params=None):
            calls.append((method, path, data))
            return {"id": 41, "name": "Research", "lead_email": "zen@shizuha.com"}

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            admin_server.create_team(
                org_slug="shizuha", name="Research", lead_email="zen@shizuha.com")

        self.assertEqual(
            calls[0][2], {"name": "Research", "lead_email": "zen@shizuha.com"})


class UpdateTeamPayloadMapping(unittest.TestCase):

    def test_lead_id_sent_as_lead_id(self):
        calls = []

        def fake_api(method, path, data=None, params=None):
            calls.append((method, path, data))
            return {"id": 41, "name": "Research", "lead_id": 15}

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            admin_server.update_team(
                org_slug="shizuha", team_id="41", lead_id="15")

        self.assertEqual(calls[0][2], {"lead_id": "15"})
        self.assertNotIn("lead", calls[0][2])

    def test_lead_email_passed_through(self):
        calls = []

        def fake_api(method, path, data=None, params=None):
            calls.append((method, path, data))
            return {"id": 41, "name": "Research"}

        with patch.object(admin_server.base, "api_request", side_effect=fake_api):
            admin_server.update_team(
                org_slug="shizuha", team_id="41", lead_email="zen@shizuha.com")

        self.assertEqual(calls[0][2], {"lead_email": "zen@shizuha.com"})


class ListTeamsPagination(unittest.TestCase):

    PAGES = {
        1: _page([_team_row(i, f"team-{i}") for i in range(1, 21)], 35,
                 "https://host/admin/api/organizations/shizuha/teams/?page=2"),
        2: _page([_team_row(i, f"team-{i}", "lead@shizuha.com")
                  for i in range(21, 36)], 35, None),
    }

    def _fake_api(self, calls):
        def fake_api(method, path, data=None, params=None):
            calls.append((method, path, params))
            page = (params or {}).get("page", 1)
            return self.PAGES[page]
        return fake_api

    def test_all_pages_followed_and_count_accurate(self):
        """The 2026-07-02 failure: 35 active teams, listing showed 20."""
        calls = []
        with patch.object(admin_server.base, "api_request",
                          side_effect=self._fake_api(calls)):
            out = admin_server.list_teams(org_slug="shizuha")

        self.assertEqual(len(calls), 2)
        self.assertIn("# Teams (35)", out)
        self.assertIn("team-1", out)     # page 1
        self.assertIn("team-35", out)    # page 2 — previously hidden

    def test_single_page_needs_one_request(self):
        rows = [_team_row(1, "solo")]
        with patch.object(admin_server.base, "api_request",
                          return_value=_page(rows, 1, None)) as api:
            out = admin_server.list_teams(org_slug="shizuha")
        self.assertEqual(api.call_count, 1)
        self.assertIn("# Teams (1)", out)

    def test_bare_list_shape(self):
        with patch.object(admin_server.base, "api_request",
                          return_value=[_team_row(1, "solo")]):
            out = admin_server.list_teams(org_slug="shizuha")
        self.assertIn("# Teams (1)", out)

    def test_error_passthrough(self):
        with patch.object(admin_server.base, "api_request",
                          return_value={"error": "HTTP 403", "detail": "nope"}):
            out = admin_server.list_teams(org_slug="shizuha")
        self.assertIn("403", out)

    def test_empty(self):
        with patch.object(admin_server.base, "api_request",
                          return_value=_page([], 0, None)):
            out = admin_server.list_teams(org_slug="shizuha")
        self.assertEqual(out, "No teams found.")


if __name__ == "__main__":
    unittest.main()
