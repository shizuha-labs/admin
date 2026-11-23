"""
Heal phantom work_email values on employee profiles (PLAT-12219).

About 33 profiles still store ``<username>@shizuha.com`` while shizuha-id
holds the canonical ``<username>@agents.shizuha.io``. The profile has no
linked membership user, so the mapping is by username: the local part of
the stored address is looked up in shizuha-id, and the profile is repointed
at that account's email.

Dry-run is the default. It prints a before/after manifest and writes
nothing, so the change is reviewable and reversible. ``--execute`` applies
it. Addresses that are already canonical (the keep-as-is list, plus anything
shizuha-id does not recognise) are reported and left untouched.

Usage:
    python manage.py heal_employee_work_emails
    python manage.py heal_employee_work_emails --execute
"""
import os
from collections import Counter

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from organizations.models import EmployeeProfile

# Already canonical. Never rewritten, even if shizuha-id disagrees.
KEEP_AS_IS = ('hiro', 'san', 'saki', 'waka', 'rui')

PHANTOM_DOMAIN = '@shizuha.com'


class Command(BaseCommand):
    help = 'Repoint phantom <user>@shizuha.com work emails at the shizuha-id canonical address (dry-run by default).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--execute', action='store_true',
            help='Apply the changes. Without this the command only prints the manifest.',
        )

    def handle(self, *args, **options):
        shizuha_id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
        execute = options['execute']

        profiles = EmployeeProfile.objects.filter(
            work_email__iendswith=PHANTOM_DOMAIN,
        ).order_by('work_email')

        # Resolution is injectable so the mapping can be verified without the
        # network. The default reads shizuha-id.
        resolve = options.get('resolve') or self._canonical_email

        changes = []
        kept = []
        unresolved = []
        for profile in profiles:
            local = profile.work_email.split('@', 1)[0].strip().lower()
            if not local or local in KEEP_AS_IS:
                kept.append((profile.work_email, 'keep-as-is'))
                continue
            canonical, status_code = resolve(shizuha_id_url, local)
            if not canonical or canonical.lower() == profile.work_email.lower():
                unresolved.append((profile.work_email, status_code))
                continue
            changes.append((profile, profile.work_email, canonical))

        self.stdout.write(f"profiles with {PHANTOM_DOMAIN}: {profiles.count()}")
        self.stdout.write(f"would change: {len(changes)}  kept: {len(kept)}  unresolved: {len(unresolved)}")
        for profile, before, after in changes:
            self.stdout.write(f"  CHANGE {before} -> {after}")
        for email, reason in kept:
            self.stdout.write(f"  SKIP   {email} ({reason})")
        # A dry-run that resolves nothing must say why. A wall of 401s is an
        # auth failure, not 33 unknown users.
        status_counts = Counter(code for _, code in unresolved)
        for email, code in unresolved:
            self.stdout.write(f"  SKIP   {email} (shizuha-id HTTP {code})")
        if status_counts:
            summary = ', '.join(f"{code}: {n}" for code, n in sorted(status_counts.items()))
            self.stdout.write(f"unresolved by HTTP status: {summary}")

        if not execute:
            self.stdout.write("dry-run: nothing written. Re-run with --execute to apply.")
            return

        with transaction.atomic():
            for profile, before, after in changes:
                profile.work_email = after
                profile.save(update_fields=['work_email'])
        self.stdout.write(self.style.SUCCESS(f"applied {len(changes)} change(s)"))

    def _service_headers(self):
        """Auth for the admin to shizuha-id hop. The token is never logged.

        shizuha-id's ``/internal/users/`` list requires an authenticated caller
        and ignores ``?username=``. The by-username route is the service lookup
        (``InternalUserByUsernameView``), and it checks
        ``X-Internal-Service-Token`` against its ``INTERNAL_SERVICE_TOKEN``.
        """
        token = str(getattr(settings, 'ADMIN_INTERNAL_SERVICE_TOKEN', '') or '')
        headers = {'X-Internal-Service': 'shizuha-admin'}
        if token:
            headers['X-Internal-Service-Token'] = token
        return headers

    def _canonical_email(self, base_url, username):
        """Return ``(email, http_status)`` for a username.

        ``email`` is '' unless shizuha-id returns 200 with an address. The
        status is returned either way so a dry-run can tell an auth failure
        (401) from an unknown user (404) instead of reporting both as skipped.
        """
        try:
            resp = requests.get(
                f'{base_url}/internal/users/by-username/',
                params={'username': username},
                headers=self._service_headers(),
                timeout=5,
            )
        except requests.RequestException:
            return '', 'unreachable'
        if resp.status_code != 200:
            return '', resp.status_code
        data = resp.json()
        if isinstance(data, dict) and (data.get('username') or '').lower() == username:
            return (data.get('email') or '').strip(), 200
        return '', 200
