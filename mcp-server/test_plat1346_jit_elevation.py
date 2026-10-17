"""PLAT-1346: MCP helpers expose the JIT elevated-access request/decision path."""
import unittest
from unittest.mock import patch

import admin_server


class JITElevationMCPTools(unittest.TestCase):
    def test_request_renders_auto_approved_grant(self):
        fixture = {
            'auto_approved': True,
            'grant': {
                'id': 42,
                'status': 'approved',
                'organization_slug': 'shizuha',
                'scope': 'org.members.add',
                'requested_role': 'admin',
                'owning_team': 'admin-platform',
                'expires_at': '2026-07-03T12:00:00Z',
            },
        }
        with patch.object(admin_server.base, 'api_request', return_value=fixture) as api:
            out = admin_server.request_jit_elevation(
                org_slug='shizuha',
                scope='org.members.add',
                reason='audit passed',
                task_key='PLAT-1346',
                ttl_seconds=1800,
            )

        api.assert_called_once()
        self.assertIn('Grant ID: 42', out)
        self.assertIn('Status: approved', out)
        self.assertIn('Auto-approved: True', out)
        self.assertIn('Expires at', out)

    def test_pending_request_points_to_owning_team_not_operator(self):
        fixture = {
            'auto_approved': False,
            'grant': {
                'id': 43,
                'status': 'pending',
                'organization_slug': 'shizuha',
                'scope': 'org.members.owner_transfer',
                'requested_role': 'owner',
                'owning_team': 'security',
            },
        }
        with patch.object(admin_server.base, 'api_request', return_value=fixture):
            out = admin_server.request_jit_elevation(
                org_slug='shizuha',
                scope='org.members.owner_transfer',
                reason='needs review',
                task_key='PLAT-1346',
                requested_role='owner',
                owning_team='security',
            )

        self.assertIn('Owning team: security', out)
        self.assertIn('Pending owning-team approval', out)
        self.assertNotIn('operator', out.lower())

    def test_decide_jit_elevation_calls_action_endpoint(self):
        fixture = {'grant': {'id': 42, 'status': 'revoked'}}
        with patch.object(admin_server.base, 'api_request', return_value=fixture) as api:
            out = admin_server.decide_jit_elevation('42', 'revoke', note='done')

        api.assert_called_once_with('POST', '/jit-elevations/42/revoke/', data={'note': 'done'})
        self.assertIn('JIT grant #42 revoked', out)


if __name__ == '__main__':
    unittest.main()
