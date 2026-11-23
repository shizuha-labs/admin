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

import requests
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
            canonical = resolve(shizuha_id_url, local)
            if not canonical or canonical.lower() == profile.work_email.lower():
                unresolved.append((profile.work_email, 'no shizuha-id match'))
                continue
            changes.append((profile, profile.work_email, canonical))

        self.stdout.write(f"profiles with {PHANTOM_DOMAIN}: {profiles.count()}")
        self.stdout.write(f"would change: {len(changes)}  kept: {len(kept)}  unresolved: {len(unresolved)}")
        for profile, before, after in changes:
            self.stdout.write(f"  CHANGE {before} -> {after}")
        for email, reason in kept + unresolved:
            self.stdout.write(f"  SKIP   {email} ({reason})")

        if not execute:
            self.stdout.write("dry-run: nothing written. Re-run with --execute to apply.")
            return

        with transaction.atomic():
            for profile, before, after in changes:
                profile.work_email = after
                profile.save(update_fields=['work_email'])
        self.stdout.write(self.style.SUCCESS(f"applied {len(changes)} change(s)"))

    def _canonical_email(self, base_url, username):
        """The shizuha-id email for a username, or '' when it can't be resolved.

        shizuha-id exposes ``/internal/users/{id}/`` (see
        backfill_display_names). These profiles have no linked user id, so the
        lookup is by username. An unknown username, a non-200, or a transport
        error leaves the row unresolved rather than guessed.
        """
        try:
            resp = requests.get(
                f'{base_url}/internal/users/',
                params={'username': username},
                timeout=5,
            )
        except requests.RequestException:
            return ''
        if resp.status_code != 200:
            return ''
        data = resp.json()
        rows = data if isinstance(data, list) else data.get('results', [data])
        for row in rows:
            if isinstance(row, dict) and (row.get('username') or '').lower() == username:
                return (row.get('email') or '').strip()
        return ''
