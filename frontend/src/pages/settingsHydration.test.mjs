/**
 * PLAT-5084 — pure hydration helpers (no DOM).
 * Run: node --test src/pages/settingsHydration.test.mjs
 */
import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { profileFieldsFromOrg, mergeProfileUpdate } from './settingsHydration.mjs'

describe('profileFieldsFromOrg', () => {
  it('returns empty strings when org is null (pre-hydration)', () => {
    assert.deepEqual(profileFieldsFromOrg(null), {
      name: '',
      description: '',
      website: '',
      logoUrl: '',
      billingEmail: '',
    })
  })

  it('maps server fields including name for selected org', () => {
    const fields = profileFieldsFromOrg({
      slug: 'shizuha',
      name: 'Shizuha Global Pvt. Ltd',
      description: 'desc',
      website: 'https://shizuha.com',
      logo_url: '/logo.png',
      billing_email: 'billing@shizuha.com',
    })
    assert.equal(fields.name, 'Shizuha Global Pvt. Ltd')
    assert.equal(fields.logoUrl, '/logo.png')
    assert.equal(fields.billingEmail, 'billing@shizuha.com')
  })
})

describe('mergeProfileUpdate', () => {
  const hydrated = {
    slug: 'shizuha',
    name: 'Shizuha Global Pvt. Ltd',
    description: 'kept',
    website: 'https://shizuha.com',
    logo_url: '/logo.png',
  }

  it('does not blank name when form name is still empty (unhydrated save)', () => {
    const payload = mergeProfileUpdate(hydrated, {
      name: '',
      description: 'new desc',
      website: '',
      logoUrl: '',
    })
    assert.equal(payload.name, 'Shizuha Global Pvt. Ltd')
    assert.equal(payload.description, 'new desc')
  })

  it('allows intentional name edits when non-empty', () => {
    const payload = mergeProfileUpdate(hydrated, {
      name: 'New Name',
      description: '',
      website: 'https://example.com',
      logoUrl: '',
    })
    assert.equal(payload.name, 'New Name')
    assert.equal(payload.website, 'https://example.com')
  })
})
