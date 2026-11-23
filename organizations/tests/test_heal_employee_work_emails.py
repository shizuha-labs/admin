"""The work_email heal must tolerate the token the pod actually holds.

The admin pod's ADMIN_INTERNAL_SERVICE_TOKEN ends in a newline. requests
rejects a header value containing one with InvalidHeader before the request
is sent, so a dry-run reported every row as unreachable.
"""
from django.test import SimpleTestCase, override_settings

from organizations.management.commands.heal_employee_work_emails import Command


class ServiceHeaderTests(SimpleTestCase):
    @override_settings(ADMIN_INTERNAL_SERVICE_TOKEN='svc-token\n')
    def test_newline_terminated_token_is_stripped(self):
        headers = Command()._service_headers()
        self.assertEqual(headers['X-Internal-Service-Token'], 'svc-token')
        # A header value with a newline is illegal and requests refuses to send it.
        self.assertNotIn('\n', headers['X-Internal-Service-Token'])

    @override_settings(ADMIN_INTERNAL_SERVICE_TOKEN='')
    def test_blank_token_sends_no_credential_header(self):
        headers = Command()._service_headers()
        self.assertNotIn('X-Internal-Service-Token', headers)
        self.assertEqual(headers['X-Internal-Service'], 'shizuha-admin')
