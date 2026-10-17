"""PLAT-5343 slice 1 — Admin v2 membership composition (HLD v12 §4.3).

``POST /api/internal/v2/project-memberships:resolve`` replaces the circular
v1 path (ID → Admin → Pulse → Admin) with the acyclic composition:

    ID (assertion) → Admin v2 → Pulse v2 snapshot (zero outbound) → Admin composes

For the asserted subject Admin performs **one** local query for active
``OrganizationMembership`` rows, calls the Pulse v2 snapshot route **once**,
and authorizes each candidate when either

1. its ``organization_id`` is in the local Admin membership set, or
2. the same organization is present in the subject-bound Pulse
   ``roster_org_evidence``.

Exact parity with the current internal membership check (§4.3):
``is_active=True`` is required; ``is_pending`` and organization activity are
NOT silently reinterpreted. An Admin row matches when its non-null ``user_id``
equals ``sub``; the exact asserted-email fallback applies only when the row's
``user_id IS NULL``; a conflicting non-null user ID is denied and counted as a
fixed-enum anomaly — the ONLY permitted deliberate difference from the old OR
query (§4.4 step 2).

Every failure mode — Pulse timeout, Admin query failure, expired/mismatched
assertion, invalid snapshot, duplicate project/role conflict — returns a
typed non-200. None may become ``200 + []`` (PLAT-5338 class). Authoritative
empty remains a valid 200 only when the complete v2 snapshot and the local
query both succeeded and the intersection is genuinely empty.

Once v2 is selected there is NO fallback to the circular v1 path (§4.4
step 3). The v1 route is retained untouched until caller inventory proves
zero users (§4.4 steps 4–5).
"""
import logging
import os
from datetime import datetime, timezone as dt_timezone

import requests as http_requests
from django.db import models
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import OrganizationMembership
from . import security_events
from .subject_assertion import (
    SubjectAssertionRejected,
    authenticate_id_assertion,
    emit_derivative_assertion,
    pulse_hop_credential,
)

logger = logging.getLogger('organizations.membership_v2')

SNAPSHOT_SCHEMA = 'shizuha.pulse.project-membership-candidates.v2'

# §5.1 membership-provider budget class: cooperative 350 ms / wire 500 ms.
# Reuses the exact v1 proxy budget (SHIZUHA_PULSE_CONNECT/READ_TIMEOUT) so the
# mint-path envelope is unchanged by the cutover.
def _pulse_v2_timeout():
    return (
        float(os.environ.get('SHIZUHA_PULSE_CONNECT_TIMEOUT', '0.25')),
        float(os.environ.get('SHIZUHA_PULSE_READ_TIMEOUT', '0.5')),
    )


# A snapshot older than this is stale evidence (generous against pod clock
# drift — the freshness contract is valid_for_ms + immediate use; this only
# catches replayed/cached bodies).
SNAPSHOT_MAX_AGE_SECONDS = 30


def _subject_fingerprint(issuer, subject, email):
    """Same construction as the Pulse hop module (issuer|sub|email → sha256)."""
    import hashlib
    material = f'{issuer}|{int(subject)}|{(email or "").strip().lower()}'
    return 'sha256:' + hashlib.sha256(material.encode('utf-8')).hexdigest()


def resolve_local_admin_orgs(subject_id, email):
    """One local query for active OrganizationMembership rows (§4.3).

    Returns ``(admin_org_ids, conflict_count)``. A row matches when its
    non-null ``user_id`` equals ``sub``; the exact asserted-email fallback
    applies only when the row's ``user_id IS NULL``; a conflicting non-null
    user ID matched by email is denied and counted (fixed-enum anomaly).
    """
    q = models.Q(user_id=subject_id)
    if email:
        q |= models.Q(user_email__iexact=email)
    rows = list(
        OrganizationMembership.objects
        .filter(q, is_active=True)
        .values_list('organization_id', 'user_id', 'user_email')
    )
    admin_orgs = set()
    conflicts = 0
    for org_id, row_user_id, row_email in rows:
        if row_user_id == subject_id:
            admin_orgs.add(org_id)
        elif row_user_id is None and email and str(row_email or '').strip().lower() == email:
            admin_orgs.add(org_id)
        elif row_user_id is not None:
            # Non-null user_id conflicting with sub, matched by email: denied.
            conflicts += 1
    return admin_orgs, conflicts


