/** PLAT-5084 — pure org-profile hydration helpers (no React). */

export function profileFieldsFromOrg(org) {
  if (!org) {
    return { name: '', description: '', website: '', logoUrl: '', billingEmail: '' }
  }
  return {
    name: org.name || '',
    description: org.description || '',
    website: org.website || '',
    logoUrl: org.logo_url || '',
    billingEmail: org.billing_email || '',
  }
}

/**
 * Merge form edits onto the last hydrated org snapshot so an unhydrated empty
 * local field cannot blank a persisted server value on save.
 */
export function mergeProfileUpdate(hydratedOrg, form) {
  const base = profileFieldsFromOrg(hydratedOrg)
  return {
    name: form.name !== '' ? form.name : base.name,
    description: form.description,
    website: form.website || null,
    logo_url: form.logoUrl || null,
  }
}
