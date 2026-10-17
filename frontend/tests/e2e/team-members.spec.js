import { test as base, expect } from '@playwright/test'

// Connect to the operator's isolated, headed QA browser when supplied. This
// suite intercepts every API call and never alters an organization directory.
const test = base.extend({
  browser: async ({ playwright }, use) => {
    const browser = process.env.TEAMS_BROWSER_CDP
      ? await playwright.chromium.connectOverCDP(process.env.TEAMS_BROWSER_CDP)
      : await playwright.chromium.launch({ headless: false, chromiumSandbox: true })
    await use(browser)
    await browser.close()
  },
})
test.use({ viewport: { width: 1440, height: 1000 } })

const team = { id: 13, name: 'CEO Decisions', member_count: 1, color: '#6366f1', team_type: 'permanent', department_name: 'Executive' }
const roster = {
  count: 3, routing_count: 1, directory_count: 2,
  members: [
    { id: null, employee_profile: 1, employee_name: 'Hritik', employee_email: 'owner@example.test', employee_title: 'CEO / Founder', routing_identity: 'pulse:owner@example.test', source: 'pulse-team-roster', routing_member: true, role: 'member' },
    { id: 33, employee_profile: 1, employee_name: 'Hritik', employee_email: 'owner@example.test', employee_title: 'CEO / Founder', source: 'admin-directory', routing_member: false, role: 'lead' },
    { id: 50, employee_profile: 66, employee_name: 'Shizuha', employee_email: 'assistant@example.test', employee_title: 'General Assistant', source: 'admin-directory', routing_member: false, role: 'lead' },
  ],
}
async function click(page, locator) {
  await expect(locator).toBeVisible()
  const rect = await locator.boundingBox()
  const session = await page.context().newCDPSession(page)
  const x = rect.x + rect.width * .45, y = rect.y + rect.height * .55
  for (let step = 1; step <= 12; step++) {
    const t = step / 12
    await session.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 25 + (x - 25) * t, y: 35 + (y - 35) * t + Math.sin(t * Math.PI) * 9 })
    await new Promise(resolve => setTimeout(resolve, 12 + Math.random() * 18))
  }
  await new Promise(resolve => setTimeout(resolve, 70 + Math.random() * 80))
  await session.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 })
  await session.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 })
  await session.detach()
}
async function fixture(page, options = {}) {
  const writes = [], errors = [], organizationReads = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => { localStorage.setItem('shizuha_access_token', 'qa-fixture'); localStorage.setItem('shizuha_admin_current_org', 'test-org') })
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url())
    if (url.pathname === '/v1/hane') return route.fulfill({ json: options.hane || { available: 0 } })
    if (url.pathname.includes('/api/')) {
      if (request.method() !== 'GET') {
        writes.push({ path: url.pathname, method: request.method(), ...(request.postData() ? { body: request.postDataJSON() } : {}) })
        return route.fulfill({ status: 204, body: '' })
      }
      let body = []
      if (url.pathname === '/admin/api/me/') body = { id: 1, username: 'QA', is_staff: false }
      else if (url.pathname === '/admin/api/organizations/') { organizationReads.push(1); body = options.organizations || [{ id: 1, name: 'Test organization', slug: 'test-org' }] }
      else if (url.pathname.endsWith('/teams/13/members/')) {
        if (options.membersFailure?.()) return route.fulfill({ status: 503, json: { error: 'team_roster_unavailable' } })
        body = options.roster || roster
      } else if (url.pathname.endsWith('/teams/')) {
        if (options.teamsFailure) return route.fulfill({ status: 503, json: { error: 'team_roster_unavailable' } })
        body = [team]
      } else if (url.pathname.endsWith('/employees/')) body = []
      return route.fulfill({ json: body })
    }
    if (url.origin !== new URL(process.env.BASE_URL || 'http://shizuha-nginx').origin) return route.abort()
    return route.continue()
  })
  await page.goto('/admin/teams')
  return { writes, errors, organizationReads }
}
test('title and member count reveal one routing identity with separate directory records', async ({ page }) => {
  const { writes, errors } = await fixture(page)
  const opener = page.getByRole('button', { name: 'View 1 members of CEO Decisions', exact: true })
  await click(page, opener)
  const dialog = page.getByRole('dialog', { name: 'CEO Decisions' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('1 routing member · 2 directory records')).toBeVisible()
  await expect(dialog.getByText('Hritik', { exact: true })).toHaveCount(1)
  const routing = dialog.getByRole('region', { name: 'Task-routing members' })
  await expect(routing.getByText('owner@example.test')).toBeVisible()
  await expect(routing.getByText('Shizuha', { exact: true })).toHaveCount(0)
  await expect(dialog.getByRole('region', { name: 'Directory only' }).getByText('Shizuha', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('button', { name: /Remove directory record/ })).toHaveCount(2)
  await page.screenshot({ path: process.env.TEAMS_SCREENSHOT || 'test-results/team-members.png' })
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(opener).toBeFocused()
  await click(page, page.getByRole('button', { name: 'View members of CEO Decisions', exact: true }))
  await expect(dialog).toBeVisible()
  expect(writes).toEqual([])
  expect(errors).toEqual([])
})
test('routing-only and malformed directory rows have no removal path', async ({ page }) => {
  const { writes, errors } = await fixture(page, { roster: { ...roster, directory_count: 0, members: [roster.members[0], { ...roster.members[2], id: null }] } })
  await click(page, page.getByRole('button', { name: 'View members of CEO Decisions', exact: true }))
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByRole('button', { name: /Remove directory record/ })).toHaveCount(0)
  expect(writes).toEqual([]); expect(errors).toEqual([])
})
test('the existing directory remove endpoint receives a concrete directory ID only', async ({ page }) => {
  const { writes } = await fixture(page)
  await click(page, page.getByRole('button', { name: 'View members of CEO Decisions', exact: true }))
  await click(page, page.getByRole('button', { name: 'Remove directory record for Hritik', exact: true }))
  await expect.poll(() => writes.length).toBe(1)
  expect(writes).toEqual([{ path: '/admin/api/organizations/test-org/teams/13/members/33/', method: 'DELETE' }])
})
test('failed roster reads remain unknown, then retry recovers without writes', async ({ page }) => {
  let failing = true
  const { writes, errors } = await fixture(page, { membersFailure: () => failing })
  await click(page, page.getByRole('button', { name: 'View members of CEO Decisions', exact: true }))
  await expect(page.getByRole('alert')).toContainText('Team membership is unknown')
  await expect(page.getByText('No task-routing members.')).toHaveCount(0)
  await expect(page.getByText('Add a directory record')).toHaveCount(0)
  failing = false
  await click(page, page.getByRole('button', { name: 'Try again' }))
  await expect(page.getByText('1 routing member · 2 directory records')).toBeVisible()
  expect(writes).toEqual([]); expect(errors).toEqual([])
})
test('authoritative empty routing does not promote directory-only identities', async ({ page }) => {
  await fixture(page, { roster: { ...roster, routing_count: 0, authoritative_empty: true, members: roster.members.slice(1) } })
  await click(page, page.getByRole('button', { name: 'View members of CEO Decisions', exact: true }))
  await expect(page.getByText('No task-routing members.')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Task-routing members' }).getByText('Hritik', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Directory only' }).getByText('Hritik', { exact: true })).toBeVisible()
})
test('a failed team list is not an empty organization', async ({ page }) => {
  const { writes, errors } = await fixture(page, { teamsFailure: true })
  await expect(page.getByRole('alert')).toContainText('Teams could not be loaded')
  await expect(page.getByText('No teams yet')).toHaveCount(0)
  expect(writes).toEqual([]); expect(errors).toEqual([])
})

