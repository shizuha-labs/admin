from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0018_jit_kubernetes_dispatch'),
    ]

    operations = [
        migrations.CreateModel(
            name='WaiverIssuanceGrant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('subject_user_id', models.IntegerField(db_index=True)),
                ('subject_email', models.EmailField(max_length=254)),
                ('waiver_type', models.CharField(choices=[('receipt.deploy_verify_waiver', 'Deploy-verify waiver')], max_length=64)),
                ('expires_at', models.DateTimeField(blank=True, null=True)),
                ('max_uses', models.PositiveIntegerField(blank=True, null=True)),
                ('use_count', models.PositiveIntegerField(default=0)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('issued_by_user_id', models.IntegerField()),
                ('issued_by_email', models.EmailField(blank=True, default='', max_length=254)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='waiver_grants', to='organizations.organization')),
            ],
            options={
                'db_table': 'organizations_waiver_issuance_grant',
                'indexes': [models.Index(fields=['subject_email', 'waiver_type', 'revoked_at'], name='org_waiver_subject_type_idx')],
            },
        ),
    ]
