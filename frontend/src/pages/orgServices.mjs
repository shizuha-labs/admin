/**
 * Normalize GET /organizations/<slug>/services/ for Settings.
 * Live contract used to be `{ services: ["admin", ...] }` while the page
 * treated each entry as `{ name, is_enabled }` — empty lock rows.
 */

const SERVICE_DISPLAY_NAMES = {
  admin: 'Admin',
  id: 'ID',
  pulse: 'Pulse',
  notes: 'Notes',
  mail: 'Mail',
  time: 'Time',
  connect: 'Connect',
  wiki: 'Wiki',
  finance: 'Finance',
  books: 'Books',
  inventory: 'Inventory',
  hr: 'HR',
  home: 'Home',
  drive: 'Drive',
  hive: 'Hive',
  cortex: 'Cortex',
  scs: 'SCS',
  origin: 'Origin',
}

export function serviceDisplayName(slug) {
  const raw = String(slug || '').trim()
  if (!raw) return ''
  let key = raw.toLowerCase()
  if (key.startsWith('shizuha-') || key.startsWith('shizuha_')) key = key.slice(8)
  if (SERVICE_DISPLAY_NAMES[key]) return SERVICE_DISPLAY_NAMES[key]
  const titled = key.replace(/[_-]+/g, ' ').trim()
  return titled ? titled.replace(/\b\w/g, (c) => c.toUpperCase()) : raw
}

export function normalizeOrgServices(payload) {
  const raw = Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.services)
      ? payload.services
      : []
  const out = []
  for (const item of raw) {
    if (typeof item === 'string') {
      const slug = item.trim()
      if (!slug) continue
      out.push({
        slug,
        service_slug: slug,
        name: serviceDisplayName(slug),
        is_enabled: true,
      })
      continue
    }
    if (!item || typeof item !== 'object') continue
    const slug = String(item.slug || item.service_slug || '').trim()
    if (!slug) continue
    out.push({
      slug,
      service_slug: slug,
      name: item.name || serviceDisplayName(slug),
      is_enabled: item.is_enabled !== false,
    })
  }
  return out
}
