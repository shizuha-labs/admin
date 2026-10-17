"""Optional installation-owned Company OS seed, never a public business plan."""
import json
import os
from pathlib import Path
from django.db import migrations


_FIELDS = {'mission', 'vision', 'strategic_bets', 'values_summary'}


def _payload():
    filename = os.environ.get('ADMIN_COMPANY_OS_SEED_FILE', '')
    if not filename:
        return None
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate company seed field')
            result[key] = value
        return result
    try:
        data = json.loads(Path(filename).read_text(), object_pairs_hook=unique_pairs)
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError('Cannot read reviewed Company OS seed payload') from exc
    if (not isinstance(data, dict) or set(data) != {'schema', 'organizations'}
            or data['schema'] != 'shizuha.company-os-seed.v1'
            or not isinstance(data['organizations'], list)):
        raise ValueError('Invalid Company OS seed schema')
    return data['organizations']


def seed(apps, schema_editor):
    targets = _payload()
    if targets is None:
        return
    Organization = apps.get_model('organizations', 'Organization')
    alias = schema_editor.connection.alias
    pending = []
    seen = set()
    for target in targets:
        if (not isinstance(target, dict) or set(target) != {'id', 'slug', 'fields'}
                or type(target['id']) is not int or target['id'] <= 0
                or not isinstance(target['slug'], str) or not target['slug']
                or not isinstance(target['fields'], dict) or not target['fields']
                or not set(target['fields']) <= _FIELDS):
            raise ValueError('Invalid Company OS target')
        if target['id'] in seen:
            raise ValueError('Duplicate Company OS organization')
        seen.add(target['id'])
        for field, value in target['fields'].items():
            if field == 'strategic_bets':
                valid = isinstance(value, list) and all(isinstance(item, str) for item in value)
            else:
                valid = isinstance(value, str)
            if not valid:
                raise ValueError('Invalid Company OS field shape')
        organization = Organization.objects.using(alias).filter(pk=target['id'],slug=target['slug']).first()
        if organization is None:
            raise ValueError('Company OS target identity does not match this installation')
        pending.append((organization,target['fields']))
    # Complete payload and every exact ID+slug binding are checked before writes.
    for organization, fields in pending:
        for field, value in fields.items():
            setattr(organization,field,value)
        organization.save(using=alias,update_fields=[*fields,'updated_at'])


def unseed(apps, schema_editor):
    # Applied installation records are never removed by a source rollback.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0009_company_os'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
