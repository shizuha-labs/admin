import { test as base } from '@playwright/test'

/**
 * Test fixtures for Shizuha Admin E2E tests
 * Provides authenticated user context and API access
 *
 * Authentication flow:
 * - Login happens at /id/login (Shizuha ID)
 * - After login, user is redirected to /admin/ (Shizuha Admin)
 * - Tokens are stored in localStorage with shared keys
 */

// Test user credentials (same as other Shizuha services)
export const TEST_USER = {
  username: 'testuser',
  password: 'TestPass123',
  email: 'testuser@example.com'
}

// Extend base test with authentication and data fixtures
export const test = base.extend({
  // Authenticated page fixture - logs in via Shizuha ID
  authenticatedPage: async ({ page }, use) => {
    // Go to Shizuha ID login page with continue parameter
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

    // Wait for redirect to Admin
    await page.waitForURL(/.*admin.*/, { timeout: 30000 })

    // Wait for page to fully load and React to hydrate
    await page.waitForLoadState('networkidle', { timeout: 20000 })
    await page.waitForTimeout(1000)

    // Verify we're on the admin app - check we're not still on login
    const url = page.url()
    if (url.includes('/id/login')) {
      throw new Error('Still on login page after authentication')
    }

    // Use the authenticated page
    await use(page)
  },

  // API context for direct API testing (unauthenticated)
  apiContext: async ({ playwright }, use) => {
    const baseUrl = process.env.BASE_URL || 'http://shizuha-nginx'
    const apiContext = await playwright.request.newContext({
      baseURL: process.env.API_URL || `${baseUrl}/admin/api`,
      extraHTTPHeaders: {
        'Content-Type': 'application/json',
      },
    })

    await use(apiContext)

    await apiContext.dispose()
  },

  // Authenticated API context - uses Shizuha ID for login
  authenticatedApi: async ({ playwright }, use) => {
    const baseUrl = process.env.BASE_URL || 'http://shizuha-nginx'
    const adminApiUrl = process.env.API_URL || `${baseUrl}/admin/api/`
    const idApiUrl = process.env.ID_API_URL || `${baseUrl}/id/api/`

    const apiContext = await playwright.request.newContext({
      baseURL: idApiUrl,
      extraHTTPHeaders: {
        'Content-Type': 'application/json',
      },
    })

    // Login via Shizuha ID to get token
    const loginResponse = await apiContext.post('auth/login/', {
      data: {
        username: TEST_USER.username,
        password: TEST_USER.password
      }
    })

    // Check if login was successful
    if (!loginResponse.ok()) {
      const text = await loginResponse.text()
      throw new Error(`Login failed: ${loginResponse.status()} - ${text.substring(0, 200)}`)
    }

    const { tokens } = await loginResponse.json()

    // Create new context with auth header for Admin API
    const authContext = await playwright.request.newContext({
      baseURL: adminApiUrl,
      extraHTTPHeaders: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${tokens.access}`
      },
    })

    // Store the token for later use
    authContext.token = tokens.access

    await use(authContext)

    await apiContext.dispose()
    await authContext.dispose()
  },

  // Fixture to get organizations
  organizations: async ({ authenticatedApi }, use) => {
    const response = await authenticatedApi.get('organizations/')
    let orgs = []

    if (response.ok()) {
      const data = await response.json()
      orgs = data.results || data || []
    }

    await use(orgs)
  },
})

export { expect } from '@playwright/test'

/**
 * Helper function to create unique test data
 */
export function uniqueId(prefix = 'test') {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`
}

/**
 * Helper to wait for API response with retries
 */
export async function waitForApiResponse(page, urlPattern, options = {}) {
  const { timeout = 10000, expectedStatus = 200 } = options

  return page.waitForResponse(
    response => {
      const matchesUrl = typeof urlPattern === 'string'
        ? response.url().includes(urlPattern)
        : urlPattern.test(response.url())

      return matchesUrl && response.status() === expectedStatus
    },
    { timeout }
  )
}
