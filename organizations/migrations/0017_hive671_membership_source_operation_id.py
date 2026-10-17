from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0016_jit_peer_approval_contract'),
    ]

    operations = [
        migrations.AddField(
            model_name='organizationmembership',
            name='source_operation_id',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
    ]
