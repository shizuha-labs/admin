import { createContext, useContext, useState, useEffect } from 'react'
import { organizationsApi, userApi } from '../services/api'
import { loadAdminData, loadingFailure, organizationRows, requestFailure } from './adminLoadState.mjs'

const AdminContext = createContext(null)

export function AdminProvider({ children }) {
  const [organizations, setOrganizations] = useState([])
  const [currentOrganization, setCurrentOrganization] = useState(null)
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [errors, setErrors] = useState({ user: null, organizations: null })
  const error = loadingFailure(errors)

  // Load user info and organizations on mount
  useEffect(() => {
    loadInitialData()
  }, [])

  // Restore current org from localStorage. First visit defaults to the user's
  // FIRST org — the previous "All Organizations" (null) default rendered the
  // dashboard as a dead zeros page ("overview for —, 0 employees") since
  // org-scoped stats never fire without a tenant (operator 2026-07-10).
  // An explicitly saved "__all__" choice is still honored.
  useEffect(() => {
    if (organizations.length === 0) return
    const savedOrgSlug = localStorage.getItem('shizuha_admin_current_org')
    if (!savedOrgSlug) {
      setCurrentOrganization(organizations[0])
      localStorage.setItem('shizuha_admin_current_org', organizations[0].slug)
    } else if (savedOrgSlug === '__all__') {
      // "All Organizations" mode (explicit user choice)
      setCurrentOrganization(null)
    } else {
      const org = organizations.find((o) => o.slug === savedOrgSlug)
      if (org) {
        setCurrentOrganization(org)
      } else {
        // Saved org not found, fall back to All Organizations
        setCurrentOrganization(null)
        localStorage.setItem('shizuha_admin_current_org', '__all__')
      }
    }
  }, [organizations])

  const loadInitialData = async () => {
    try {
      setLoading(true)

      const result = await loadAdminData(userApi, organizationsApi)
      setUser(result.user)
      if (result.organizations !== undefined) setOrganizations(result.organizations)
      setErrors(result.errors)
    } finally {
      setLoading(false)
    }
  }

  const loadOrganizations = async () => {
    try {
      const response = await organizationsApi.list()
      setOrganizations(organizationRows(response))
      setErrors(previous => ({ ...previous, organizations: null }))
    } catch (err) {
      setErrors(previous => ({ ...previous, organizations: requestFailure(err, 'organizations') }))
    }
  }

  const switchOrganization = (org) => {
    setCurrentOrganization(org)
    localStorage.setItem('shizuha_admin_current_org', org ? org.slug : '__all__')
  }

  const refreshOrganizations = () => {
    loadOrganizations()
  }

  const value = {
    organizations,
    currentOrganization,
    user,
    isStaff: user?.is_staff || false,
    isSuperuser: user?.is_superuser || false,
    loading,
    error,
    retryInitialData: loadInitialData,
    switchOrganization,
    refreshOrganizations,
  }

  return (
    <AdminContext.Provider value={value}>
      {children}
    </AdminContext.Provider>
  )
}

export function useAdmin() {
  const context = useContext(AdminContext)
  if (!context) {
    throw new Error('useAdmin must be used within an AdminProvider')
  }
  return context
}

export default AdminContext
