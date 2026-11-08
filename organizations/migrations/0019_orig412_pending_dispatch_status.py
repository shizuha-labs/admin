from django.db import migrations, models

import organizations.models


class Migration(migrations.Migration):
    """ORIG-412: add the ``pending_dispatch`` grant status (metadata-only; the
    burn moves post-acceptance in application code)."""

    dependencies = [('organizations', '0018_jit_kubernetes_dispatch')]

    operations = [
        migrations.AlterField(
            model_name='jitelevatedaccessgrant',
            name='status',
            field=models.CharField(
                choices=organizations.models.JITElevatedAccessGrant.STATUS_CHOICES,
                db_index=True,
                default='pending',
                max_length=20,
            ),
        ),
    ]
