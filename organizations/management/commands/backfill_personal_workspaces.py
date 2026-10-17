"""
Backfill: make sure every known user has a personal workspace org
(operator 2026-07-11). Idempotent; safe to re-run.

Creates a personal workspace for any active org member who lacks one, named
with the placeholder "My Workspace". The proper "<User>'s Workspace" name is
applied by ensure_personal_workspace's self-heal on the user's next token mint
(shizuha-id passes the real first name then). We deliberately do NOT bulk-rename
here from admin-local data: the only local signal is an email local part
(often a machine/CI handle), and renaming to that would both look wrong AND
defeat the self-heal (which keys on the "My Workspace" placeholder).

    python manage.py backfill_personal_workspaces [--dry-run]
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from organizations.models import Organization, OrganizationMembership


class Command(BaseCommand):
    help = "Create a personal workspace for any user missing one (idempotent; names self-heal on next login)."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        dry = opts['dry_run']

        emails = {}
        for m in OrganizationMembership.objects.filter(is_active=True).values('user_id', 'user_email'):
            emails.setdefault(m['user_id'], m['user_email'] or '')

        have = set(
            Organization.objects.filter(is_personal=True, is_active=True)
            .values_list('owner_id', flat=True)
        )
        created = 0
        for uid, email in emails.items():
            if uid in have:
                continue
            self.stdout.write(f"[create] user {uid} -> 'My Workspace' (self-heals to <User>'s Workspace on next login)")
            if not dry:
                with transaction.atomic():
                    slug = f"personal-{uid}"
                    org = Organization.objects.select_for_update().filter(slug=slug).first()
                    if org is None:
                        org = Organization.objects.create(
                            name='My Workspace', slug=slug, owner_id=uid,
                            plan='free', is_personal=True,
                        )
                    OrganizationMembership.objects.get_or_create(
                        organization=org, user_id=uid,
                        defaults=dict(user_email=email, role='owner',
                                      is_pending=False, accepted_at=timezone.now()),
                    )
            created += 1

        self.stdout.write(self.style.SUCCESS(f"{'(dry-run) ' if dry else ''}created={created}"))
