"""PLAT-13057: JIT decision-hook notifications.

Root cure for the PLAT-13056 TTL-rot finding: grants rot because requesters
never learn their grant is pending or actioned. Every decision transition
emits one notification to the requester and one to the owning-team lead
(when resolvable) on Connect's dedicated system-DM lane, carrying the
spec-mandated fields: grant_id, decision, actor, timestamp.
"""

from __future__ import annotations

from unittest import mock

from django.test import TestCase

from organizations import jit_notifications
from organizations.models import (
    JITElevatedAccessGrant,
    Organization,
    Team,
)


def _org(name='Shizuha'):
    return Organization.objects.create(name=name, slug=name.lower(), owner_id=1)


def _grant(org, *, requester_user_id=42, owning_team='admin-platform', scope='hive.fleet.read'):
    return JITElevatedAccessGrant.objects.create(
        organization=org,
        requester_user_id=requester_user_id,
        requester_email=f'user{requester_user_id}@agents.shizuha.io',
        scope=scope,
        owning_team=owning_team,
        ttl_seconds=3600,
    )


def _team(org, name='admin-platform', lead_id=7):
    return Team.objects.create(organization=org, name=name, lead_id=lead_id)


def _accepted_response(status_code=201):
    response = mock.Mock()
    response.status_code = status_code
    return response


class JitDecisionContentTests(TestCase):
    def setUp(self):
        self.org = _org()
        self.grant = _grant(self.org)

    def test_content_carries_the_four_spec_fields(self):
        from django.utils import timezone
        decided = timezone.now()
        content = jit_notifications.jit_decision_content(
            grant=self.grant, decision='approved', actor='decider@shizuha.com',
            decided_at=decided,
        )
        self.assertIn(f'grant_id: {self.grant.pk}', content)
        self.assertIn('decision: approved', content)
        self.assertIn('actor: decider@shizuha.com', content)
        self.assertIn(f'timestamp: {decided.isoformat()}', content)

    def test_note_is_bounded_and_optional(self):
        content = jit_notifications.jit_decision_content(
            grant=self.grant, decision='denied', actor='system',
            decided_at=self.grant.decided_at, note='x' * 500,
        )
        self.assertIn('note: ' + 'x' * 200, content)
        self.assertNotIn('x' * 201, content)


