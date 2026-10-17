"""PLS-770 regression: admin_list_team_members must dedupe the same identity
when a Pulse routing row coexists with a directory lead edge, so a person is
never presented twice as two team members.

Run: SHIZUHA_ADMIN_URL=http://x python -m unittest test_pls770_mcp_flattening -v
"""
import unittest
from unittest.mock import patch

import admin_server


class PLS770McpFlattening(unittest.TestCase):

    def _rows(self):
        return [
            {
                'id': 1,
                'employee_name': 'Hritik (routing)',
                'employee_email': 'test-owner@example.com',
                'role': 'member',
                'source': 'pulse-team-roster',
                'routing_member': True,
            },
            {
                'id': 2,
                'employee_name': 'Hritik (directory)',
                'employee_email': 'test-owner@example.com',
                'role': 'lead',
                'source': 'admin-directory',
                'routing_member': False,
            },
        ]

    def test_same_identity_deduplicated_with_routing_typing_preserved(self):
        with patch.object(
            admin_server.base, "api_request", return_value={
                'team': 'CEO Decisions',
                'count': 2,
                'routing_count': 1,
                'directory_count': 1,
                'members': self._rows(),
            }
        ):
            out = admin_server.list_team_members('shizuha', '13')

        # One identity, one line; routing supersedes directory.
        self.assertIn('# Team Members (1)', out)
        self.assertEqual(out.count('test-owner@example.com'), 1)
        self.assertIn('source=pulse-team-roster', out)
        self.assertIn('routing=true', out)
        self.assertNotIn('source=admin-directory', out)

    def test_separate_identities_both_kept(self):
        rows = self._rows() + [{
            'id': 3,
            'employee_name': 'Sara',
            'employee_email': 'sara@shizuha.com',
            'role': 'member',
            'source': 'pulse-team-roster',
            'routing_member': True,
        }]
        with patch.object(
            admin_server.base, "api_request", return_value={
                'team': 'QA',
                'count': 3,
                'routing_count': 2,
                'directory_count': 1,
                'members': rows,
            }
        ):
            out = admin_server.list_team_members('shizuha', '8')

        self.assertIn('# Team Members (2)', out)
        self.assertEqual(out.count('test-owner@example.com'), 1)
        self.assertIn('sara@shizuha.com', out)


if __name__ == '__main__':
    unittest.main()
