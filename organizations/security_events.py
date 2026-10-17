"""PLAT-4133: emit sanitized boundary-denial events to Connect SIEM-lite."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
import uuid

import requests
import redis
from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone

logger = logging.getLogger(__name__)

_SAFE_ID_RE = re.compile(r'^[A-Za-z0-9_.:-]{1,128}$')
_METRIC_OUTCOMES = (
    'success',
    'disabled',
    'missing_secret',
    'unauthenticated_actor',
    'invalid_actor',
    'non_202',
    'timeout',
    'exception',
)
_METRIC_KEY = 'admin:metrics:boundary_security_event:{outcome}'
_JIT_INVARIANT_METRIC_KEY = 'admin:metrics:jit_approval_invariant_failure'
_DEDUPE_KEY = 'admin:security_event_dedupe:{digest}'

# PLAT-5338: project-membership projection outcomes.
#
# `/internal/users/<id>/project-memberships/` mints an AUTHORIZATION claim
# (`project_ids` / `project_roles` on the JWT), so the only interesting states
# are the ones where the answer is not a vouched-for, non-empty projection.
# Only anomalies are recorded: the healthy path (Pulse answered with a
# non-empty projection) does no Redis I/O at all, because this endpoint sits
# inside shizuha-id's 1.0s token-mint budget. The series still render at 0 via
# the mget below, so `absent()` liveness alerting works without hot-path cost.
_PROJECTION_OUTCOMES = (
    # Pulse answered 200 with a well-formed but EMPTY projection. Legitimate for
    # a user who genuinely has no projects — recorded so an operator can tell
    # that case apart from `unavailable` instead of guessing.
    'authoritative_empty',
    # Pulse answered 200 with a payload that is not the claim shape -> 502.
    'malformed',
    # Pulse did not answer (non-200, timeout, connection error). Admin has no
    # authoritative projection, so the request fails closed with a typed 503.
    # This is the counter that stands in for the defect class PLAT-5338 found:
    # before the fix this exact path returned 200 with `project_ids: []`.
    'unavailable',
)
_PROJECTION_METRIC_KEY = 'admin:metrics:project_membership_projection:{outcome}'

# PLAT-5343 slice 1: v2 (acyclic) projection outcomes + fixed-enum anomalies.
# Separate family from v1 so operators can watch the shadow/cutover window
# without mixing semantics. Anomalies are the §4.3 fixed-enum denials.
_PROJECTION_V2_OUTCOMES = (
    'served',
    'authoritative_empty',
    'unavailable',
    'malformed',
    'auth_rejected',
    'snapshot_rejected',
)
_PROJECTION_V2_METRIC_KEY = 'admin:metrics:project_membership_projection_v2:{outcome}'
_V2_ANOMALY_KINDS = (
    # §4.3: a row with a non-null user_id conflicting with the asserted sub
    # that matched by email is denied (the ONLY deliberate v1/v2 difference).
    'conflicting_non_null_user_id_email_row',
    # Pulse returned two candidates for the same project — malformed evidence.
    'duplicate_project_candidate',
    # Snapshot generated_at outside the freshness window.
    'stale_snapshot',
    # Snapshot subject_fingerprint does not match this request's subject.
    'fingerprint_mismatch',
)
_V2_ANOMALY_METRIC_KEY = 'admin:metrics:membership_v2_anomaly:{kind}'


def _metrics_redis_client():
    url = getattr(settings, 'CONNECT_SECURITY_EVENT_METRICS_REDIS_URL', '') or getattr(
        settings, 'CELERY_BROKER_URL', 'redis://redis:6379/3',
    )
    return redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=0.25,
        socket_timeout=0.25,
    )


def record_boundary_event_outcome(outcome: str) -> bool:
    """Persist one bounded producer outcome for independent Prometheus alerting."""
    outcome = outcome if outcome in _METRIC_OUTCOMES else 'exception'
    try:
        _metrics_redis_client().incr(_METRIC_KEY.format(outcome=outcome))
        return True
    except Exception:
        logger.exception('PLAT-4133 failed to persist boundary producer metric outcome=%s', outcome)
        return False


def record_jit_invariant_failure() -> bool:
    """Persist detector liveness independently of the relational audit row."""
    try:
        _metrics_redis_client().incr(_JIT_INVARIANT_METRIC_KEY)
        return True
    except Exception:
        logger.exception('PLAT-4878 failed to persist JIT invariant failure metric')
        return False


def record_project_membership_projection(outcome: str) -> bool:
    """Persist one non-authoritative project-membership projection outcome.

    PLAT-5338. Never raises: a broken metrics backend must not turn a token
    mint into a 500, and must not change the status code the caller sees.
    """
    if outcome not in _PROJECTION_OUTCOMES:
        return False
    try:
        _metrics_redis_client().incr(_PROJECTION_METRIC_KEY.format(outcome=outcome))
        return True
    except Exception:
        logger.exception(
            'PLAT-5338 failed to persist project-membership projection outcome=%s', outcome,
        )
        return False


def record_project_membership_projection_v2(outcome: str) -> bool:
    """Persist one v2 (acyclic) projection outcome (PLAT-5343 slice 1)."""
    if outcome not in _PROJECTION_V2_OUTCOMES:
        return False
    try:
        _metrics_redis_client().incr(_PROJECTION_V2_METRIC_KEY.format(outcome=outcome))
        return True
    except Exception:
        logger.exception('PLAT-5343 failed to persist v2 projection outcome=%s', outcome)
        return False


def record_membership_v2_anomaly(kind: str) -> bool:
    """Persist one fixed-enum v2 composition anomaly (PLAT-5343 §4.3)."""
    if kind not in _V2_ANOMALY_KINDS:
        return False
    try:
        _metrics_redis_client().incr(_V2_ANOMALY_METRIC_KEY.format(kind=kind))
        return True
    except Exception:
        logger.exception('PLAT-5343 failed to persist v2 anomaly kind=%s', kind)
        return False


def render_boundary_event_metrics() -> str:
    counts = None
    projection_counts = None
    jit_invariant_failures = None
    probe_errors = 0
    keys = (
        [_METRIC_KEY.format(outcome=value) for value in _METRIC_OUTCOMES]
        + [_JIT_INVARIANT_METRIC_KEY]
        + [_PROJECTION_METRIC_KEY.format(outcome=value) for value in _PROJECTION_OUTCOMES]
    )
    try:
        client = _metrics_redis_client()
        values = client.mget(keys)
        values = list(values) + [None] * (len(keys) - len(values))
        parsed_counts = {outcome: 0 for outcome in _METRIC_OUTCOMES}
        parsed_counts.update({
            outcome: int(raw or 0)
            for outcome, raw in zip(_METRIC_OUTCOMES, values[:len(_METRIC_OUTCOMES)])
        })
        parsed_jit_invariant_failures = int(values[len(_METRIC_OUTCOMES)] or 0)
        parsed_projection_counts = {outcome: 0 for outcome in _PROJECTION_OUTCOMES}
        parsed_projection_counts.update({
            outcome: int(raw or 0)
            for outcome, raw in zip(
                _PROJECTION_OUTCOMES, values[len(_METRIC_OUTCOMES) + 1:],
            )
        })
        counts = parsed_counts
        jit_invariant_failures = parsed_jit_invariant_failures
        projection_counts = parsed_projection_counts
    except Exception:
        probe_errors = 1
        logger.exception('PLAT-4133 failed to collect boundary producer metrics')
    lines = []
    if counts is not None:
        lines.extend([
            '# HELP platform_boundary_event_producer_total Boundary-denial producer outcomes persisted by service.',
            '# TYPE platform_boundary_event_producer_total counter',
        ])
        lines.extend(
            f'platform_boundary_event_producer_total{{service="admin",outcome="{outcome}"}} {counts[outcome]}'
            for outcome in _METRIC_OUTCOMES
        )
    lines.extend([
        '# HELP platform_boundary_event_producer_probe_errors Producer metric backend collection errors.',
        '# TYPE platform_boundary_event_producer_probe_errors gauge',
        f'platform_boundary_event_producer_probe_errors{{service="admin"}} {probe_errors}',
    ])
    if jit_invariant_failures is not None:
        lines.extend([
            '# HELP platform_jit_approval_invariant_failures_total Persisted exact-team JIT mechanism failures.',
            '# TYPE platform_jit_approval_invariant_failures_total counter',
            f'platform_jit_approval_invariant_failures_total{{service="admin"}} {jit_invariant_failures}',
        ])
    if projection_counts is not None:
        lines.extend([
            '# HELP platform_project_membership_projection_total Non-authoritative project-membership projection outcomes.',
            '# TYPE platform_project_membership_projection_total counter',
        ])
        lines.extend(
            f'platform_project_membership_projection_total{{service="admin",outcome="{outcome}"}} '
            f'{projection_counts[outcome]}'
            for outcome in _PROJECTION_OUTCOMES
        )
    return '\n'.join(lines) + '\n'


def boundary_event_metrics(request):
    return HttpResponse(
        render_boundary_event_metrics(),
        content_type='text/plain; version=0.0.4; charset=utf-8',
    )


def _org_ids(source) -> list[int]:
    ids = set()
    if isinstance(source, dict):
        source = source.keys()
    if isinstance(source, (list, tuple, set, dict)):
        for value in list(source)[:32]:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                ids.add(parsed)
    return sorted(ids)


def _request_org_ids(request) -> list[int]:
    user = getattr(request, 'user', None)
    ids = set(_org_ids(getattr(user, 'organization_memberships', {}) or {}))
    auth = getattr(request, 'auth', None)
    if not ids and isinstance(auth, dict):
        for key in ('organization_memberships', 'organization_ids', 'org_ids'):
            ids.update(_org_ids(auth.get(key)))
        for key in ('organization_id', 'org_id'):
            ids.update(_org_ids([auth.get(key)]))
    return sorted(ids)


def _correlation_id(request) -> str:
    headers = getattr(request, 'headers', {}) or {}
    value = str(headers.get('X-Correlation-ID') or headers.get('X-Request-ID') or '').strip()
    if _SAFE_ID_RE.fullmatch(value):
        return value
    return str(uuid.uuid4())


def emit_boundary_denial(
    *, request, service: str, operation: str, reason: str,
    target_org_id=None, source_org_ids=None, owner_team=None, dedupe_key=None,
) -> bool:
    """Synchronously enqueue one bounded event; never change the caller's 403."""
    dedupe_client = None
    claimed_dedupe_key = None

    def release_failed_claim():
        if dedupe_client is None or claimed_dedupe_key is None:
            return
        try:
            dedupe_client.delete(claimed_dedupe_key)
        except Exception:
            logger.exception(
                'PLAT-4878 failed to release unsuccessful security event dedupe claim',
            )

    try:
        if not bool(getattr(settings, 'CONNECT_SECURITY_EVENT_EMIT_ENABLED', True)):
            record_boundary_event_outcome('disabled')
            return False
        secret = getattr(settings, 'CONNECT_SECURITY_EVENT_ORIGIN_SECRET', '') or ''
        if not secret:
            record_boundary_event_outcome('missing_secret')
            logger.warning('PLAT-4133 boundary event secret is not configured')
            return False

        user = getattr(request, 'user', None)
        if not user or not getattr(user, 'is_authenticated', False):
            record_boundary_event_outcome('unauthenticated_actor')
            return False
        actor_user_id = int(getattr(user, 'id', 0) or 0)
        if actor_user_id <= 0:
            record_boundary_event_outcome('invalid_actor')
            return False
        actor_username = str(
            getattr(user, 'username', '') or getattr(user, 'email', '') or actor_user_id
        )[:150]
        if dedupe_key:
            digest = hashlib.sha256(str(dedupe_key).encode('utf-8')).hexdigest()
            try:
                dedupe_client = _metrics_redis_client()
                claimed_dedupe_key = _DEDUPE_KEY.format(digest=digest)
                claimed = dedupe_client.set(
                    claimed_dedupe_key,
                    '1',
                    nx=True,
                    ex=int(getattr(settings, 'CONNECT_SECURITY_EVENT_DEDUPE_SECONDS', 300)),
                )
                if not claimed:
                    return True
            except Exception:
                # A broken dedupe backend must not suppress the owner notification.
                logger.exception(
                    'PLAT-4878 security event dedupe failed; emitting operation=%s',
                    operation,
                )
        route = operation
        resolver_match = getattr(request, 'resolver_match', None)
        if resolver_match is not None:
            route = getattr(resolver_match, 'view_name', '') or getattr(resolver_match, 'route', '') or route

        payload = {
            'specversion': '1.0',
            'id': str(uuid.uuid4()),
            'source': f'shizuha://{service}',
            'type': 'platform.boundary_denial',
            'time': timezone.now().isoformat(),
            'data': {
                'service': service,
                'operation': operation,
                'reason': reason,
                'actor_user_id': actor_user_id,
                'actor_username': actor_username,
                'source_org_ids': _org_ids(
                    source_org_ids if source_org_ids is not None else _request_org_ids(request)
                ),
                'target_org_id': int(target_org_id) if target_org_id is not None else None,
                'owner_team': str(owner_team or '')[:80],
                'method': str(getattr(request, 'method', 'GET') or 'GET')[:12].upper(),
                'route': str(route)[:160],
                'correlation_id': _correlation_id(request),
            },
        }
        canonical = json.dumps(
            payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        ).encode('utf-8')
        timestamp = int(time.time())
        sender_service = f'shizuha-{service}'
        body_hash = hashlib.sha256(canonical).hexdigest()
        signature = hmac.new(
            secret.encode('utf-8'),
            f'{sender_service}|{timestamp}|{body_hash}'.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        response = requests.post(
            getattr(
                settings,
                'SHIZUHA_CONNECT_SECURITY_EVENT_URL',
                'http://localhost:8019/api/internal/security-events/',
            ),
            json=payload,
            headers={
                'X-Internal-Service': sender_service,
                'X-Security-Event-Timestamp': str(timestamp),
                'X-Security-Event-Signature': signature,
            },
            timeout=float(getattr(settings, 'CONNECT_SECURITY_EVENT_TIMEOUT_SECONDS', 1.0)),
        )
        if response.status_code != 202:
            release_failed_claim()
            record_boundary_event_outcome('non_202')
            logger.error(
                'PLAT-4133 boundary event ingest rejected service=%s operation=%s status=%s',
                service, operation, response.status_code,
            )
            return False
        record_boundary_event_outcome('success')
        return True
    except requests.Timeout:
        release_failed_claim()
        record_boundary_event_outcome('timeout')
        logger.exception(
            'PLAT-4133 boundary event emit timed out service=%s operation=%s',
            service, operation,
        )
        return False
    except Exception:
        release_failed_claim()
        record_boundary_event_outcome('exception')
        logger.exception(
            'PLAT-4133 boundary event emit failed service=%s operation=%s',
            service, operation,
        )
        return False
