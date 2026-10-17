import assert from 'node:assert/strict'
import { build } from 'esbuild'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
const { MemoryRouter } = createRequire(import.meta.url)('react-router-dom')
const { QueryClient, QueryClientProvider } = createRequire(import.meta.url)('@tanstack/react-query')
import { Module, createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../../', import.meta.url))
const result = await build({ stdin: { contents: "export { default as Dashboard } from './src/pages/Dashboard.jsx'; export { default as Context } from './src/contexts/AdminContext.jsx';", resolveDir: root }, bundle: true, platform: 'node', format: 'cjs', write: false, jsx: 'automatic', external: ['react', 'react/*', 'react-dom/*', 'react-router-dom', '@tanstack/react-query'], define: { 'import.meta.env': '{}' } })
const compiled = new Module(root + 'dashboard-test.cjs')
compiled.require = createRequire(import.meta.url)
compiled._compile(result.outputFiles[0].text, root + 'dashboard-test.cjs')
const { Dashboard, Context, OrgContext } = compiled.exports
const client = new QueryClient({ defaultOptions: { queries: { retry: false, retryOnMount: false, staleTime: Infinity, gcTime: Infinity } } })
const auth = { user: { id: 3 }, isAuthenticated: true, currentOrganization: { id: 1, slug: 'shizuha', name: 'Shizuha' }, loading: false }
function render(overrides = {}) {
  const context = { ...auth, ...overrides }
  let tree = React.createElement(Context.Provider, { value: context }, React.createElement(Dashboard))
  if (OrgContext) tree = React.createElement(OrgContext.Provider, { value: { currentOrganization: context.currentOrganization, isOrganizationResolved: true, organizations: [] } }, tree)
  return renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter, null, tree)))
    .replace(/<[^>]*>/g, '').replace(/\s+/g, ' ')
}
async function fail(queryKey, status = 503) {
  await client.fetchQuery({ queryKey, staleTime: 0, queryFn: () => Promise.reject(Object.assign(new Error('unavailable'), { response: { status } })), retry: false }).catch(() => {})
}
const loading = render()
assert.match(loading, /Loading/i)
assert.doesNotMatch(loading, /Total Employees0|Pending Tasks0|All caught up/)
const keys = client.getQueryCache().getAll().map(q => q.queryKey)
for (const key of keys) await fail(key)
let text = render()
assert.match(text, /unavailable/i)
assert.doesNotMatch(text, /Total Employees0|Departments0|Teams0|Active0|No employee data|No department data/)
const statsKey = keys.find(k => k[0] === 'org-stats')
const zero = { total_employees: 0, total_departments: 0, total_teams: 0, status_breakdown: {}, largest_departments: [], type_breakdown: {} }
client.setQueryData(statsKey, zero)
text = render()
assert.match(text, /Total Employees0/)
assert.match(text, /Active0/)
client.setQueryData(statsKey, { ...zero, total_employees: 12, total_departments: 4 })
await fail(statsKey)
text = render()
assert.match(text, /Total Employees12/)
assert.match(text, /last (?:successful )?observation/i)
await fail(statsKey, 403)
text = render()
assert.doesNotMatch(text, /Total Employees12/)
assert.doesNotMatch(render({ user: { id: 99 } }), /Total Employees12/)
assert.doesNotMatch(render({ currentOrganization: { id: 2, slug: 'other' } }), /Total Employees12/)
assert.match(render({ currentOrganization: null }), /Select an organization/)
const query = client.getQueryCache().find({ queryKey: statsKey })
assert.equal(query.options.refetchInterval, 30000)
assert.equal(query.options.refetchIntervalInBackground, false)
assert.equal(query.options.refetchOnWindowFocus, true)
await client.fetchQuery({ queryKey: statsKey, staleTime: 0, queryFn: async () => ({ total_employees: 23, total_departments: 2, total_teams: 0, status_breakdown: {} }) })
assert.match(render(), /Total Employees23/)
client.clear()
console.log('actual dashboard: initial failure, measured zero, retained observation, permission failure, actor/tenant isolation and refresh contract PASS')
