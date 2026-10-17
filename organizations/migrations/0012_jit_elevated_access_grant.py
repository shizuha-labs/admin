# Generated for PLAT-1346 JIT elevated access.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0011_project_member'),
    ]

    operations = [
        migrations.CreateModel(
            name='JITElevatedAccessGrant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('requester_user_id', models.IntegerField(db_index=True)),
                ('requester_email', models.EmailField(blank=True, default='', max_length=254)),
                ('scope', models.CharField(db_index=True, max_length=100)),
                ('requested_role', models.CharField(choices=[('owner', 'Owner'), ('admin', 'Admin'), ('member', 'Member'), ('viewer', 'Viewer')], max_length=20)),
                ('reason', models.TextField()),
                ('task_key', models.CharField(db_index=True, max_length=32)),
                ('ttl_seconds', models.PositiveIntegerField(default=3600)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('denied', 'Denied'), ('revoked', 'Revoked')], db_index=True, default='pending', max_length=20)),
                ('approval_path', models.CharField(choices=[('policy', 'Policy auto-approved'), ('owning_team', 'Owning-team approval')], default='owning_team', max_length=20)),
                ('owning_team', models.CharField(db_index=True, default='admin-platform', max_length=64)),
                ('risk_level', models.CharField(choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')], default='medium', max_length=20)),
                ('policy_slug', models.CharField(blank=True, default='', max_length=100)),
                ('decided_by_user_id', models.IntegerField(blank=True, null=True)),
                ('decided_by_email', models.EmailField(blank=True, default='', max_length=254)),
                ('decision_note', models.TextField(blank=True, default='')),
                ('decided_at', models.DateTimeField(blank=True, null=True)),
                ('expires_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='jit_elevation_grants', to='organizations.organization')),
            ],
            options={
                'db_table': 'organizations_jit_elevated_access_grant',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['requester_user_id', 'status', 'expires_at'], name='organizatio_request_e5db50_idx'),
                    models.Index(fields=['organization', 'scope', 'status'], name='organizatio_organiz_3c5af8_idx'),
                    models.Index(fields=['task_key'], name='organizatio_task_ke_0b6093_idx'),
                ],
            },
        ),
    ]
