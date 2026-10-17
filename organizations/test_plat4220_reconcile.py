"""PLAT-4220: the agent task-team reconcile derives from the Pulse roster
safely — deactivate-only, agents-only, mapped-teams-only. Pure-logic tests
(no DB)."""
from django.test import SimpleTestCase
from unittest.mock import Mock, patch

from organizations.management.commands.reconcile_agent_task_teams import (
    build_pulse_index, compute_deactivations, _norm,
)
from organizations.services.team_roster_authority import (
    FleetIdentityUnavailable,
    fetch_authoritative_team_members,
    fetch_fleet_agent_emails,
)

ROSTER = [
    {'team_name': 'customer-support', 'tiers': [['cora@shizuha.com', 'rin@shizuha.com', 'scout@shizuha.com']], 'junior_emails': []},
    {'team_name': 'admin-ops', 'tiers': [['shion@shizuha.com', 'shizuha@shizuha.com']], 'junior_emails': []},
    {'team_name': 'design', 'tiers': [['lina@shizuha.com']], 'junior_emails': []},
]
AGENTS = {'cora@shizuha.com', 'rin@shizuha.com', 'scout@shizuha.com',
          'shion@shizuha.com', 'shizuha@shizuha.com', 'lina@shizuha.com'}


class ReconcileLogicTests(SimpleTestCase):
    def setUp(self):
        self.idx = build_pulse_index(ROSTER)

    def test_norm_matches_spaced_and_hyphenated(self):
        self.assertEqual(_norm('Customer Support'), 'customersupport')
        self.assertEqual(_norm('customer-support'), 'customersupport')

    def test_research_labels_map_to_one_canonical_team(self):
        self.assertEqual(_norm('Research'), 'researchanalytics')
        self.assertEqual(_norm('Analytics'), 'researchanalytics')
        self.assertEqual(_norm('Research Analytics'), 'researchanalytics')

    def test_index_flattens_tiers_and_juniors(self):
        self.assertEqual(self.idx['customersupport'],
                         {'cora@shizuha.com', 'rin@shizuha.com', 'scout@shizuha.com'})

    def test_false_agent_membership_is_deactivated(self):
        # scout is only in customer-support per Pulse; his 'Accounting'/'Design'
        # admin memberships are false -> deactivated. 'Customer Support' kept.
        mems = [
            (1, 'scout@shizuha.com', 'Customer Support', True),
            (2, 'scout@shizuha.com', 'Accounting', True),
            (3, 'scout@shizuha.com', 'Design', True),
        ]
        d = compute_deactivations(mems, self.idx, AGENTS)
        # Accounting has no Pulse counterpart here -> preserved; Design maps and
        # scout is NOT in Pulse design -> deactivated.
        killed = {(x['team']) for x in d}
        self.assertIn('Design', killed)
        self.assertNotIn('Customer Support', killed)
        self.assertNotIn('Accounting', killed)  # unmapped team preserved

    def test_correct_membership_is_kept(self):
        mems = [(1, 'lina@shizuha.com', 'Design', True)]
        self.assertEqual(compute_deactivations(mems, self.idx, AGENTS), [])

    def test_human_in_mapped_team_is_never_touched(self):
        # A human (not in the agent set) sitting in a mapped task team where the
        # roster does not list them — e.g. the CEO in Admin Ops — is preserved.
        mems = [(9, 'test-owner@example.com', 'Admin Ops', True)]
        self.assertEqual(compute_deactivations(mems, self.idx, AGENTS), [])

    def test_governance_team_without_pulse_counterpart_is_preserved(self):
        mems = [(7, 'scout@shizuha.com', 'Executive Council', True)]
        self.assertEqual(compute_deactivations(mems, self.idx, AGENTS), [])

    def test_inactive_membership_ignored(self):
        mems = [(5, 'scout@shizuha.com', 'Design', False)]
        self.assertEqual(compute_deactivations(mems, self.idx, AGENTS), [])

    @patch('organizations.services.team_roster_authority.requests.get')
    def test_agent_inventory_fails_closed_on_degraded_empty_success(self, get):
        get.return_value = Mock(
            json=lambda: {'agents': []},
            raise_for_status=lambda: None,
        )

        with self.assertRaises(FleetIdentityUnavailable):
            fetch_fleet_agent_emails()

    @patch('organizations.services.team_roster_authority.requests.get')
    def test_roster_projection_fails_closed_on_degraded_empty_success(self, get):
        get.return_value = Mock(
            json=lambda: {'teams': []},
            raise_for_status=lambda: None,
        )

        with self.assertRaises(FleetIdentityUnavailable):
            fetch_authoritative_team_members(
                organization_id=1,
                organization_slug='shizuha',
                team_name='engineering',
            )
