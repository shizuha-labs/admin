import { test, expect } from '@playwright/test'

test('mixed profile denial preserves organization data and renders access failure, then recovers', async ({ page }, testInfo) => {
  let denied = true
  await page.route('**/admin/api/me/', route => route.fulfill({
    status: denied ? 403 : 200, contentType: 'application/json',
    body: JSON.stringify(denied ? { error: 'service_access_denied' } : { id: 2, is_staff: false }),
  }))
  await page.route('**/admin/api/organizations/', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify([{ id: 1, name: 'Sample Organization', slug: 'sample' }]),
  }))
  await page.route('**/admin/api/organizations/sample/org-chart/stats/', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({ total_employees: 0, total_departments: 0, total_teams: 0, status_breakdown: {}, type_breakdown: {}, largest_departments: [] }),
  }))
  await page.goto('/admin/dashboard')
  await expect(page.getByRole('heading', { name: 'Admin access required' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'No Organizations' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Sample Organization', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('access-denied.png') })
  denied = false
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('successful empty organization response still renders the genuine empty state', async ({ page }) => {
  await page.route('**/admin/api/me/', route => route.fulfill({ contentType: 'application/json', body: '{"id":2,"is_staff":false}' }))
  await page.route('**/admin/api/organizations/', route => route.fulfill({ contentType: 'application/json', body: '{"results":[]}' }))
  await page.goto('/admin/dashboard')
  await expect(page.getByRole('heading', { name: 'No Organizations' })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('organization failure is not an empty success', async ({ page }) => {
  await page.route('**/admin/api/me/', route => route.fulfill({ contentType: 'application/json', body: '{"id":2,"is_staff":false}' }))
  await page.route('**/admin/api/organizations/', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"unavailable"}' }))
  await page.goto('/admin/dashboard')
  await expect(page.getByRole('heading', { name: 'Unable to load Admin' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'No Organizations' })).toHaveCount(0)
})