class SnapshotRejected(Exception):
    """The Pulse v2 snapshot failed validation (fixed reason + anomaly kind)."""

    def __init__(self, reason, anomaly=None):
        self.reason = reason
        self.anomaly = anomaly
        super().__init__(reason)


def validate_snapshot(body, expected_fingerprint):
    """Validate the Pulse v2 snapshot; returns (candidates, roster_org_ids).

    Raises :class:`SnapshotRejected` with a fixed reason on any malformation,
    staleness, duplicate conflict, or fingerprint mismatch.
    """
    if not isinstance(body, dict):
        raise SnapshotRejected('not_an_object')
    if body.get('schema') != SNAPSHOT_SCHEMA:
        raise SnapshotRejected('unknown_schema')
    if body.get('subject_fingerprint') != expected_fingerprint:
        raise SnapshotRejected('fingerprint_mismatch', 'fingerprint_mismatch')

    generated_at = body.get('generated_at')
    if not isinstance(generated_at, str):
        raise SnapshotRejected('missing_generated_at')
    try:
        generated = datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
    except ValueError:
        raise SnapshotRejected('malformed_generated_at')
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=dt_timezone.utc)
    age = (datetime.now(dt_timezone.utc) - generated).total_seconds()
    if age > SNAPSHOT_MAX_AGE_SECONDS or age < -SNAPSHOT_MAX_AGE_SECONDS:
        raise SnapshotRejected('stale_snapshot', 'stale_snapshot')

    valid_for = body.get('valid_for_ms')
    if not isinstance(valid_for, int) or valid_for <= 0:
        raise SnapshotRejected('malformed_valid_for_ms')

    candidates = body.get('candidates')
    if not isinstance(candidates, list):
        raise SnapshotRejected('malformed_candidates')
    seen_projects = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise SnapshotRejected('malformed_candidate')
        project_id = candidate.get('project_id')
        org_id = candidate.get('organization_id')
        role = candidate.get('role')
        if not isinstance(project_id, int) or isinstance(project_id, bool):
            raise SnapshotRejected('malformed_candidate')
        if org_id is not None and (not isinstance(org_id, int) or isinstance(org_id, bool)):
            raise SnapshotRejected('malformed_candidate')
        if not isinstance(role, str) or not role:
            raise SnapshotRejected('malformed_candidate')
        if project_id in seen_projects:
            # Pulse dedups per project; duplicates are malformed evidence.
            raise SnapshotRejected('duplicate_project_candidate', 'duplicate_project_candidate')
        seen_projects.add(project_id)

    roster_evidence = body.get('roster_org_evidence')
    if not isinstance(roster_evidence, list):
        raise SnapshotRejected('malformed_roster_evidence')
    roster_org_ids = set()
    seen_roster_orgs = set()
    for entry in roster_evidence:
        if not isinstance(entry, dict):
            raise SnapshotRejected('malformed_roster_evidence')
        org_id = entry.get('organization_id')
        rows = entry.get('roster_rows')
        if not isinstance(org_id, int) or isinstance(org_id, bool):
            raise SnapshotRejected('malformed_roster_evidence')
        if not isinstance(rows, list):
            raise SnapshotRejected('malformed_roster_evidence')
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('id'), int) \
                    or not isinstance(row.get('version'), int):
                raise SnapshotRejected('malformed_roster_evidence')
        if org_id in seen_roster_orgs:
            raise SnapshotRejected('duplicate_roster_org')
        seen_roster_orgs.add(org_id)
        roster_org_ids.add(org_id)

    return candidates, roster_org_ids


