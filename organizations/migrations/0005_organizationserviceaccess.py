from django.db import migrations, models
import django.db.models.deletion


DEFAULT_SERVICES = [
    'admin', 'id', 'pulse', 'notes', 'mail', 'time',
    'connect', 'wiki', 'finance', 'books', 'inventory', 'hr', 'home',
]


def populate_existing_orgs(apps, schema_editor):
    """Create service access entries for all existing organizations."""
    Organization = apps.get_model('organizations', 'Organization')
    OrganizationServiceAccess = apps.get_model('organizations', 'OrganizationServiceAccess')

    for org in Organization.objects.filter(is_active=True):
        for slug in DEFAULT_SERVICES:
            OrganizationServiceAccess.objects.get_or_create(
                organization=org,
                service_slug=slug,
                defaults={'is_enabled': True},
            )


def reverse_populate(apps, schema_editor):
    OrganizationServiceAccess = apps.get_model('organizations', 'OrganizationServiceAccess')
    OrganizationServiceAccess.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0004_remove_project_models'),
    ]

    operations = [
        migrations.CreateModel(
            name='OrganizationServiceAccess',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('service_slug', models.CharField(db_index=True, max_length=50)),
                ('is_enabled', models.BooleanField(default=True)),
                ('granted_by_id', models.IntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='service_access', to='organizations.organization')),
            ],
            options={
                'db_table': 'organizations_service_access',
                'ordering': ['service_slug'],
                'unique_together': {('organization', 'service_slug')},
            },
        ),
        migrations.RunPython(populate_existing_orgs, reverse_populate),
    ]