class EmitJitDecisionNotificationTests(TestCase):
    def setUp(self):
        self.org = _org()
        self.team = _team(self.org)
        self.grant = _grant(self.org)

    def tearDown(self):
        jit_notifications.JIT_DECISION_NOTIFICATIONS_ENABLED = True

    def test_notifies_requester_and_team_lead_one_message_each(self):
        with mock.patch.object(jit_notifications.requests, 'post',
                               return_value=_accepted_response()) as post:
            ok = jit_notifications.emit_jit_decision_notification(
                grant=self.grant, decision='approved', actor_email='d@shizuha.com',
                decided_at=self.grant.decided_at,
            )
        self.assertTrue(ok)
        self.assertEqual(post.call_count, 2)
        recipients = sorted(
            call.kwargs['json']['recipient_user_id'] for call in post.call_args_list
        )
        self.assertEqual(recipients, [7, 42])  # lead + requester
        request_ids = [call.kwargs['json']['client_message_id'] for call in post.call_args_list]
        self.assertEqual(len(set(request_ids)), 2)

    def test_requester_face_carries_spec_payload_shape(self):
        with mock.patch.object(jit_notifications.requests, 'post',
                               return_value=_accepted_response()) as post:
            jit_notifications.emit_jit_decision_notification(
                grant=self.grant, decision='approved', actor_email='d@shizuha.com',
                decided_at=self.grant.decided_at,
            )
        requester_call = next(
            call for call in post.call_args_list
            if call.kwargs['json']['recipient_user_id'] == 42
        )
        payload = requester_call.kwargs['json']
        self.assertEqual(payload['sender_service'], 'shizuha-admin')
        self.assertEqual(payload['sender_name'], 'Admin JIT')
        self.assertIn(f'grant_id: {self.grant.pk}', payload['content'])
        self.assertIn('decision: approved', payload['content'])
        self.assertIn('X-System-Message-Token', requester_call.kwargs['headers'])
        self.assertIn('X-Internal-Service', requester_call.kwargs['headers'])

    def test_lead_skipped_when_unresolvable(self):
        self.team.delete()
        with mock.patch.object(jit_notifications.requests, 'post',
                               return_value=_accepted_response()) as post:
            ok = jit_notifications.emit_jit_decision_notification(
                grant=self.grant, decision='denied', actor_email='d@shizuha.com',
                decided_at=self.grant.decided_at,
            )
        self.assertTrue(ok)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs['json']['recipient_user_id'], 42)

    def test_lead_equal_to_requester_is_not_double_notified(self):
        self.team.lead_id = 42
        self.team.save()
        with mock.patch.object(jit_notifications.requests, 'post',
                               return_value=_accepted_response()) as post:
            jit_notifications.emit_jit_decision_notification(
                grant=self.grant, decision='approved', actor_email='d@shizuha.com',
                decided_at=self.grant.decided_at,
            )
        self.assertEqual(post.call_count, 1)

    def test_connect_failure_is_fail_soft(self):
        failed = mock.Mock()
        failed.status_code = 500
        with mock.patch.object(jit_notifications.requests, 'post', return_value=failed):
            ok = jit_notifications.emit_jit_decision_notification(
                grant=self.grant, decision='approved', actor_email='d@shizuha.com',
                decided_at=self.grant.decided_at,
            )
        self.assertFalse(ok)  # delivery result only — never an exception

    def test_connect_timeout_is_fail_soft(self):
        import requests as requests_lib
        with mock.patch.object(
            jit_notifications.requests, 'post',
            side_effect=requests_lib.Timeout('slow'),
        ):
            ok = jit_notifications.emit_jit_decision_notification(
                grant=self.grant, decision='approved', actor_email='d@shizuha.com',
                decided_at=self.grant.decided_at,
            )
        self.assertFalse(ok)

    def test_unknown_decision_refuses_to_notify(self):
        with mock.patch.object(jit_notifications.requests, 'post') as post:
            ok = jit_notifications.emit_jit_decision_notification(
                grant=self.grant, decision='maybe', actor_email='d@shizuha.com',
                decided_at=self.grant.decided_at,
            )
        self.assertFalse(ok)
        post.assert_not_called()

    def test_kill_switch_disables_emission(self):
        with mock.patch.object(jit_notifications.settings,
                               'JIT_DECISION_NOTIFICATIONS_ENABLED', False), \
             mock.patch.object(jit_notifications.requests, 'post') as post:
            ok = jit_notifications.emit_jit_decision_notification(
                grant=self.grant, decision='approved', actor_email='d@shizuha.com',
                decided_at=self.grant.decided_at,
            )
        self.assertFalse(ok)
        post.assert_not_called()


class NotifyExpiredJitGrantsTaskTests(TestCase):
    def setUp(self):
        self.org = _org()
        _team(self.org)
        self.grant = _grant(self.org)
        from django.utils import timezone
        self.grant.approve(actor_email='decider@shizuha.com')
        JITElevatedAccessGrant.objects.filter(pk=self.grant.pk).update(
            expires_at=timezone.now() - timezone.timedelta(minutes=5),
        )
        self.grant.refresh_from_db()

    def test_expired_grant_notified_once(self):
        from organizations.tasks import notify_expired_jit_grants_task
        with mock.patch.object(jit_notifications.requests, 'post',
                               return_value=_accepted_response()) as post:
            result = notify_expired_jit_grants_task()
        self.assertEqual(result, {'notified': 1})
        self.assertEqual(post.call_count, 2)  # requester + lead
        expired_call = post.call_args_list[0].kwargs['json']
        self.assertIn('decision: expired', expired_call['content'])
        self.assertTrue(JITElevatedAccessGrantEvent_marker_exists(self.grant))

    def test_second_pass_is_a_noop(self):
        from organizations.tasks import notify_expired_jit_grants_task
        with mock.patch.object(jit_notifications.requests, 'post',
                               return_value=_accepted_response()):
            notify_expired_jit_grants_task()
        with mock.patch.object(jit_notifications.requests, 'post') as post:
            result = notify_expired_jit_grants_task()
        self.assertEqual(result, {'notified': 0})
        post.assert_not_called()


def JITElevatedAccessGrantEvent_marker_exists(grant) -> bool:
    from organizations.models import JITElevatedAccessGrantEvent
    return JITElevatedAccessGrantEvent.objects.filter(
        grant=grant, event_type='expired',
    ).exists()
