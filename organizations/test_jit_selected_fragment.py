"""Bind the selected existing Origin owner to one independently approved use."""
import json
from unittest.mock import patch

from django.test import TestCase, override_settings

from .jit_dispatch import _dispatch_request, dispatch_kubernetes_jit_use
from .models import (
    EmployeeProfile, JITElevatedAccessGrant, JITElevatedAccessGrantUse,
    OrganizationMembership, Team, TeamMembership,
)
from . import test_jit_elevated_access as legacy
from . import test_jit_dispatch as legacy_dispatch


SELECTED = 'infra-recovery-owner-read'
MISSING = object()


@override_settings(ORIGIN_JIT_DISPATCH_TOKEN='disposable-selected-test')
class KubernetesSelectedFragmentTests(TestCase):
    setUp = legacy.JITElevatedAccessGrantTests.setUp
    _auth = legacy.JITElevatedAccessGrantTests._auth

    def request_grant(self, selected=MISSING):
        Team.objects.get_or_create(organization=self.org, name='Platform')
        self._auth()
        payload = {
            'org_slug': self.org.slug,
            'scope': JITElevatedAccessGrant.KUBERNETES_RBAC_APPLY_SCOPE,
            'reason': 'Synthetic selected owner contract',
            'task_key': 'PLAT-TEST', 'ttl_seconds': 600,
            'commit_sha': 'a' * 40,
        }
        if selected is not MISSING:
            payload['selected_fragment'] = selected
        return self.client.post('/api/jit-elevations/', payload, format='json')

    def approved(self, selected=MISSING):
        response = self.request_grant(selected)
        self.assertEqual(response.status_code, 201, response.data)
        grant = JITElevatedAccessGrant.objects.get(pk=response.data['grant']['id'])
        OrganizationMembership.objects.create(
            organization=self.org, user_id=11, user_email='peer@example.invalid',
            role='member', is_pending=False,
        )
        profile = EmployeeProfile.objects.get(
            membership__organization=self.org, membership__user_id=11,
        )
        TeamMembership.objects.create(
            team=Team.objects.get(organization=self.org, name='Platform'),
            employee_profile=profile, role='member',
        )
        self._auth(11, 'peer@example.invalid')
        response = self.client.post(
            f'/api/jit-elevations/{grant.pk}/approve/', {'note': 'Peer review'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self._auth()
        grant.refresh_from_db()
        return grant

    def consume(self, grant, selected=MISSING, key='once'):
        payload = {
            'action': 'apply-origin-ci-deployer-rbac',
            'expected_sha': 'a' * 40, 'idempotency_key': key,
        }
        if selected is not MISSING:
            payload['selected_fragment'] = selected
        with patch('organizations.tasks.dispatch_kubernetes_jit_use_task.delay'):
            with self.captureOnCommitCallbacks(execute=True):
                return self.client.post(
                    f'/api/jit-elevations/{grant.pk}/consume-kubernetes/',
                    payload, format='json',
                )

    def test_actual_grant_consume_and_dispatch_bind_selected_owner(self):
        grant = self.approved(SELECTED)
        self.assertEqual(grant.target_constraints['selected_fragment'], SELECTED)
        self.assertTrue(grant.has_complete_current_exact_authority())
        consumed = self.consume(grant, SELECTED)
        self.assertEqual(consumed.status_code, 202, consumed.data)
        use = JITElevatedAccessGrantUse.objects.get(grant=grant)
        self.assertEqual(use.result['selected_fragment'], SELECTED)
        canonical = {'action': 'apply-origin-ci-deployer-rbac',
                     'expected_sha': 'a' * 40, 'selected_fragment': SELECTED}
        self.assertEqual(use.request_digest,
                         JITElevatedAccessGrant.constraint_digest_for(canonical))
        payload = json.loads(_dispatch_request(use).data)
        self.assertEqual(payload['inputs'], {
            'expected_sha': 'a' * 40, 'grant_id': str(grant.pk),
            'use_id': str(use.pk), 'task_key': 'PLAT-TEST',
            'selected_fragment': SELECTED,
        })
        grant.refresh_from_db()
        self.assertEqual(grant.uses_consumed, 1)
        self.assertEqual(grant.status, JITElevatedAccessGrant.STATUS_REVOKED)
        replay = self.consume(grant, SELECTED)
        self.assertEqual(replay.status_code, 202)
        self.assertEqual(replay.data['use_id'], use.pk)

    def test_unknown_and_nonstring_admission_refuse_without_grant(self):
        for value in ('other', '../infra-recovery-owner-read', ' all', None, 1, True, []):
            with self.subTest(value=value):
                before = JITElevatedAccessGrant.objects.count()
                response = self.request_grant(value)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(JITElevatedAccessGrant.objects.count(), before)

    def test_default_all_keeps_exact_existing_contract_and_dispatch(self):
        for index, value in enumerate((MISSING, '', 'all')):
            with self.subTest(value=str(value)):
                # Reuse independently approved grant through API; peer exists
                # after the first case, so isolate each case in a savepoint.
                from django.db import transaction
                with transaction.atomic():
                    grant = self.approved(value)
                    expected = {**grant.exact_policy_for_scope(grant.scope)['fixed_constraints'],
                                'commit_sha': 'a' * 40}
                    self.assertEqual(grant.target_constraints, expected)
                    consumed = self.consume(grant, value, key=f'old-{index}')
                    self.assertEqual(consumed.status_code, 202, consumed.data)
                    use = JITElevatedAccessGrantUse.objects.get(grant=grant)
                    self.assertNotIn('selected_fragment', use.result)
                    self.assertEqual(use.request_digest, grant.constraint_digest_for({
                        'action': 'apply-origin-ci-deployer-rbac', 'expected_sha': 'a' * 40,
                    }))
                    self.assertEqual(set(json.loads(_dispatch_request(use).data)['inputs']),
                                     {'expected_sha', 'grant_id', 'use_id', 'task_key'})
                    transaction.set_rollback(True)

    def test_selected_grant_cannot_be_consumed_as_all(self):
        grant = self.approved(SELECTED)
        for value in (MISSING, '', 'all'):
            with self.subTest(value=str(value)):
                response = self.consume(grant, value)
                self.assertEqual(response.status_code, 403, response.data)
                self.assertFalse(JITElevatedAccessGrantUse.objects.filter(grant=grant).exists())

    def test_consumed_all_cannot_be_relabelled_selected(self):
        grant = self.approved()
        self.assertEqual(self.consume(grant).status_code, 202)
        use = JITElevatedAccessGrantUse.objects.get(grant=grant)
        original = (use.request_digest, use.result.copy())
        response = self.consume(grant, SELECTED)
        self.assertEqual(response.status_code, 409, response.data)
        use.refresh_from_db()
        self.assertEqual((use.request_digest, use.result), original)

    def test_selected_dispatch_refuses_use_binding_tamper(self):
        grant = self.approved(SELECTED)
        self.assertEqual(self.consume(grant, SELECTED).status_code, 202)
        use = JITElevatedAccessGrantUse.objects.get(grant=grant)
        for field, value in (('request_digest', '0' * 64), ('result', {'dispatch_status': 'pending'})):
            with self.subTest(field=field):
                original = getattr(use, field)
                setattr(use, field, value)
                with self.assertRaises(RuntimeError):
                    _dispatch_request(use)
                setattr(use, field, original)

    def test_stored_unknown_selector_is_incomplete_even_with_matching_digest(self):
        grant = self.approved(SELECTED)
        for value in ('other', '', 'all', None, False):
            with self.subTest(value=value):
                grant.target_constraints['selected_fragment'] = value
                grant.constraint_digest = grant.constraint_digest_for(grant.target_constraints)
                grant.save(update_fields=['target_constraints', 'constraint_digest'])
                self.assertFalse(grant.has_complete_current_exact_authority())
                response = self.consume(grant, SELECTED)
                self.assertEqual(response.status_code, 403, response.data)
                self.assertFalse(JITElevatedAccessGrantUse.objects.filter(grant=grant).exists())

    def test_unknown_consume_selector_and_other_actor_never_create_use(self):
        grant = self.approved(SELECTED)
        self.assertEqual(self.consume(grant, 'other').status_code, 400)
        self._auth(11, 'peer@example.invalid')
        self.assertEqual(self.consume(grant, SELECTED).status_code, 403)
        self.assertFalse(JITElevatedAccessGrantUse.objects.filter(grant=grant).exists())
        grant.refresh_from_db()
        self.assertEqual(grant.uses_consumed, 0)

    def test_selected_use_cannot_downgrade_to_all_when_grant_marker_is_removed(self):
        from django.db import transaction
        for remove_result_marker in (False, True):
            with self.subTest(remove_result_marker=remove_result_marker):
                with transaction.atomic():
                    grant = self.approved(SELECTED)
                    self.assertEqual(self.consume(grant, SELECTED).status_code, 202)
                    use = JITElevatedAccessGrantUse.objects.get(grant=grant)
                    constraints = dict(grant.target_constraints)
                    constraints.pop('selected_fragment')
                    grant.target_constraints = constraints
                    grant.constraint_digest = grant.constraint_digest_for(constraints)
                    grant.save(update_fields=['target_constraints', 'constraint_digest'])
                    if remove_result_marker:
                        result = dict(use.result)
                        result.pop('selected_fragment')
                        use.result = result
                        use.save(update_fields=['result'])
                    with patch('organizations.jit_dispatch.urllib.request.urlopen',
                               return_value=legacy_dispatch._Response()) as send:
                        with self.assertRaises(RuntimeError):
                            dispatch_kubernetes_jit_use(use.pk)
                        send.assert_not_called()
                    transaction.set_rollback(True)
