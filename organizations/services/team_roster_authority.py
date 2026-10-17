"""Pulse-owned fleet roster boundary for Admin team membership (PLS-745)."""

import os

import requests

MIN_FLEET_AGENTS = 10
MIN_ROSTER_TEAMS = 8


class FleetIdentityUnavailable(RuntimeError):
    pass


def fetch_fleet_agent_emails(timeout=3):
    """Return the live ID agent inventory or fail closed."""
    base = os.environ.get(
        'SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api',
    ).rstrip('/')
    try:
        response = requests.get(f'{base}/internal/agents/', timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise FleetIdentityUnavailable(
            'The fleet identity registry is unavailable; Admin will not risk '
            'persisting a competing team edge.'
        ) from exc
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get('agents', payload.get('results', []))
    else:
        raise FleetIdentityUnavailable('The fleet identity registry returned an invalid payload.')
    if not isinstance(rows, list):
        raise FleetIdentityUnavailable('The fleet identity registry returned an invalid agent list.')
    emails = {
        str(row.get('email') or '').strip().lower()
        for row in rows
        if isinstance(row, dict) and row.get('email')
    }
    if len(emails) < MIN_FLEET_AGENTS:
        raise FleetIdentityUnavailable(
            f'The fleet identity registry returned only {len(emails)} agents; '
            'refusing a potentially degraded snapshot.'
        )
    return emails


def _canonical_team(name):
    key = (name or '').strip().lower().replace('_', '-').replace(' ', '-')
    return {
        'analytics': 'research-analytics',
        'research': 'research-analytics',
        'security-triage': 'security',
        'platform-ops': 'devops',
        'trading-engineering': 'engineering',
    }.get(key, key)


def fetch_authoritative_team_members(*, organization_id, organization_slug,
                                     team_name, timeout=3):
    """Return the exact Pulse roster member set; absence is authoritative empty."""
    rows = _fetch_roster_rows(timeout=timeout)
    key = _canonical_team(team_name)
    slug = (organization_slug or '').strip().lower()
    for row in rows:
        if int(row.get('organization_id') or 0) != int(organization_id):
            continue
        if (row.get('organization_slug') or '').strip().lower() != slug:
            continue
        if _canonical_team(row.get('team_name')) != key:
            continue
        members = set()
        for tier in row.get('tiers') or []:
            members.update(
                str(email).strip().lower() for email in (tier or []) if email
            )
        members.update(
            str(email).strip().lower()
            for email in (row.get('junior_emails') or [])
            if email
        )
        return members
    return set()


def fetch_authoritative_roster_all(timeout=3):
    """Return {canonical-team-key: {lower-email...}} across the org.

    Fetches the Pulse roster snapshot ONCE and projects every team, so list
    summaries share the same authoritative semantics as detail reads (and
    authoritative-empty teams are projected as an empty set).
    """
    rows = _fetch_roster_rows(timeout=timeout)
    projected = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        org_id = int(row.get('organization_id') or 0)
        slug = (row.get('organization_slug') or '').strip().lower()
        key = _canonical_team(row.get('team_name'))
        members = set()
        for tier in row.get('tiers') or []:
            members.update(
                str(email).strip().lower() for email in (tier or []) if email
            )
        members.update(
            str(email).strip().lower()
            for email in (row.get('junior_emails') or [])
            if email
        )
        projected[(org_id, slug, key)] = members
    return projected


def _fetch_roster_rows(timeout=3):
    base = os.environ.get(
        'SHIZUHA_PULSE_API_URL', 'http://shizuha-pulse:8002/api',
    ).rstrip('/')
    try:
        response = requests.get(f'{base}/internal/team-roster/', timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise FleetIdentityUnavailable(
            'Pulse TeamRoster is unavailable; Admin will not substitute legacy memberships.'
        ) from exc
    rows = payload.get('teams', []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        raise FleetIdentityUnavailable('Pulse TeamRoster returned an invalid team list.')
    if len(rows) < MIN_ROSTER_TEAMS:
        raise FleetIdentityUnavailable(
            f'Pulse TeamRoster returned only {len(rows)} teams; refusing a '
            'potentially degraded snapshot.'
        )
    return rows


def fleet_agent_write_denial(email):
    """Return a typed rejection payload when ``email`` is a fleet identity."""
    normalized = (email or '').strip().lower()
    if normalized not in fetch_fleet_agent_emails():
        return None
    return {
        'error': 'pulse_team_roster_authority',
        'detail': (
            'Fleet-agent team placement is owned by Pulse TeamRoster. Admin '
            'did not persist a local membership edge.'
        ),
        'email': normalized,
        'pulse_command': {
            'method': 'POST',
            'path': '/pulse/api/admin/team-roster/members/',
            'required': ['command_id', 'expected_version', 'organization_id',
                         'organization_slug', 'team_name', 'action'],
        },
    }
