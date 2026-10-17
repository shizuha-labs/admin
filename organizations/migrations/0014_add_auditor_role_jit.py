"""
Migration: Add 'auditor' to JITElevatedAccessGrant.requested_role choices.

PLS-409 follow-up: OrganizationMembership.ROLE_CHOICES now includes 'auditor',
and JITElevatedAccessGrant.requested_role uses the same choices constant.
This migration updates that field's choices to match.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Add auditor role to JITElevatedAccessGrant.requested_role choices."""

    dependencies = [
        ('organizations', '0013_add_auditor_role'),
    ]

    operations = [
        migrations.AlterField(
            model_name='jitelevatedaccessgrant',
            name='requested_role',
            field=models.CharField(
                choices=[
                    ('owner', 'Owner'),
                    ('admin', 'Admin'),
                    ('member', 'Member'),
                    ('viewer', 'Viewer'),
                    ('auditor', 'Auditor'),
                ],
                max_length=20,
            ),
        ),
    ]