class ProjectMembershipResolveV2View(APIView):
    """ID-facing v2 composition endpoint (HLD §4.3). Fail-closed auth."""

    # Authentication is enforced in-view (fail-closed, typed rejections).
    permission_classes = [permissions.AllowAny]

    def _unavailable(self, reason):
        security_events.record_project_membership_projection_v2('unavailable')
        logger.error('PLAT-5343 v2 projection unavailable (%s); typed 503', reason)
        response = Response(
            {
                'error': 'project_membership_unavailable',
                'detail': (
                    'shizuha-pulse did not answer the v2 snapshot request with a '
                    'usable response. admin has no authoritative projection to '
                    'return and will not answer with an empty one. Retry.'
                ),
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        response['Retry-After'] = '1'
        return response

    def _snapshot_rejected(self, reason):
        security_events.record_project_membership_projection_v2('snapshot_rejected')
        logger.error('PLAT-5343 v2 snapshot rejected (%s); typed 502', reason)
        return Response(
            {
                'error': 'project_membership_snapshot_rejected',
                'detail': (
                    'shizuha-pulse answered, but the v2 snapshot failed validation '
                    '(schema, freshness, fingerprint, or shape). admin will not '
                    'compose from untrusted evidence.'
                ),
                'reason': reason,
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    def post(self, request):
        try:
            principal, claims, parent_assertion = authenticate_id_assertion(
                request, body=getattr(request, 'data', None),
            )
        except SubjectAssertionRejected as exc:
            security_events.record_project_membership_projection_v2('auth_rejected')
            logger.warning('PLAT-5343 v2 resolve rejected service=%s reason=%s',
                           (request.META.get('HTTP_X_INTERNAL_SERVICE', '') or '').strip(),
                           exc.reason)
            return Response(
                {'error': 'internal_service_auth_failed', 'reason': exc.reason},
                status=401,
            )

        subject_id = claims['sub']
        email = claims.get('email')

        # --- One local query: active Admin membership rows (§4.3) ------------
        try:
            admin_orgs, conflicts = resolve_local_admin_orgs(subject_id, email)
        except Exception:
            logger.exception('PLAT-5343 v2 local membership query failed; typed 503')
            return self._unavailable('local_query_failed')
        for _ in range(conflicts):
            security_events.record_membership_v2_anomaly(
                'conflicting_non_null_user_id_email_row')

        # --- Exactly one Pulse v2 call (§10 gate 3 Admin half) ---------------
        try:
            derivative = emit_derivative_assertion(parent_assertion, claims)
        except SubjectAssertionRejected:
            logger.error('PLAT-5343 v2 derivative emission unavailable (no signing key)')
            return self._unavailable('derivative_signing_unconfigured')

        pulse_url = os.environ.get('SHIZUHA_PULSE_API_URL', 'http://shizuha-pulse:8002/api')
        try:
            resp = http_requests.post(
                f'{pulse_url}/internal/v2/project-membership-candidates:resolve',
                json={},
                headers={
                    'X-Internal-Service': 'shizuha-admin',
                    'X-Internal-Service-Token': pulse_hop_credential(),
                    'X-Shizuha-Subject-Assertion': derivative,
                },
                timeout=_pulse_v2_timeout(),
            )
        except Exception as exc:
            return self._unavailable(f'{type(exc).__name__}: {exc}')

        if resp.status_code != 200:
            return self._unavailable(f'pulse HTTP {resp.status_code}')

        try:
            body = resp.json()
        except Exception:
            security_events.record_project_membership_projection_v2('malformed')
            logger.warning('PLAT-5343 v2 pulse snapshot unparseable')
            return self._snapshot_rejected('unparseable_body')

        expected_fingerprint = _subject_fingerprint('shizuha-admin', subject_id, email)
        try:
            candidates, roster_orgs = validate_snapshot(body, expected_fingerprint)
        except SnapshotRejected as exc:
            if exc.anomaly:
                security_events.record_membership_v2_anomaly(exc.anomaly)
            return self._snapshot_rejected(exc.reason)

        # --- Composition (§4.3): local Admin set ∪ subject-bound roster ------
        project_memberships = {}
        for candidate in candidates:
            org_id = candidate['organization_id']
            if org_id is None:
                # A null-org candidate was never authorizable in v1 either.
                continue
            if org_id in admin_orgs or org_id in roster_orgs:
                project_memberships[str(candidate['project_id'])] = candidate['role']

        project_ids = sorted(int(pid) for pid in project_memberships)
        if not project_ids:
            security_events.record_project_membership_projection_v2('authoritative_empty')
        else:
            security_events.record_project_membership_projection_v2('served')

        return Response({
            'project_memberships': project_memberships,
            'project_ids': project_ids,
        })
