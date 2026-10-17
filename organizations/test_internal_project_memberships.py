import os
from types import SimpleNamespace
from unittest.mock import patch

import requests as http_requests
from django.contrib.admin import site as admin_site
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory

from organizations import security_events
from organizations.models import ProjectMember
from organizations.internal_urls import (
    PULSE_PROXY_TIMEOUT,
    InternalUserProjectMembershipsView,
    InternalUserProjectsView,
    _pulse_proxy_timeout,
)

# shizuha-id calls this endpoint with `timeout=1.0` while minting a token
# (id: identity/views.py::_fetch_project_memberships). That number is the
# contract these tests defend, not an arbitrary constant.
ID_MINT_BUDGET_SECONDS = 1.0


class InternalUserProjectMembershipsViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    @override_settings(ROOT_URLCONF='organizations.internal_urls')
    @patch('organizations.internal_urls.http_requests.get')
    def test_proxies_pulse_project_membership_claim_shape(self, mock_get):
        mock_get.return_value = SimpleNamespace(
            status_code=200,
            json=lambda: {
                'project_memberships': {'36': 'member', '41': 'admin'},
                'project_ids': [36, 41],
            },
        )
        request = self.factory.get('/internal/users/7/project-memberships/?email=dev@shizuha.com')

        response = InternalUserProjectMembershipsView.as_view()(request, user_id=7)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['project_memberships'], {'36': 'member', '41': 'admin'})
        self.assertEqual(response.data['project_ids'], [36, 41])
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        self.assertEqual(args[0], 'http://shizuha-pulse:8002/api/internal/users/7/project-memberships/')
        self.assertEqual(kwargs['params'], {'email': 'dev@shizuha.com'})

    @patch('organizations.internal_urls.http_requests.get')
    def test_pulse_proxy_cannot_outlive_the_caller_that_is_waiting_for_it(self, mock_get):
        """PLAT-5338: the proxy budget must stay under shizuha-id's 1.0s budget.

        This was `timeout=10`. gunicorn serves :8003 from a small fixed worker
        pool, so a 10s upstream call held a worker roughly 10x longer than the
        only caller was still waiting — and everything else queued behind it,
        including the kubelet health probe that keeps this pod alive. Asserting
        the RELATIONSHIP rather than the literal keeps a later "let's give Pulse
        more time" change from silently reintroducing liveness kills.
        """
        mock_get.return_value = SimpleNamespace(
            status_code=200,
            json=lambda: {'project_memberships': {}, 'project_ids': []},
        )
        request = self.factory.get('/internal/users/7/project-memberships/')

        InternalUserProjectMembershipsView.as_view()(request, user_id=7)

        timeout = mock_get.call_args.kwargs['timeout']
        # A (connect, read) pair, because a single scalar applies to EACH phase:
        # `timeout=1.0` can still block for 2.0s total and blow the budget.
        self.assertIsInstance(timeout, tuple)
        self.assertEqual(len(timeout), 2)
        self.assertLess(
            sum(timeout),
            ID_MINT_BUDGET_SECONDS,
            f'connect+read={sum(timeout)}s must stay under the caller budget of '
            f'{ID_MINT_BUDGET_SECONDS}s, or a slow Pulse pins an admin worker '
            f'after shizuha-id has already given up and stamped project_ids=[]',
        )

    def test_pulse_timeout_is_env_tunable_but_still_defaults_under_budget(self):
        with patch.dict(os.environ, {
            'SHIZUHA_PULSE_CONNECT_TIMEOUT': '0.1',
            'SHIZUHA_PULSE_READ_TIMEOUT': '0.2',
        }):
            self.assertEqual(_pulse_proxy_timeout(), (0.1, 0.2))

        for key in ('SHIZUHA_PULSE_CONNECT_TIMEOUT', 'SHIZUHA_PULSE_READ_TIMEOUT'):
            os.environ.pop(key, None)
        self.assertLess(sum(_pulse_proxy_timeout()), ID_MINT_BUDGET_SECONDS)

    @patch('organizations.security_events.record_project_membership_projection')
    @patch('organizations.internal_urls.http_requests.get')
    def test_pulse_timeout_fails_closed_instead_of_answering_empty(self, mock_get, mock_metric):
        """PLAT-5338: the live defect. A Pulse timeout must NOT become 200 + [].

        This replaces `test_local_fallback_is_reached_when_pulse_times_out`,
        which asserted the behaviour that caused the incident: on timeout the
        view read the local ProjectMember shadow table and returned whatever it
        found as a 200. Nothing writes that table, so what it found was nothing,
        and every timed-out mint got a well-formed, authoritative-looking
        `project_ids: []` — which shizuha-id cannot tell apart from "this user
        has no projects" and stamps into a 15-minute JWT.
        """
        mock_get.side_effect = http_requests.exceptions.Timeout('pulse slow')
        request = self.factory.get('/internal/users/7/project-memberships/')

        response = InternalUserProjectMembershipsView.as_view()(request, user_id=7)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['error'], 'project_membership_unavailable')
        # Retryable, and typed: shizuha-id's required=True projection raises on
        # any non-200, so this is what stops the mint rather than mis-stamping it.
        self.assertEqual(response['Retry-After'], '1')
        self.assertNotIn('project_ids', response.data)
        mock_metric.assert_called_once_with('unavailable')

    @patch('organizations.security_events.record_project_membership_projection')
    @patch('organizations.internal_urls.http_requests.get')
    def test_pulse_error_status_fails_closed(self, mock_get, mock_metric):
        """A non-200 from Pulse is not an answer either."""
        mock_get.return_value = SimpleNamespace(status_code=500, json=lambda: {})
        request = self.factory.get('/internal/users/7/project-memberships/')

        response = InternalUserProjectMembershipsView.as_view()(request, user_id=7)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['error'], 'project_membership_unavailable')
        mock_metric.assert_called_once_with('unavailable')

    @patch('organizations.internal_urls.http_requests.get')
    def test_the_projection_endpoint_never_reads_the_unwritten_shadow_table(self, mock_get):
        """The fallback fabricated an answer; make sure it cannot come back.

        `ProjectMember` has no writer anywhere in this codebase, so a read of it
        is a guaranteed empty result dressed up as a projection. Asserting on
        the manager itself (rather than the response) is what keeps a later
        "let's degrade gracefully again" change from silently reintroducing the
        exact failure PLAT-5338 was filed for.
        """
        mock_get.side_effect = http_requests.exceptions.Timeout('pulse slow')
        request = self.factory.get('/internal/users/7/project-memberships/?email=dev@shizuha.com')

        with patch('organizations.models.ProjectMember.objects') as mock_objects:
            InternalUserProjectMembershipsView.as_view()(request, user_id=7)

        mock_objects.filter.assert_not_called()

    @patch('organizations.security_events.record_project_membership_projection')
    @patch('organizations.internal_urls.http_requests.get')
    def test_authoritative_empty_is_served_but_counted(self, mock_get, mock_metric):
        """A user with genuinely no projects still gets a 200.

        Negative control for the fix: failing closed must mean "admin could not
        ask", never "the answer was empty". If this ever turns into a 503, the
        fix has started denying legitimate mints.
        """
        mock_get.return_value = SimpleNamespace(
            status_code=200,
            json=lambda: {'project_memberships': {}, 'project_ids': []},
        )
        request = self.factory.get('/internal/users/7/project-memberships/')

        response = InternalUserProjectMembershipsView.as_view()(request, user_id=7)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['project_ids'], [])
        mock_metric.assert_called_once_with('authoritative_empty')

    @patch('organizations.security_events.record_project_membership_projection')
    @patch('organizations.internal_urls.http_requests.get')
    def test_healthy_projection_does_no_metrics_io(self, mock_get, mock_metric):
        """The hot path stays free of the Redis round-trip.

        This endpoint runs inside shizuha-id's 1.0s mint budget; the counter
        exists to make anomalies visible, not to tax every successful mint.
        """
        mock_get.return_value = SimpleNamespace(
            status_code=200,
            json=lambda: {'project_memberships': {'36': 'member'}, 'project_ids': [36]},
        )
        request = self.factory.get('/internal/users/7/project-memberships/')

        response = InternalUserProjectMembershipsView.as_view()(request, user_id=7)

        self.assertEqual(response.status_code, 200)
        mock_metric.assert_not_called()

    @patch('organizations.security_events._metrics_redis_client')
    @patch('organizations.internal_urls.http_requests.get')
    def test_a_broken_metrics_backend_does_not_change_the_answer(self, mock_get, mock_redis):
        """The detector must never be able to break the thing it watches.

        Runs the REAL recorder (not a mock of it) against a dead Redis, so the
        swallow-and-log is what is under test rather than an assumption about it.
        """
        mock_redis.side_effect = RuntimeError('redis down')
        mock_get.side_effect = http_requests.exceptions.Timeout('pulse slow')
        request = self.factory.get('/internal/users/7/project-memberships/')

        with self.assertLogs('organizations.security_events', level='ERROR'):
            response = InternalUserProjectMembershipsView.as_view()(request, user_id=7)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['error'], 'project_membership_unavailable')

    @patch('organizations.internal_urls.http_requests.get')
    def test_unparseable_pulse_body_fails_closed_as_malformed(self, mock_get):
        def _boom():
            raise ValueError('not json')

        mock_get.return_value = SimpleNamespace(status_code=200, json=_boom)
        request = self.factory.get('/internal/users/7/project-memberships/')

        response = InternalUserProjectMembershipsView.as_view()(request, user_id=7)

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data['error'], 'project_membership_malformed')
        self.assertNotIn('project_ids', response.data)

    @patch('organizations.internal_urls.http_requests.get')
    def test_other_pulse_proxies_bound_their_connect_phase(self, mock_get):
        """A bare scalar timeout is per-PHASE, so `timeout=10` can mean 20s.

        These proxies are not on the token-mint path, so they keep a generous
        read budget — but an unbounded connect phase against a Pulse that is slow
        to accept connections would still let one request occupy an admin worker
        for twice the number written in the source.
        """
        mock_get.return_value = SimpleNamespace(status_code=200, json=lambda: {'projects': []})
        request = self.factory.get('/internal/users/7/projects/')

        InternalUserProjectsView.as_view()(request, user_id=7)

        timeout = mock_get.call_args.kwargs['timeout']
        self.assertEqual(timeout, PULSE_PROXY_TIMEOUT)
        self.assertIsInstance(timeout, tuple)
        self.assertLess(timeout[0], 1.0, 'connect phase must stay sub-second')

    @patch('organizations.security_events.record_project_membership_projection')
    @patch('organizations.internal_urls.http_requests.get')
    def test_malformed_pulse_payload_fails_closed(self, mock_get, mock_metric):
        """reika P2-1: the 502 must not itself be a well-shaped empty projection.

        The previous body was `{'project_memberships': {}, 'project_ids': []}` —
        byte-identical to the fabricated answer this whole change exists to stop
        emitting, with only the status code telling them apart. shizuha-id
        happens to check the status first, so it was never live-exploitable, but
        it left a caller's status check as the only thing between a fabricated
        projection and a stamped JWT claim. The error branches now carry no claim
        keys at all, so absence cannot be read as emptiness by anyone.
        """
        mock_get.return_value = SimpleNamespace(
            status_code=200,
            json=lambda: {'project_memberships': [], 'project_ids': {}},
        )
        request = self.factory.get('/internal/users/7/project-memberships/')

        response = InternalUserProjectMembershipsView.as_view()(request, user_id=7)

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data['error'], 'project_membership_malformed')
        self.assertNotIn('project_ids', response.data)
        self.assertNotIn('project_memberships', response.data)
        mock_metric.assert_called_once_with('malformed')


