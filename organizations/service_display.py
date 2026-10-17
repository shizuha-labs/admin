"""Human names for organization service slugs.

Org settings and MCP list endpoints must not render a raw slug, and they
must not assume the caller already received `{name, is_enabled}` objects.
"""

SERVICE_DISPLAY_NAMES = {
    'admin': 'Admin',
    'id': 'ID',
    'pulse': 'Pulse',
    'notes': 'Notes',
    'mail': 'Mail',
    'time': 'Time',
    'connect': 'Connect',
    'wiki': 'Wiki',
    'finance': 'Finance',
    'books': 'Books',
    'inventory': 'Inventory',
    'hr': 'HR',
    'home': 'Home',
    'drive': 'Drive',
    'hive': 'Hive',
    'cortex': 'Cortex',
    'scs': 'SCS',
    'origin': 'Origin',
}


def service_display_name(slug):
    raw = (slug or '').strip()
    if not raw:
        return ''
    key = raw.lower()
    if key.startswith('shizuha-') or key.startswith('shizuha_'):
        key = key[8:]
    if key in SERVICE_DISPLAY_NAMES:
        return SERVICE_DISPLAY_NAMES[key]
    titled = key.replace('_', ' ').replace('-', ' ').strip()
    return titled.title() if titled else raw


def serialize_org_service(access):
    slug = access.service_slug
    return {
        'slug': slug,
        'service_slug': slug,
        'name': service_display_name(slug),
        'is_enabled': bool(access.is_enabled),
    }
