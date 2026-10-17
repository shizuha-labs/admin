"""Fail-closed Origin dispatch adapter for Kubernetes JIT consumption."""

import json
import logging
import os
import urllib.error
import urllib.request

from django.conf import settings
from django.utils import timezone

from .models import (
    JITElevatedAccessGrant,
    JITElevatedAccessGrantEvent,
    JITElevatedAccessGrantUse,
)

logger = logging.getLogger(__name__)


def _dispatch_request(use):
    grant = use.grant
    constraints = grant.target_constraints
    token = settings.ORIGIN_JIT_DISPATCH_TOKEN
    if not token:
        raise RuntimeError('ORIGIN_JIT_DISPATCH_TOKEN is not configured')
    expected = {
        'repository': 'shizuha-labs/deploy',
        'ref': 'refs/heads/master',
        'workflow': 'apply-origin-ci-deployer-rbac.yml',
        'script': 'k3s/origin/apply-ci-deployer-rbac.sh',
    }
    if any(constraints.get(key) != value for key, value in expected.items()):
        raise RuntimeError('stored Kubernetes JIT dispatch contract is not allowlisted')
    url = (
        settings.ORIGIN_API_URL.rstrip('/')
        + '/api/v1/repos/shizuha-labs/deploy/actions/workflows/'
        + expected['workflow'] + '/dispatches'
    )
    payload = {
        'ref': expected['ref'],
        'return_run_info': True,
        'inputs': {
            'expected_sha': constraints['commit_sha'],
            'grant_id': str(grant.pk),
            'use_id': str(use.pk),
            'task_key': grant.task_key,
        },
    }
    return urllib.request.Request(
        url,
        data=json.dumps(payload, sort_keys=True).encode('utf-8'),
        method='POST',
        headers={
            'Authorization': f'token {token}',
            'Content-Type': 'application/json',
            'Idempotency-Key': f'jit-grant-{grant.pk}-use-{use.pk}',
        },
    )


def dispatch_kubernetes_jit_use(use_id):
    """Dispatch one committed use; retrying preserves the immutable request."""
    use = JITElevatedAccessGrantUse.objects.select_related('grant').get(pk=use_id)
    if use.dispatch_status == 'accepted' and use.origin_run_id:
        return use.result
    if use.grant.expires_at is None or use.grant.expires_at <= timezone.now():
        raise RuntimeError('Kubernetes JIT dispatch window expired before acceptance')
    request = _dispatch_request(use)
    try:
        with urllib.request.urlopen(
            request, timeout=settings.ORIGIN_JIT_DISPATCH_TIMEOUT_SECONDS,
        ) as response:
            status_code = response.status
            raw_body = response.read().decode('utf-8')
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        raw_body = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'Origin workflow dispatch refused with HTTP {status_code}') from exc
    if status_code != 201:
        raise RuntimeError(f'Origin workflow dispatch returned HTTP {status_code}, expected 201')
    try:
        body = json.loads(raw_body)
        run_id = int(body['id'])
        run_number = int(body['run_number'])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError('Origin workflow dispatch returned no attributable run') from exc
    result = {
        **use.result,
        'dispatch_status': 'accepted',
        'origin_run_id': run_id,
        'origin_run_number': run_number,
    }
    now = timezone.now()
    JITElevatedAccessGrantUse.objects.filter(pk=use.pk).update(
        dispatch_status='accepted', dispatch_attempts=use.dispatch_attempts + 1,
        origin_run_id=run_id, origin_run_number=run_number,
        last_dispatch_error='', dispatched_at=now, result=result,
    )
    JITElevatedAccessGrantEvent.objects.create(
        grant=use.grant,
        event_type='dispatch_accepted',
        actor_user_id=use.actor_user_id,
        actor_email=use.actor_email,
        source='origin',
        detail={'use_id': use.pk, 'origin_run_id': run_id, 'origin_run_number': run_number},
    )
    return result


def dispatch_kubernetes_jit_use_fail_loud(use_id):
    """Persist retry evidence before re-raising to the task runner."""
    try:
        return dispatch_kubernetes_jit_use(use_id)
    except Exception as exc:
        logger.exception('Kubernetes JIT dispatch failed use_id=%s', use_id)
        use = JITElevatedAccessGrantUse.objects.select_related('grant').filter(pk=use_id).first()
        if use is not None:
            JITElevatedAccessGrantUse.objects.filter(pk=use.pk).update(
                dispatch_status='failed', dispatch_attempts=use.dispatch_attempts + 1,
                last_dispatch_error=str(exc)[:1000],
            )
            JITElevatedAccessGrantEvent.objects.create(
                grant=use.grant, event_type='dispatch_failed', source='origin',
                actor_user_id=use.actor_user_id, actor_email=use.actor_email,
                detail={'use_id': use.pk, 'error': str(exc)[:500]},
            )
        raise


def reconcile_pending_kubernetes_jit_uses():
    """Recover committed outbox rows after broker/worker interruption."""
    use_ids = list(
        JITElevatedAccessGrantUse.objects.filter(
            grant__scope=JITElevatedAccessGrant.KUBERNETES_RBAC_APPLY_SCOPE,
            dispatch_status__in=['pending', 'failed'],
            origin_run_id__isnull=True,
            grant__expires_at__gt=timezone.now(),
        ).order_by('created_at').values_list('pk', flat=True)[:100]
    )
    return [dispatch_kubernetes_jit_use_fail_loud(use_id) for use_id in use_ids]
