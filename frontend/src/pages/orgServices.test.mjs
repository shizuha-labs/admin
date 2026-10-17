/**
 * Run: node --test src/pages/orgServices.test.mjs
 */
import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { normalizeOrgServices, serviceDisplayName } from './orgServices.mjs'

describe('serviceDisplayName', () => {
  it('maps known slugs and strips the shizuha- prefix', () => {
    assert.equal(serviceDisplayName('pulse'), 'Pulse')
    assert.equal(serviceDisplayName('id'), 'ID')
    assert.equal(serviceDisplayName('hr'), 'HR')
    assert.equal(serviceDisplayName('shizuha-wiki'), 'Wiki')
  })
})

describe('normalizeOrgServices', () => {
  it('treats a bare slug list as enabled named services', () => {
    const services = normalizeOrgServices({
      organization: 'personal-3',
      services: ['admin', 'pulse', 'books'],
    })
    assert.deepEqual(services.map((s) => [s.slug, s.name, s.is_enabled]), [
      ['admin', 'Admin', true],
      ['pulse', 'Pulse', true],
      ['books', 'Books', true],
    ])
  })

  it('preserves explicit disabled catalog rows', () => {
    const services = normalizeOrgServices({
      services: [
        { slug: 'pulse', name: 'Pulse', is_enabled: true },
        { service_slug: 'hive', is_enabled: false },
      ],
    })
    assert.equal(services[0].is_enabled, true)
    assert.equal(services[1].slug, 'hive')
    assert.equal(services[1].name, 'Hive')
    assert.equal(services[1].is_enabled, false)
  })

  it('returns an empty list when the payload has no services', () => {
    assert.deepEqual(normalizeOrgServices({ organization: 'x' }), [])
    assert.deepEqual(normalizeOrgServices(null), [])
  })
})
