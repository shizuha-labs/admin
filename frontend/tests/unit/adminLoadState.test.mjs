import assert from 'node:assert/strict'
import http from 'node:http'
import axios from 'axios'
import { loadAdminData, loadingFailure } from '../../src/contexts/adminLoadState.mjs'

let profileStatus = 403
let organizationStatus = 200
let organizations = [{ id: 1, slug: 'sample', name: 'Sample Organization' }]
const requests = []
const server = http.createServer((request, response) => {
  requests.push(request.url)
  const profile = request.url === '/me/'
  response.writeHead(profile ? profileStatus : organizationStatus, { 'Content-Type': 'application/json' })
  response.end(JSON.stringify(profile ? profileStatus === 200 ? { id: 2, is_staff: false } : { error: 'service_access_denied' }
    : organizationStatus === 200 ? { results: organizations } : { error: 'unavailable' }))
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const api = axios.create({ baseURL: `http://127.0.0.1:${server.address().port}`, proxy: false })
const userApi = { me: () => api.get('/me/') }
const organizationsApi = { list: () => api.get('/organizations/') }
try {
  // Exact observed mixed HTTP statuses: the successful org result must survive.
  let result = await loadAdminData(userApi, organizationsApi)
  assert.deepEqual(result.organizations, organizations)
  assert.equal(result.user, null)
  assert.equal(loadingFailure(result.errors).kind, 'denied')
  assert.deepEqual(requests.sort(), ['/me/', '/organizations/'])

  profileStatus = 200
  result = await loadAdminData(userApi, organizationsApi)
  assert.equal(result.user.id, 2)
  assert.deepEqual(result.organizations, organizations)
  assert.equal(loadingFailure(result.errors), null)

  organizationStatus = 503
  result = await loadAdminData(userApi, organizationsApi)
  assert.equal(result.user.id, 2)
  assert.equal(result.organizations, undefined, 'failure must not become a successful empty list')
  assert.equal(loadingFailure(result.errors).kind, 'unavailable')

  profileStatus = 403
  result = await loadAdminData(userApi, organizationsApi)
  assert.equal(loadingFailure(result.errors).kind, 'denied', 'access failure takes precedence over transient failure')

  profileStatus = 200; organizationStatus = 200; organizations = []
  result = await loadAdminData(userApi, organizationsApi)
  assert.deepEqual(result.organizations, [], 'genuine empty success remains distinguishable')
  assert.equal(loadingFailure(result.errors), null)

  result = await loadAdminData(userApi, { list: async () => ({ data: { detail: 'not a list' } }) })
  assert.equal(result.organizations, undefined)
  assert.equal(loadingFailure(result.errors).kind, 'unavailable')
  console.log('PASS real HTTP mixed-status Admin loading, retry, denial, failure and genuine empty states')
} finally { await new Promise(resolve => server.close(resolve)) }
