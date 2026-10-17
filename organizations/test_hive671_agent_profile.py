"""HIVE-671: Admin projects an agent's ownership binding from Shizuha ID.

Connect must verify that a service-authenticated peer is an owner-bound
*personal-default* agent before honouring the connection.  Rather than guess
from a reserved user-id band, Connect asks Admin's internal
``/api/internal/users/<id>/agent-profile/`` endpoint, which sources the
authoritative binding from Shizuha ID and projects only the security-relevant
fields.  These tests pin the projection and the fail-CLOSED behaviour: any
inability to positively establish the binding must return a non-200 so the
caller denies rather than defaults open.
"""
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APIClient
from unittest.mock import MagicMock, patch


class InternalUserAgentProfileViewTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()

    def _url(self, user_id):
        return reverse('internal-user-agent-profile', args=[user_id])

    def _id_resp(self, status_code=200, body=None):
        m = MagicMock()
        m.status_code = status_code
        m.json.return_value = body if body is not None else {}
        return m

    @patch('organizations.internal_urls.http_requests.get')
    def test_projects_ownership_fields_from_id(self, mock_get):
        mock_get.return_value = self._id_resp(200, {
            'id': 4242, 'account_type': 'agent',
            'ownership_class': 'personal_default_member',
            'owner_id': '7', 'is_active': True,
            'first_name': 'Sara', 'email': 'sara@agents.shizuha.io',
        })
        resp = self.client.get(self._url(4242))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {
            'user_id': 4242,
            'account_type': 'agent',
            'ownership_class': 'personal_default_member',
            'owner_id': 7,
            'is_active': True,
        })

    @patch('organizations.internal_urls.http_requests.get')
    def test_missing_fields_default_to_safe_empties(self, mock_get):
        mock_get.return_value = self._id_resp(200, {'id': 5, 'account_type': 'human'})
        resp = self.client.get(self._url(5))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {
            'user_id': 5,
            'account_type': 'human',
            'ownership_class': '',
            'owner_id': None,
            'is_active': False,
        })

    @patch('organizations.internal_urls.http_requests.get')
    def test_id_404_propagates_as_404(self, mock_get):
        mock_get.return_value = self._id_resp(404)
        self.assertEqual(self.client.get(self._url(9)).status_code, 404)

    @patch('organizations.internal_urls.http_requests.get')
    def test_id_5xx_fails_closed_as_502(self, mock_get):
        mock_get.return_value = self._id_resp(503)
        self.assertEqual(self.client.get(self._url(9)).status_code, 502)

    @patch('organizations.internal_urls.http_requests.get', side_effect=RuntimeError('boom'))
    def test_id_unreachable_fails_closed_as_502(self, mock_get):
        self.assertEqual(self.client.get(self._url(9)).status_code, 502)

    @patch('organizations.internal_urls.http_requests.get')
    def test_malformed_owner_id_is_nulled(self, mock_get):
        mock_get.return_value = self._id_resp(200, {
            'id': 3, 'account_type': 'agent',
            'ownership_class': 'personal_default_member',
            'owner_id': 'not-a-number', 'is_active': True,
        })
        resp = self.client.get(self._url(3))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()['owner_id'])
