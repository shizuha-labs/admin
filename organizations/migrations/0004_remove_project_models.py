"""
Migration to remove Project and ProjectMembership models from shizuha-admin.

Projects are now solely managed by shizuha-pulse. This migration:
1. Removes the project FK from Team model
2. Adds pulse_project_id IntegerField to Team (for project-based teams)
3. Drops the ProjectMembership table
4. Drops the Project table
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0003_auto_founder_profile'),
    ]

    operations = [
        # Step 1: Remove the project FK from Team model
        migrations.RemoveField(
            model_name='team',
            name='project',
        ),

        # Step 2: Add pulse_project_id to Team for referencing Pulse projects
        migrations.AddField(
            model_name='team',
            name='pulse_project_id',
            field=models.IntegerField(
                null=True,
                blank=True,
                help_text='Project ID in shizuha-pulse (for project-based teams)'
            ),
        ),

        # Step 3: Drop ProjectMembership table (has FK to Project)
        migrations.DeleteModel(
            name='ProjectMembership',
        ),

        # Step 4: Drop Project table
        migrations.DeleteModel(
            name='Project',
        ),
    ]
