import { test, expect, TEST_USER } from './fixtures.js'

/**
 * Authentication tests for Shizuha Admin
 *
 * The login flow works as follows:
 * 1. User visits /admin/ (unauthenticated)
 * 2. API interceptor redirects to /id/login?continue=/admin/
 * 3. User logs in at Shizuha ID (/id/login)
 * 4. After successful login, redirects back to /admin/
 */

test.describe('Authentication', () => {

  test.describe('Unified Login Flow', () => {

    test('should redirect from /admin/ to /id/login when unauthenticated', async ({ page }) => {
      // Clear any existing auth state
      await page.goto('/id/login')
      await page.evaluate(() => {
        localStorage.clear()
      })

      // Try to access Admin directly
      await page.goto('/admin/')

      // Should redirect to Shizuha ID login with continue parameter
      await page.waitForURL(/.*\/id\/login.*continue/, { timeout: 15000 })

      // Verify we're on the login page
      await expect(page.locator('h1')).toContainText('Shizuha ID')
    })

    test('should login with valid credentials and redirect to Admin', async ({ page }) => {
      // Start at Shizuha ID login with continue parameter
      await page.goto('/id/login?continue=/admin/')

      // Wait for form to be ready
      await page.waitForSelector('input[id="username"]', { timeout: 10000 })

      // Fill in credentials
      await page.fill('input[id="username"]', TEST_USER.username)
      await page.fill('input[id="password"]', TEST_USER.password)

      // Click submit
      await page.click('button[type="submit"]')

      // Wait for successful login API response
      await page.waitForResponse(
        response => response.url().includes('/auth/login/') && response.ok(),
        { timeout: 15000 }
      )

      // The redirect happens via window.location.href, wait for it
      await page.waitForURL(/.*admin.*/, { timeout: 30000 })

      // Wait for page to load
      await page.waitForLoadState('domcontentloaded', { timeout: 15000 })

      // Verify we're on the Admin dashboard
      await expect(page.locator('h1, h2').filter({ hasText: /Dashboard|Admin|Organization/i }).first()).toBeVisible({ timeout: 15000 })
    })

    test('should show error with invalid credentials', async ({ page }) => {
      await page.goto('/id/login')

      // Fill in wrong credentials
      await page.fill('input[id="username"]', 'wronguser')
      await page.fill('input[id="password"]', 'wrongpassword')

      // Submit form
      await page.click('button[type="submit"]')

      // Wait for error response from API
      await page.waitForResponse(response =>
        response.url().includes('/auth/login/') && response.status() >= 400,
        { timeout: 10000 }
      )

      // Wait a moment for state update
      await page.waitForTimeout(1000)

      // Should show error message
      await expect(
        page.locator('div').filter({ hasText: /Login failed|No active account|Invalid|credentials/i }).first()
      ).toBeVisible({ timeout: 5000 })

      // Should stay on login page
      await expect(page).toHaveURL(/.*\/id\/login/)
    })

  })

  test.describe('Session Persistence', () => {

    test('should persist authentication across page reload', async ({ authenticatedPage }) => {
      const page = authenticatedPage

      // Verify we're authenticated
      await page.waitForLoadState('networkidle', { timeout: 15000 })

      // Reload the page
      await page.reload()

      // Should still be authenticated (not redirected to login)
      await page.waitForLoadState('networkidle', { timeout: 15000 })
      await expect(page).not.toHaveURL(/.*\/id\/login/)
    })

    test('should maintain session when navigating between pages', async ({ authenticatedPage }) => {
      const page = authenticatedPage

      // Navigate to different pages within Admin
      await page.goto('/admin/departments')
      await page.waitForLoadState('domcontentloaded')
      await expect(page).not.toHaveURL(/.*login/)

      await page.goto('/admin/teams')
      await page.waitForLoadState('domcontentloaded')
      await expect(page).not.toHaveURL(/.*login/)

      await page.goto('/admin/employees')
      await page.waitForLoadState('domcontentloaded')
      await expect(page).not.toHaveURL(/.*login/)

      await page.goto('/admin/settings')
      await page.waitForLoadState('domcontentloaded')
      await expect(page).not.toHaveURL(/.*login/)
    })

  })

  test.describe('API Authentication', () => {

    test('should make authenticated API calls without 401 errors', async ({ authenticatedPage }) => {
      const page = authenticatedPage

      // Listen for API responses
      const apiResponses = []
      page.on('response', response => {
        if (response.url().includes('/admin/api/') || response.url().includes('/id/api/')) {
          apiResponses.push({
            url: response.url(),
            status: response.status()
          })
        }
      })

      // Navigate to trigger some API calls
      await page.goto('/admin/')
      await page.waitForLoadState('networkidle', { timeout: 15000 })

      // Wait for API calls to complete
      await page.waitForTimeout(3000)

      // Check that API calls were made and returned successful status
      const successfulCalls = apiResponses.filter(r => r.status >= 200 && r.status < 400)
      const failedAuth = apiResponses.filter(r => r.status === 401)

      // Log for debugging
      console.log('API responses:', apiResponses)

      // There should be some successful API calls
      expect(successfulCalls.length).toBeGreaterThan(0)

      // There should be no 401 errors after authentication
      expect(failedAuth.length).toBe(0)
    })

    test('should authenticate via API fixture', async ({ authenticatedApi }) => {
      // Test that authenticatedApi fixture works
      const response = await authenticatedApi.get('organizations/')

      expect(response.ok()).toBeTruthy()
      const data = await response.json()
      expect(data).toBeDefined()
    })

  })

})
