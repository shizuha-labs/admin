"""
PLAT-4220 — make the admin org-chart DERIVE agent task-team membership from the
Pulse roster (the single source of truth), so the two can't silently split-brain.

The Pulse ``TeamRoster`` is authoritative for *which agent is on which task
team*. This command reconciles admin ``TeamMembership`` to agree with it, but
**only** for the safe, unambiguous subset:

  * only AGENT accounts are touched (account_type=agent, fetched from ID) — human
    employees (incl. the CEO in Admin Ops / governance bodies) are never touched;
  * admin team names are normalized through the same compatibility aliases as
    Pulse. In particular, ``Research`` and ``Analytics`` both map to the one
    canonical ``research-analytics`` roster (operator 2026-07-16);
  * governance / council / infra teams that have no Pulse counterpart are left
    alone;
  * it is DEACTIVATE-ONLY: it soft-removes an agent from a mapped task team where
    Pulse does not place them. It never fabricates HR records by adding
    memberships. This eliminates the visible split-brain (agents shown in wrong /
    too-many teams) without destroying the richer HR/governance structure.

Data sources (both in-cluster, network-secured):
  * agents:  GET {SHIZUHA_ID_API_URL}/internal/agents/
  * roster:  GET {SHIZUHA_PULSE_API_URL}/internal/team-roster/

Usage:
    python manage.py reconcile_agent_task_teams            # dry-run (default)
    python manage.py reconcile_agent_task_teams --apply    # execute
    python manage.py reconcile_agent_task_teams --apply --force   # bypass sanity guards
"""
import os
import logging

import requests
from django.core.management.base import BaseCommand
from django.utils import timezone

from organizations.models import TeamMembership

logger = logging.getLogger(__name__)

# Sanity guards — an auto-reconcile that mass-deactivates because an upstream
# fetch returned empty would be a self-inflicted outage. Refuse to apply if the
# inputs look degenerate or the change is implausibly large.
MIN_ROSTER_TEAMS = 8       # the live roster has ~28 active teams
MIN_AGENTS = 10            # the fleet has ~60 agents
MAX_DEACTIVATE_FRACTION = 0.6  # of agent memberships in mapped teams


def _norm(s):
    value = ''.join(c for c in (s or '').lower() if c.isalnum())
    return {
        # Operator 2026-07-16: Admin uses the short human-facing name while
        # Pulse persists the consolidated routing slug.
        'analytics': 'researchanalytics',
        'research': 'researchanalytics',
    }.get(value, value)


def build_pulse_index(teams):
    """teams: list of {team_name, tiers, junior_emails} -> {norm_name: set(email)}."""
    idx = {}
    for t in teams or []:
        emails = set()
        for tier in (t.get('tiers') or []):
            for e in (tier or []):
                if e:
                    emails.add(e.strip().lower())
        for e in (t.get('junior_emails') or []):
            if e:
                emails.add(e.strip().lower())
        idx.setdefault(_norm(t.get('team_name')), set()).update(emails)
    return idx


def compute_deactivations(memberships, pulse_index, agent_emails):
    """memberships: iterable of (id, email, team_name, is_active).

    Returns the list of {id, email, team} to soft-deactivate: AGENT memberships
    in a mapped task team where Pulse (SoT) does not place them. Humans, unknown
    identities, and teams without a Pulse counterpart are preserved.
    """
    out = []
    for mid, email, team_name, active in memberships:
        if not active:
            continue
        e = (email or '').strip().lower()
        if e not in agent_emails:      # human / unknown -> preserve
            continue
        n = _norm(team_name)
        if n not in pulse_index:       # governance / infra, no Pulse team -> preserve
            continue
        if e in pulse_index[n]:        # correct membership -> keep
            continue
        out.append({'id': mid, 'email': e, 'team': team_name})
    return out