class ProjectMemberAdminFormTests(SimpleTestCase):
    """reika P2-2: the ModelAdmin was the write path both greps were blind to.

    A row created through the admin form emits neither `ProjectMember(` nor
    `ProjectMember.objects.` into the source tree, so "nothing writes this
    table" could not have been established by grepping for either. Now that the
    projection never reads the table, an add form on it is worse than dead
    weight: `role` and `is_active` look like an access grant and have zero
    authorization effect, so a staff user would grant nothing and believe they
    had. Add is closed; change and delete stay open so an existing row is still
    removable.
    """

    def setUp(self):
        self.model_admin = admin_site._registry[ProjectMember]
        self.request = SimpleNamespace(
            user=SimpleNamespace(
                is_active=True,
                is_superuser=True,
                has_perm=lambda perm, obj=None: True,
            ),
        )

    def test_adding_a_shadow_row_through_the_admin_is_refused(self):
        self.assertFalse(self.model_admin.has_add_permission(self.request))

    def test_an_existing_shadow_row_stays_visible_and_removable(self):
        self.assertTrue(self.model_admin.has_view_permission(self.request))
        self.assertTrue(self.model_admin.has_change_permission(self.request))
        self.assertTrue(self.model_admin.has_delete_permission(self.request))


class ProjectMembershipProjectionMetricsTests(SimpleTestCase):
    """PLAT-5338 detector: the counter has to actually reach Prometheus.

    The admin `/api/metrics/security-events/` endpoint is already scraped by the
    `admin-boundary-event-producer` ServiceMonitor, so exposing the family there
    is what makes it alertable. These assert the exposition contract the alert
    rule is written against — including that all three series render at 0 on a
    healthy service, which is what lets `absent()` catch a detector that has
    silently stopped being scraped.
    """

    @patch('organizations.security_events._metrics_redis_client')
    def test_projection_outcomes_render_for_prometheus(self, mock_redis):
        mock_redis.return_value.mget.return_value = (
            [None] * len(security_events._METRIC_OUTCOMES) + [None] + ['3', None, '11']
        )

        body = security_events.render_boundary_event_metrics()

        self.assertIn(
            '# TYPE platform_project_membership_projection_total counter', body,
        )
        self.assertIn(
            'platform_project_membership_projection_total'
            '{service="admin",outcome="unavailable"} 11',
            body,
        )
        self.assertIn(
            'platform_project_membership_projection_total'
            '{service="admin",outcome="authoritative_empty"} 3',
            body,
        )
        # Rendered even with no increments, so the alert's absent() means
        # "not scraped", not "nothing has gone wrong yet".
        self.assertIn(
            'platform_project_membership_projection_total'
            '{service="admin",outcome="malformed"} 0',
            body,
        )
        # The pre-existing families must survive the added keys — the mget
        # slicing is positional.
        self.assertIn('platform_boundary_event_producer_total{service="admin",outcome="success"} 0', body)
        self.assertIn('platform_jit_approval_invariant_failures_total{service="admin"} 0', body)

    @patch('organizations.security_events._metrics_redis_client')
    def test_metrics_backend_failure_is_reported_not_hidden(self, mock_redis):
        mock_redis.side_effect = RuntimeError('redis down')

        with self.assertLogs('organizations.security_events', level='ERROR'):
            body = security_events.render_boundary_event_metrics()

        self.assertIn('platform_boundary_event_producer_probe_errors{service="admin"} 1', body)
        self.assertNotIn('platform_boundary_event_producer_total', body)
        self.assertNotIn('platform_jit_approval_invariant_failures_total', body)
        self.assertNotIn('platform_project_membership_projection_total', body)

    @patch('organizations.security_events._metrics_redis_client')
    def test_metrics_backend_recovery_preserves_counters_without_synthetic_zero(
        self, mock_redis,
    ):
        """Mirror the production N -> Redis error -> same N scrape order."""
        healthy = ['3', '0', '0', '0', '0', '1', '0', '0', '2', '5', '0', '1']
        client = mock_redis.return_value
        client.mget.side_effect = [healthy, ConnectionError('redis down'), healthy]

        before = security_events.render_boundary_event_metrics()
        with self.assertLogs('organizations.security_events', level='ERROR'):
            unavailable = security_events.render_boundary_event_metrics()
        recovered = security_events.render_boundary_event_metrics()

        before_counters = [
            line for line in before.splitlines()
            if '_total{' in line
        ]
        recovered_counters = [
            line for line in recovered.splitlines()
            if '_total{' in line
        ]
        self.assertEqual(recovered_counters, before_counters)
        self.assertIn(
            'platform_boundary_event_producer_total'
            '{service="admin",outcome="non_202"} 1',
            before,
        )
        self.assertNotIn('_total{', unavailable)
        self.assertIn(
            'platform_boundary_event_producer_probe_errors{service="admin"} 1',
            unavailable,
        )

    def test_unknown_outcome_is_not_recorded(self):
        self.assertFalse(security_events.record_project_membership_projection('made_up'))
