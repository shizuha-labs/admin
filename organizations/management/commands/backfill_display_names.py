"""
Backfill display_name on OrganizationMembership from shizuha-id.

Usage:
    python manage.py backfill_display_names
"""
import os
import requests
import logging

from django.core.management.base import BaseCommand
from organizations.models import OrganizationMembership

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Backfill display_name on memberships from shizuha-id'

    def handle(self, *args, **options):
        shizuha_id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')

        memberships = OrganizationMembership.objects.filter(
            user_id__isnull=False,
            is_active=True,
        ).filter(
            # Missing display_name
            display_name__isnull=True,
        ) | OrganizationMembership.objects.filter(
            user_id__isnull=False,
            is_active=True,
            display_name='',
        )

        # Collect unique user_ids
        user_ids = set(memberships.values_list('user_id', flat=True))
        self.stdout.write(f"Found {len(user_ids)} users to look up")

        # Fetch usernames from shizuha-id
        user_map = {}
        for user_id in user_ids:
            try:
                resp = requests.get(
                    f'{shizuha_id_url}/internal/users/{user_id}/',
                    timeout=5,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    username = data.get('username', '')
                    if username:
                        user_map[user_id] = username
                        self.stdout.write(f"  User {user_id}: {username}")
            except Exception as e:
                self.stderr.write(f"  Failed to fetch user {user_id}: {e}")

        # Update memberships
        updated = 0
        for user_id, username in user_map.items():
            count = OrganizationMembership.objects.filter(
                user_id=user_id,
                is_active=True,
            ).filter(
                display_name__isnull=True,
            ).update(display_name=username)
            count += OrganizationMembership.objects.filter(
                user_id=user_id,
                is_active=True,
                display_name='',
            ).update(display_name=username)
            updated += count

        self.stdout.write(self.style.SUCCESS(f"Updated {updated} memberships"))
