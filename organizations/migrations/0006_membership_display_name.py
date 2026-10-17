from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0005_organizationserviceaccess'),
    ]

    operations = [
        migrations.AddField(
            model_name='organizationmembership',
            name='display_name',
            field=models.CharField(
                blank=True,
                help_text='Cached display name from auth service (username).',
                max_length=150,
                null=True,
            ),
        ),
    ]
