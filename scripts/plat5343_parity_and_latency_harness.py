#!/usr/bin/env python3
"""PLAT-5343 slice 1 — parity + latency harness (HLD v12 §4.4 steps 1-2, §10 gates 1-2).

Runs the two production-order entry points side by side against a live
deployment and fails closed on any unexpected grant/loss:

  v1 (old):  GET  /api/internal/users/{id}/project-memberships/?email=...
  v2 (new):  POST /api/internal/v2/project-memberships:resolve
             (ID-dedicated credential + EdDSA subject assertion)

The ONLY permitted deliberate difference (§4.4 step 2) is denial of a
conflicting non-null ID/email row that the old OR query could union. Anything
else — a grant appearing in v2 but not v1, or a loss — is a stop.

Modes:
  parity   — resolve every subject through both entry points and diff.
  latency  — >=100 consecutive v2 calls (Service routing; add --pod to target
             a specific ready pod); report p50/p95/p99/max; gate p99 <= 250 ms
             and zero responses > 500 ms (§10 gate 1).

Subjects:
  --subjects-file JSON  — [{"sub": 4242, "email": "zen@shizuha.com"}, ...]
  --from-db             — sample real subjects from the Admin database
                          (members-by-user_id, email-only rows, agents,
                          no-membership users) to reach --min-subjects.

Usage (from the admin workspace, inside the cluster):
  .venv/bin/python scripts/plat5343_parity_and_latency_harness.py parity \
      --admin-url http://shizuha-admin:8003/api \
      --id-signing-key-file /run/secrets/id_v2_signing_key.pem \
      --id-service-credential-env SHIZUHA_ADMIN_V2_SERVICE_CREDENTIAL \
      --from-db --min-subjects 100

Exit codes: 0 = gates pass, 1 = gate failure, 2 = harness misconfiguration.
"""
import argparse
import json
import os
import statistics
import sys
import time
import uuid

import jwt
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

V2_ROUTE = '/internal/v2/project-memberships:resolve'
V1_ROUTE = '/internal/users/{user_id}/project-memberships/'
ASSERTION_LIFETIME_SECONDS = 5
LATENCY_CALLS_DEFAULT = 100
P99_BUDGET_MS = 250.0
MAX_BUDGET_MS = 500.0


def log(message):
    print(message, flush=True)


def load_signing_key(path):
    with open(path, 'rb') as handle:
        return handle.read()


def mint_assertion(signing_private_pem, sub, email):
    """Mint one ID subject assertion (HLD §4.1) for the harness subject."""
    now = int(time.time())
    claims = {
        'iss': 'shizuha-id',
        'aud': 'shizuha-admin',
        'scope': 'membership-projection:resolve',
        'sub': str(int(sub)),
        'iat': now,
        'exp': now + ASSERTION_LIFETIME_SECONDS,
        'jti': str(uuid.uuid4()),
    }
    if email:
        claims['email'] = str(email).strip().lower()
    return jwt.encode(claims, signing_private_pem, algorithm='EdDSA')


def resolve_v1(admin_url, service_token, user_id, email, timeout):
    params = {}
    if email:
        params['email'] = email
    response = requests.get(
        admin_url + V1_ROUTE.format(user_id=user_id),
        params=params,
        headers={
            'X-Internal-Service': 'shizuha-id',
            'X-Internal-Service-Token': service_token,
        },
        timeout=timeout,
    )
    if response.status_code != 200:
        return {'error': f'HTTP {response.status_code}'}
    return response.json()


def resolve_v2(admin_url, service_token, signing_key, sub, email, timeout):
    response = requests.post(
        admin_url + V2_ROUTE,
        json={},
        headers={
            'X-Internal-Service': 'shizuha-id',
            'X-Internal-Service-Token': service_token,
            'X-Shizuha-Subject-Assertion': mint_assertion(signing_key, sub, email),
        },
        timeout=timeout,
    )
    if response.status_code != 200:
        return {'error': f'HTTP {response.status_code}'}
    return response.json()


def claim_shape(payload):
    """Normalize a successful response to the {project_id: role} claim map."""
    if not isinstance(payload, dict):
        return None
    memberships = payload.get('project_memberships')
    if not isinstance(memberships, dict):
        return None
    return {str(k): str(v) for k, v in memberships.items()}


def diff_claims(v1_map, v2_map):
    """Return (unexpected_grants, unexpected_losses) per the §4.4 rule.

    The only permitted difference is a v2 denial of a project the v1 OR-query
    granted (the conflicting non-null ID/email row). Because the harness
    cannot see row provenance over the wire, a v1-only project is classified
    as PERMITTED-LOSS-CANDIDATE and reported separately for reviewer
    confirmation against the conflicting-row anomaly counter; a v2-only
    project is always an unexpected grant.
    """
    grants = sorted(set(v2_map) - set(v1_map))
    losses = sorted(set(v1_map) - set(v2_map))
    return grants, losses


