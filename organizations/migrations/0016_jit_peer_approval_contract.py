from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0015_rename_organizatio_request_e5db50_idx_organizatio_request_29c64b_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='jitelevatedaccessgrant',
            name='approver_team',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='jit_grants_to_approve',
                to='organizations.team',
            ),
        ),
        migrations.AddField(
            model_name='jitelevatedaccessgrant',
            name='constraint_digest',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='jitelevatedaccessgrant',
            name='max_uses',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='jitelevatedaccessgrant',
            name='policy_digest',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='jitelevatedaccessgrant',
            name='policy_key',
            field=models.CharField(blank=True, db_index=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='jitelevatedaccessgrant',
            name='policy_version',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='jitelevatedaccessgrant',
            name='target_constraints',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='jitelevatedaccessgrant',
            name='target_role',
            field=models.CharField(
                blank=True,
                choices=[('lead', 'Team Lead'), ('member', 'Member'), ('advisor', 'Advisor')],
                default='',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='jitelevatedaccessgrant',
            name='target_team',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='jit_grants_targeting_team',
                to='organizations.team',
            ),
        ),
        migrations.AddField(
            model_name='jitelevatedaccessgrant',
            name='target_user_id',
            field=models.IntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='jitelevatedaccessgrant',
            name='uses_consumed',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name='JITElevatedAccessGrantEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(db_index=True, max_length=40)),
                ('actor_user_id', models.IntegerField(blank=True, db_index=True, null=True)),
                ('actor_email', models.EmailField(blank=True, default='', max_length=254)),
                ('source', models.CharField(default='api', max_length=40)),
                ('detail', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('grant', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='events', to='organizations.jitelevatedaccessgrant')),
            ],
            options={
                'db_table': 'organizations_jit_elevated_access_grant_event',
                'ordering': ['created_at', 'id'],
                'indexes': [models.Index(fields=['grant', 'event_type', 'created_at'], name='jit_event_grant_type_idx')],
            },
        ),
        migrations.CreateModel(
            name='JITElevatedAccessGrantUse',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('idempotency_key', models.CharField(max_length=100)),
                ('request_digest', models.CharField(max_length=64)),
                ('result', models.JSONField(default=dict)),
                ('actor_user_id', models.IntegerField()),
                ('actor_email', models.EmailField(blank=True, default='', max_length=254)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('grant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='uses', to='organizations.jitelevatedaccessgrant')),
            ],
            options={
                'db_table': 'organizations_jit_elevated_access_grant_use',
                'indexes': [models.Index(fields=['grant', 'created_at'], name='jit_use_grant_created_idx')],
                'constraints': [models.UniqueConstraint(fields=('grant', 'idempotency_key'), name='unique_jit_grant_idempotency_key')],
            },
        ),
    ]
