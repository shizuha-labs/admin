import io
import json
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from .jit_dispatch import dispatch_kubernetes_jit_use, reconcile_pending_kubernetes_jit_uses
from .models import (
    JITElevatedAccessGrant,
    JITElevatedAccessGrantUse,
    Organization,
)


class _Response:
    status = 201

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({'id': 8123, 'run_number': 94, 'jobs': []}).encode()


@override_settings(
    ORIGIN_API_URL='http://forgejo.invalid',
    ORIGIN_JIT_DISPATCH_TOKEN='server-owned-token',
    ORIGIN_JIT_DISPATCH_TIMEOUT_SECONDS=2,
)
class KubernetesJITDispatchTests(TestCase):
    @patch('organizations.jit_dispatch.urllib.request.urlopen', return_value=_Response())
    def test_dispatch_payload_is_fixed_and_attributable(self, urlopen):
        org = Organization.objects.create(name='Acme', slug='acme', owner_id=1)
        policy = JITElevatedAccessGrant.exact_policy_for_scope(
            JITElevatedAccessGrant.KUBERNETES_RBAC_APPLY_SCOPE
        )
        constraints = {**policy['fixed_constraints'], 'commit_sha': 'a' * 40}
        grant = JITElevatedAccessGrant.objects.create(
            organization=org, requester_user_id=10,
            requester_email='requester@shizuha.com',
            scope=JITElevatedAccessGrant.KUBERNETES_RBAC_APPLY_SCOPE,
            requested_role='admin', reason='test', task_key='PLAT-6167',
            status=JITElevatedAccessGrant.STATUS_REVOKED,
            target_constraints=constraints,
            constraint_digest=JITElevatedAccessGrant.constraint_digest_for(constraints),
            revoked_at=timezone.now(),
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        use = JITElevatedAccessGrantUse.objects.create(
            grant=grant, idempotency_key='once', request_digest='d' * 64,
            actor_user_id=10, actor_email='requester@shizuha.com',
            result={'dispatch_status': 'pending'},
        )
        result = dispatch_kubernetes_jit_use(use.pk)
        self.assertEqual(result['origin_run_id'], 8123)
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            'http://forgejo.invalid/api/v1/repos/shizuha-labs/deploy/actions/workflows/'
            'apply-origin-ci-deployer-rbac.yml/dispatches',
        )
        payload = json.loads(request.data)
        self.assertEqual(payload['ref'], 'refs/heads/master')
        self.assertIs(payload['return_run_info'], True)
        self.assertEqual(payload['inputs'], {
            'expected_sha': 'a' * 40,
            'grant_id': str(grant.pk),
            'use_id': str(use.pk),
            'task_key': 'PLAT-6167',
        })
        self.assertNotIn('script', payload['inputs'])
        self.assertNotIn('workflow', payload['inputs'])
        self.assertNotIn('namespace', payload['inputs'])
        use.refresh_from_db()
        self.assertEqual(use.dispatch_status, 'accepted')
        self.assertEqual(use.origin_run_id, 8123)

        # Accepted replay is read-only and returns the recorded run.
        replay = dispatch_kubernetes_jit_use(use.pk)
        self.assertEqual(replay['origin_run_id'], 8123)
        self.assertEqual(urlopen.call_count, 1)

    @patch('organizations.jit_dispatch.dispatch_kubernetes_jit_use_fail_loud')
    def test_reconciler_finds_committed_pending_outbox(self, dispatch):
        org = Organization.objects.create(name='Acme', slug='acme', owner_id=1)
        grant = JITElevatedAccessGrant.objects.create(
            organization=org, requester_user_id=10,
            scope=JITElevatedAccessGrant.KUBERNETES_RBAC_APPLY_SCOPE,
            requested_role='admin', reason='recover', task_key='PLAT-6167',
            status=JITElevatedAccessGrant.STATUS_REVOKED,
            revoked_at=timezone.now(), expires_at=timezone.now() + timedelta(minutes=5),
        )
        use = JITElevatedAccessGrantUse.objects.create(
            grant=grant, idempotency_key='recovery', request_digest='d' * 64,
            actor_user_id=10, dispatch_status='pending',
        )
        dispatch.return_value = {'use_id': use.pk}
        self.assertEqual(reconcile_pending_kubernetes_jit_uses(), [{'use_id': use.pk}])
        dispatch.assert_called_once_with(use.pk)

    # ORIG-412: burn moves post-acceptance.
    def _consume_shape_grant(self, **overrides):
        org = Organization.objects.create(name='Acme2', slug='acme2', owner_id=1)
        policy = JITElevatedAccessGrant.exact_policy_for_scope(
            JITElevatedAccessGrant.KUBERNETES_RBAC_APPLY_SCOPE
        )
        constraints = {**policy['fixed_constraints'], 'commit_sha': 'b' * 40}
        fields = dict(
            organization=org, requester_user_id=10,
            requester_email='requester@shizuha.com',
            scope=JITElevatedAccessGrant.KUBERNETES_RBAC_APPLY_SCOPE,
            requested_role='admin', reason='test', task_key='PLAT-6167',
            status=JITElevatedAccessGrant.STATUS_PENDING_DISPATCH,
            target_constraints=constraints,
            constraint_digest=JITElevatedAccessGrant.constraint_digest_for(constraints),
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        fields.update(overrides)
        return JITElevatedAccessGrant.objects.create(**fields)

    @patch('organizations.jit_dispatch.urllib.request.urlopen', return_value=_Response())
    def test_acceptance_burns_grant_post_acceptance(self, urlopen):
        grant = self._consume_shape_grant()
        use = JITElevatedAccessGrantUse.objects.create(
            grant=grant, idempotency_key='burn-after-accept',
            request_digest='d' * 64, actor_user_id=10,
            actor_email='requester@shizuha.com',
        )
        self.assertEqual(grant.revoked_at, None)
        dispatch_kubernetes_jit_use(use.pk)
        grant.refresh_from_db()
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_REVOKED)
        self.assertIsNotNone(grant.revoked_at)
        self.assertTrue(grant.uses.filter(dispatch_status='accepted').exists())

    @patch('organizations.jit_dispatch.urllib.request.urlopen', return_value=_Response())
    def test_parked_pending_dispatch_grant_is_not_revoked_before_acceptance(self, urlopen):
        grant = self._consume_shape_grant()
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_PENDING_DISPATCH)
        self.assertEqual(grant.revoked_at, None)
        self.assertTrue(grant.is_active_now() is False)  # parked: not consumable, not revoked

    def test_window_expiry_without_acceptance_releases_approval(self):
        grant = self._consume_shape_grant(expires_at=timezone.now() - timedelta(seconds=1))
        dead = JITElevatedAccessGrantUse.objects.create(
            grant=grant, idempotency_key='dead-hop',
            request_digest='d' * 64, actor_user_id=10,
            actor_email='requester@shizuha.com', dispatch_status='failed',
            last_dispatch_error='[Errno 111] Connection refused',
        )
        affected = JITElevatedAccessGrant.release_expired_pending_dispatch_consumes()
        self.assertIn(grant.pk, affected)
        grant.refresh_from_db()
        dead.refresh_from_db()
        # Explicit release — never revoked-with-no-run.
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_PENDING)
        self.assertEqual(grant.revoked_at, None)
        self.assertEqual(grant.uses_consumed, 0)
        self.assertEqual(dead.dispatch_status, 'released')

    def test_window_expiry_with_accepted_use_burns_instead(self):
        grant = self._consume_shape_grant(expires_at=timezone.now() - timedelta(seconds=1))
        JITElevatedAccessGrantUse.objects.create(
            grant=grant, idempotency_key='accepted-late',
            request_digest='d' * 64, actor_user_id=10, dispatch_status='accepted',
            origin_run_id=99, dispatched_at=timezone.now(),
        )
        affected = JITElevatedAccessGrant.release_expired_pending_dispatch_consumes()
        self.assertIn(grant.pk, affected)
        grant.refresh_from_db()
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_REVOKED)
        self.assertIsNotNone(grant.revoked_at)

    @patch('organizations.jit_dispatch.dispatch_kubernetes_jit_use_fail_loud')
    def test_reconciler_skips_released_uses(self, dispatch):
        grant = self._consume_shape_grant()
        JITElevatedAccessGrantUse.objects.create(
            grant=grant, idempotency_key='released-evidence',
            request_digest='d' * 64, actor_user_id=10, dispatch_status='released',
        )
        self.assertEqual(reconcile_pending_kubernetes_jit_uses(), [])
        dispatch.assert_not_called()