test('different profile identities with the same name are not merged', async ({ page }) => {
  await fixture(page, { roster: { ...roster, members: roster.members.map(member => ({ ...member, employee_name: 'Same name' })) } })
  await click(page, page.getByRole('button', { name: 'View members of CEO Decisions', exact: true }))
  await expect(page.getByRole('dialog').getByText('Same name', { exact: true })).toHaveCount(2)
  await expect(page.getByRole('region', { name: 'Directory only' }).getByText('assistant@example.test')).toBeVisible()
})

test('member details fit a mobile viewport with long identity text', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await fixture(page, { roster: { ...roster, members: roster.members.map(member => ({ ...member, employee_email: 'a.very.long.identity.that.must.not.widen.the.dialog@example.test' })) } })
  await click(page, page.getByRole('button', { name: 'View members of CEO Decisions', exact: true }))
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: 'test-results/team-members-mobile.png' })
})

test('settings hydrate, preserve edits across an unchanged refresh, and reset on organization switch', async ({ page }) => {
  const { writes, errors, organizationReads } = await fixture(page, { organizations: [
    { id: 1, name: 'Test organization', slug: 'test-org', website: 'https://first.example.test' },
    { id: 2, name: 'Second organization', slug: 'second-org', website: 'https://second.example.test' },
  ] })
  await click(page, page.getByRole('link', { name: 'Settings', exact: true }))
  const name = page.locator('form').first().locator('input').first()
  await expect(name).toHaveValue('Test organization')
  await click(page, name)
  await page.keyboard.press('ControlOrMeta+A')
  await page.keyboard.insertText('Edited profile')
  await click(page, page.locator('form').first().getByRole('button', { name: 'Save Changes', exact: true }))
  await expect.poll(() => organizationReads.length).toBe(2)
  await expect(name).toHaveValue('Edited profile')
  expect(writes).toEqual([{ path: '/admin/api/organizations/test-org/', method: 'PATCH', body: { name: 'Edited profile', description: '', website: 'https://first.example.test', logo_url: null } }])
  await click(page, page.getByRole('button', { name: 'Test organization', exact: true }))
  await click(page, page.getByRole('button', { name: 'Second organization', exact: true }))
  await expect(name).toHaveValue('Second organization')
  await click(page, page.getByRole('button', { name: 'Second organization', exact: true }))
  await click(page, page.getByRole('button', { name: 'All Organizations', exact: true }))
  await expect(name).toHaveValue('')
  await expect(name).toBeDisabled()
  expect(errors).toEqual([])
})

test('the live long organization and balance leave the mobile member controls on screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true })
  const { writes, errors } = await fixture(page, {
    organizations: [{ id: 1, name: 'Shizuha Global Pvt. Ltd', slug: 'test-org' }],
    hane: { available: 147801.98, fiat: { label: '$1,478.02' } },
  })
  await expect(page.locator('header')).toContainText('$1,478.02')
  // Compare against the actual device/visual viewport, never an innerWidth
  // already expanded by the overflow we are trying to detect.
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await click(page, page.getByRole('button', { name: 'View members of CEO Decisions', exact: true }))
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('1 routing member · 2 directory records')
  const box = await dialog.boundingBox()
  expect(box.x).toBeGreaterThanOrEqual(0)
  expect(box.x + box.width).toBeLessThanOrEqual(390)
  const close = page.getByRole('button', { name: 'Close team members', exact: true })
  const closeBox = await close.boundingBox()
  expect(closeBox.x + closeBox.width).toBeLessThanOrEqual(390)
  await page.screenshot({ path: 'test-results/team-members-live-mobile.png' })
  await click(page, close)
  await expect(dialog).not.toBeVisible()
  expect(writes).toEqual([]); expect(errors).toEqual([])
  await cdp.detach()
})
