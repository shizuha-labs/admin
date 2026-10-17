from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0008_membershipchange'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='mission',
            field=models.TextField(blank=True, default='', help_text='Company-OS: mission statement'),
        ),
        migrations.AddField(
            model_name='organization',
            name='vision',
            field=models.TextField(blank=True, default='', help_text='Company-OS: vision statement'),
        ),
        migrations.AddField(
            model_name='organization',
            name='strategic_bets',
            field=models.JSONField(blank=True, default=list, help_text='Company-OS: list of strategic bets'),
        ),
        migrations.AddField(
            model_name='organization',
            name='values_summary',
            field=models.TextField(blank=True, default='', help_text='Company-OS: short values summary'),
        ),
        migrations.AddField(
            model_name='organization',
            name='handbook_url',
            field=models.URLField(blank=True, help_text='Company-OS: link to the long-form wiki handbook', null=True),
        ),
    ]