def _mapped_agent_membership_count(memberships, pulse_index, agent_emails):
    n = 0
    for _mid, email, team_name, active in memberships:
        if active and (email or '').strip().lower() in agent_emails and _norm(team_name) in pulse_index:
            n += 1
    return n


class Command(BaseCommand):
    help = 'Reconcile admin agent task-team membership to the Pulse roster (PLAT-4220).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Execute deactivations (default: dry-run).')
        parser.add_argument('--force', action='store_true', help='Bypass the sanity guards.')
        parser.add_argument('--timeout', type=int, default=10)

    def _fetch_agents(self, timeout):
        url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api').rstrip('/')
        resp = requests.get(f'{url}/internal/agents/', timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        rows = data.get('agents', data if isinstance(data, list) else data.get('results', []))
        return {(r.get('email') or '').strip().lower() for r in rows if r.get('email')}

    def _fetch_roster(self, timeout):
        url = os.environ.get('SHIZUHA_PULSE_API_URL', 'http://shizuha-pulse:8002/api').rstrip('/')
        resp = requests.get(f'{url}/internal/team-roster/', timeout=timeout)
        resp.raise_for_status()
        return resp.json().get('teams', [])

    def _load_memberships(self):
        rows = []
        qs = TeamMembership.objects.filter(is_active=True, team__is_active=True).select_related('team', 'employee_profile', 'employee_profile__membership')
        for tm in qs:
            ep = tm.employee_profile
            email = None
            m = getattr(ep, 'membership', None)
            if m:
                email = getattr(m, 'user_email', None) or getattr(m, 'email', None)
            email = email or getattr(ep, 'work_email', None)
            rows.append((tm.id, email, tm.team.name, tm.is_active))
        return rows

    def handle(self, *args, **options):
        timeout = options['timeout']
        apply = options['apply']
        force = options['force']

        agents = self._fetch_agents(timeout)
        teams = self._fetch_roster(timeout)
        pulse_index = build_pulse_index(teams)
        memberships = self._load_memberships()

        self.stdout.write(f"agents={len(agents)} roster_teams={len(pulse_index)} active_memberships={len(memberships)}")

        # --- sanity guards ---
        problems = []
        if len(agents) < MIN_AGENTS:
            problems.append(f"agent set too small ({len(agents)} < {MIN_AGENTS}) — ID fetch degraded?")
        if len(pulse_index) < MIN_ROSTER_TEAMS:
            problems.append(f"roster too small ({len(pulse_index)} < {MIN_ROSTER_TEAMS}) — Pulse fetch degraded?")

        deacts = compute_deactivations(memberships, pulse_index, agents)
        mapped_total = _mapped_agent_membership_count(memberships, pulse_index, agents)
        if mapped_total and len(deacts) > MAX_DEACTIVATE_FRACTION * mapped_total:
            problems.append(
                f"would deactivate {len(deacts)}/{mapped_total} mapped agent memberships "
                f"(> {int(MAX_DEACTIVATE_FRACTION*100)}%) — refusing as implausible")

        for d in deacts:
            self.stdout.write(f"  DEACTIVATE  {d['email']:30} x {d['team']}")
        self.stdout.write(f"total deactivations: {len(deacts)} (of {mapped_total} mapped agent memberships)")

        if problems:
            for p in problems:
                self.stderr.write(self.style.ERROR(f"GUARD: {p}"))
            if apply and not force:
                self.stderr.write(self.style.ERROR("Aborting --apply due to guards (use --force to override)."))
                return

        if not apply:
            self.stdout.write(self.style.WARNING("dry-run (pass --apply to execute)"))
            return

        now = timezone.now()
        ids = [d['id'] for d in deacts]
        done = 0
        for tm in TeamMembership.objects.filter(id__in=ids, is_active=True):
            tm.is_active = False
            tm.left_at = now
            tm.save(update_fields=['is_active', 'left_at'])
            done += 1
        self.stdout.write(self.style.SUCCESS(f"deactivated {done} false agent task-team memberships"))
