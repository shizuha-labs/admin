from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('organizations', '0017_hive671_membership_source_operation_id')]

    operations = [
        migrations.AddField(
            model_name='jitelevatedaccessgrantuse',
            name='dispatch_status',
            field=models.CharField(db_index=True, default='pending', max_length=20),
        ),
        migrations.AddField(
            model_name='jitelevatedaccessgrantuse',
            name='dispatch_attempts',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='jitelevatedaccessgrantuse',
            name='origin_run_id',
            field=models.BigIntegerField(blank=True, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='jitelevatedaccessgrantuse',
            name='origin_run_number',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='jitelevatedaccessgrantuse',
            name='last_dispatch_error',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='jitelevatedaccessgrantuse',
            name='dispatched_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='jitelevatedaccessgrantuse',
            name='completed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