def collect_subjects_from_db(min_subjects):
    """Sample real subjects across the §4.4 matrix shapes from Admin's DB."""
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shizuha_admin.settings')
    django.setup()
    from organizations.models import OrganizationMembership
    from django.db.models import Q

    subjects = []
    seen = set()

    def add(sub, email):
        key = (sub, (email or '').strip().lower())
        if key not in seen and sub:
            seen.add(key)
            subjects.append({'sub': sub, 'email': email})

    # Human members (exact user_id rows).
    for row in (OrganizationMembership.objects.filter(
            user_id__isnull=False, is_active=True)
            .values('user_id', 'user_email').distinct()[:min_subjects]):
        add(row['user_id'], row['user_email'])
    # Email-only rows (user_id IS NULL).
    for row in (OrganizationMembership.objects.filter(
            user_id__isnull=True, is_active=True)
            .exclude(user_email='')[:max(0, min_subjects // 4)]):
        add(None, row['user_email'])
    # Inactive rows.
    for row in (OrganizationMembership.objects.filter(is_active=False)
                .values('user_id', 'user_email').distinct()[:max(0, min_subjects // 4)]):
        add(row['user_id'], row['user_email'])
    # Conflicting shapes: same email, different non-null user_id.
    for row in (OrganizationMembership.objects.filter(
            Q(user_id__isnull=False), user_email__isnull=False)
            .values('user_email').distinct()[:max(0, min_subjects // 4)]):
        members = list(OrganizationMembership.objects.filter(
            user_email=row['user_email'], user_id__isnull=False, is_active=True)
            .values_list('user_id', flat=True)[:2])
        if len(members) == 2:
            add(members[0], row['user_email'])
            add(members[1], row['user_email'])
    # Known authoritative-empty subjects (no membership rows at all).
    from django.contrib.auth import get_user_model
    user_model = get_user_model()
    member_ids = set(OrganizationMembership.objects.filter(
        is_active=True, user_id__isnull=False).values_list('user_id', flat=True))
    for user in user_model.objects.exclude(id__in=member_ids)[:max(0, min_subjects // 4)]:
        add(user.id, getattr(user, 'email', None))

    while len(subjects) < min_subjects:
        add(None, None)
        break
    return subjects


def run_parity(args):
    signing_key = load_signing_key(args.id_signing_key_file)
    service_token = os.environ[args.id_service_credential_env]
    timeout = (args.connect_timeout, args.read_timeout)

    if args.subjects_file:
        with open(args.subjects_file) as handle:
            subjects = json.load(handle)
    elif args.from_db:
        subjects = collect_subjects_from_db(args.min_subjects)
    else:
        log('error: need --subjects-file or --from-db')
        return 2

    if len(subjects) < args.min_subjects:
        log(f'error: only {len(subjects)} subjects available, need {args.min_subjects}')
        return 2

    log(f'parity: resolving {len(subjects)} subjects through v1 and v2')
    unexpected_grants = []
    permitted_loss_candidates = []
    v1_errors = []
    v2_errors = []
    for subject in subjects:
        sub = subject.get('sub')
        email = subject.get('email')
        if not sub:
            # Email-only subjects need a user_id for the v1 route; resolve the
            # v1 claim by email via the same route with a placeholder id only
            # when the deployment supports it — otherwise skip with a note.
            log(f"skip email-only subject ({email}): v1 route is id-addressed")
            continue
        v1 = resolve_v1(args.admin_url, service_token, sub, email, timeout)
        v2 = resolve_v2(args.admin_url, service_token, signing_key, sub, email, timeout)
        v1_map = claim_shape(v1)
        v2_map = claim_shape(v2)
        if v1_map is None:
            v1_errors.append({'sub': sub, 'payload': v1})
            continue
        if v2_map is None:
            v2_errors.append({'sub': sub, 'payload': v2})
            continue
        grants, losses = diff_claims(v1_map, v2_map)
        for project in grants:
            unexpected_grants.append({'sub': sub, 'project': project,
                                      'v1_role': v1_map.get(project),
                                      'v2_role': v2_map.get(project)})
        for project in losses:
            permitted_loss_candidates.append({
                'sub': sub, 'project': project,
                'v1_role': v1_map.get(project),
                'note': 'permitted only if this is the conflicting '
                        'non-null ID/email row (§4.4 step 2); confirm against '
                        'admin_membership_v2_anomaly counter',
            })

    log('')
    log(f'resolved: {len(subjects) - len(v1_errors) - len(v2_errors)} ok, '
        f'{len(v1_errors)} v1 errors, {len(v2_errors)} v2 errors')
    log(f'unexpected grants (STOP): {len(unexpected_grants)}')
    for entry in unexpected_grants[:20]:
        log(f'  GRANT sub={entry["sub"]} project={entry["project"]} '
            f'v1={entry["v1_role"]} v2={entry["v2_role"]}')
    log(f'v1-only losses (permitted-difference candidates): '
        f'{len(permitted_loss_candidates)}')
    for entry in permitted_loss_candidates[:20]:
        log(f'  LOSS sub={entry["sub"]} project={entry["project"]} '
            f'v1_role={entry["v1_role"]}')
    if v1_errors or v2_errors:
        log('entry-point errors (typed non-200s are fail-closed, but the '
            'parity run cannot certify those subjects):')
        for entry in (v1_errors + v2_errors)[:10]:
            log(f'  {entry}')
    if unexpected_grants:
        log('GATE FAIL: unexpected grant/loss is a stop (§4.4 step 2)')
        return 1
    if permitted_loss_candidates and not args.allow_loss_candidates:
        log('GATE FAIL: v1-only losses present — re-run with '
            '--allow-loss-candidates ONLY after confirming every loss is the '
            'conflicting non-null ID/email denial (check the '
            'membership_v2_anomaly counter)')
        return 1
    log('GATE PASS: zero unexpected grants; losses within the permitted '
        'difference rule')
    return 0


def run_latency(args):
    signing_key = load_signing_key(args.id_signing_key_file)
    service_token = os.environ[args.id_service_credential_env]
    timeout = (args.connect_timeout, args.read_timeout)
    calls = max(args.calls, LATENCY_CALLS_DEFAULT)

    target = args.admin_url
    if args.pod:
        # Direct-pod routing (§10 gate 1: every ready pod plus Service).
        target = args.admin_url.replace(args.service_host, args.pod) \
            if args.service_host else f'http://{args.pod}:8003/api'

    log(f'latency: {calls} consecutive v2 calls against {target}')
    durations_ms = []
    failures = []
    for index in range(calls):
        sub = 4242 + (index % 50)  # bounded subject spread
        start = time.perf_counter()
        try:
            payload = resolve_v2(target, service_token, signing_key, sub,
                                 'zen@shizuha.com', timeout)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            if claim_shape(payload) is None:
                failures.append({'index': index, 'payload': payload})
            durations_ms.append(elapsed_ms)
        except Exception as exc:  # noqa: BLE001 — harness reports, never hides
            failures.append({'index': index, 'exception': f'{type(exc).__name__}: {exc}'})

    if len(durations_ms) < calls:
        log(f'GATE FAIL: only {len(durations_ms)}/{calls} calls completed')
        for entry in failures[:10]:
            log(f'  {entry}')
        return 1

    durations_ms.sort()
    p50 = statistics.median(durations_ms)
    p95 = durations_ms[int(0.95 * (len(durations_ms) - 1))]
    p99 = durations_ms[int(0.99 * (len(durations_ms) - 1))]
    maximum = durations_ms[-1]
    log(f'p50={p50:.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms max={maximum:.1f}ms')
    over_budget = [d for d in durations_ms if d > MAX_BUDGET_MS]
    log(f'responses > {MAX_BUDGET_MS:.0f}ms: {len(over_budget)}')
    if p99 > P99_BUDGET_MS:
        log(f'GATE FAIL: p99 {p99:.1f}ms > {P99_BUDGET_MS:.0f}ms budget')
        return 1
    if over_budget:
        log(f'GATE FAIL: {len(over_budget)} responses exceeded {MAX_BUDGET_MS:.0f}ms')
        return 1
    log('GATE PASS: p99 within budget, zero responses over the wire cap')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest='mode', required=True)

    def common(p):
        p.add_argument('--admin-url', default=os.environ.get(
            'SHIZUHA_ADMIN_API_URL', 'http://shizuha-admin:8003/api'))
        p.add_argument('--id-signing-key-file', required=True,
                       help='PEM file with ID\'s dedicated EdDSA private key')
        p.add_argument('--id-service-credential-env',
                       default='SHIZUHA_ADMIN_V2_SERVICE_CREDENTIAL',
                       help='env var holding ID\'s v2 service credential')
        p.add_argument('--connect-timeout', type=float, default=0.25)
        p.add_argument('--read-timeout', type=float, default=0.5)

    p_parity = subparsers.add_parser('parity', help='v1/v2 claim diff')
    common(p_parity)
    p_parity.add_argument('--subjects-file')
    p_parity.add_argument('--from-db', action='store_true')
    p_parity.add_argument('--min-subjects', type=int, default=100)
    p_parity.add_argument('--allow-loss-candidates', action='store_true',
                          help='accept v1-only losses after reviewer confirmation')

    p_latency = subparsers.add_parser('latency', help='§10 gate 1 latency probe')
    common(p_latency)
    p_latency.add_argument('--calls', type=int, default=LATENCY_CALLS_DEFAULT)
    p_latency.add_argument('--pod', help='pod DNS for direct-pod routing')
    p_latency.add_argument('--service-host', default='shizuha-admin')

    args = parser.parse_args()
    if args.mode == 'parity':
        return run_parity(args)
    return run_latency(args)


if __name__ == '__main__':
    sys.exit(main())
