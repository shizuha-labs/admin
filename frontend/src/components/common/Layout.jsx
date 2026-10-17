import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Building2,
  Users,
  UserCog,
  Network,
  Briefcase,
  GitBranch,
  Settings,
  ShieldCheck,
  ChevronDown,
  Menu,
  X,
  Plus,
  Crown,
  User,
} from 'lucide-react'
import { useState } from 'react'
import { useAdmin } from '../../contexts/AdminContext'
import AppSwitcher from '../AppSwitcher'
import HaneChip from '../HaneChip'
import { useEnabledServices } from '@shizuha/ui'
import clsx from 'clsx'

const navigation = [
  { name: 'Dashboard', href: '/dashboard', icon: LayoutDashboard },
  { name: 'Members', href: '/members', icon: UserCog },
  { name: 'Departments', href: '/departments', icon: Building2 },
  { name: 'Teams', href: '/teams', icon: Users },
  { name: 'Employees', href: '/employees', icon: Briefcase },
  { name: 'Positions', href: '/positions', icon: GitBranch },
  { name: 'Org Chart', href: '/org-chart', icon: Network },
  { name: 'Settings', href: '/settings', icon: Settings },
]

const superuserNavigation = [
  { name: 'System Dashboard', href: '/superuser', icon: Crown },
]

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [orgDropdownOpen, setOrgDropdownOpen] = useState(false)
  const { organizations, currentOrganization, switchOrganization, loading, isStaff, error, retryInitialData } = useAdmin()
  const navigate = useNavigate()
  const enabledServices = useEnabledServices()

  // Ensure organizations is always an array
  const orgList = Array.isArray(organizations) ? organizations : []
  const hasOrganizations = orgList.length > 0

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Mobile sidebar backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={clsx(
          'fixed inset-y-0 left-0 z-50 flex w-64 flex-col bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 transform transition-transform lg:translate-x-0',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        {/* Logo */}
        <div className="h-16 flex items-center justify-between px-4 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-3 min-w-0">
            <AppSwitcher currentAppId="admin" enabledServices={enabledServices} />
            <ShieldCheck className="h-5 w-5 text-primary-600 dark:text-primary-400 shrink-0" />
            <h1 className="text-lg font-semibold text-primary-600 dark:text-primary-400 whitespace-nowrap">Admin</h1>
          </div>
          <button
            className="lg:hidden p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
            onClick={() => setSidebarOpen(false)}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Organization Selector */}
        <div className="p-4 border-b border-gray-200 dark:border-gray-700">
          <div className="relative">
            <button
              onClick={() => setOrgDropdownOpen(!orgDropdownOpen)}
              className="w-full flex items-center justify-between px-3 py-2 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600"
            >
              <span className="truncate">
                {loading ? 'Loading...' : currentOrganization?.name || 'All Organizations'}
              </span>
              <ChevronDown className={clsx('h-4 w-4 transition-transform', orgDropdownOpen && 'rotate-180')} />
            </button>

            {orgDropdownOpen && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-10 max-h-60 overflow-y-auto">
                {/* All Organizations option */}
                <button
                  onClick={() => {
                    switchOrganization(null)
                    setOrgDropdownOpen(false)
                  }}
                  className={clsx(
                    'w-full px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2',
                    currentOrganization === null && 'bg-primary-50 dark:bg-primary-900/20 text-primary-600'
                  )}
                >
                  <Building2 className="h-4 w-4 shrink-0" />
                  <span className="truncate">All Organizations</span>
                </button>
                {/* Individual orgs */}
                {orgList.map((org) => (
                  <button
                    key={org.id}
                    onClick={() => {
                      switchOrganization(org)
                      setOrgDropdownOpen(false)
                    }}
                    className={clsx(
                      'w-full px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2',
                      currentOrganization?.id === org.id && 'bg-primary-50 dark:bg-primary-900/20 text-primary-600'
                    )}
                  >
                    {org.is_personal ? <User className="h-4 w-4 shrink-0" /> : <Building2 className="h-4 w-4 shrink-0" />}
                    <span className="truncate">{org.name}</span>
                  </button>
                ))}
                {/* Create Organization Button */}
                <button
                  onClick={() => {
                    setOrgDropdownOpen(false)
                    navigate('/create-organization')
                  }}
                  className="w-full px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700 border-t border-gray-200 dark:border-gray-700 flex items-center gap-2 text-primary-600"
                >
                  <Plus className="h-4 w-4" />
                  Create Organization
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto p-4 space-y-1">
          {/* Superuser navigation (only for staff) */}
          {isStaff && (
            <>
              {superuserNavigation.map((item) => (
                <NavLink
                  key={item.name}
                  to={item.href}
                  className={({ isActive }) =>
                    clsx(
                      'flex items-center gap-3 px-3 py-2 rounded-lg transition-colors',
                      isActive
                        ? 'bg-yellow-50 dark:bg-yellow-900/20 text-yellow-600 font-medium'
                        : 'text-yellow-600 dark:text-yellow-400 hover:bg-yellow-50 dark:hover:bg-yellow-900/20'
                    )
                  }
                  onClick={() => setSidebarOpen(false)}
                >
                  <item.icon className="h-5 w-5" />
                  {item.name}
                </NavLink>
              ))}
              <div className="border-b border-gray-200 dark:border-gray-700 my-2" />
            </>
          )}

          {/* Regular navigation */}
          {navigation.map((item) => (
            <NavLink
              key={item.name}
              to={item.href}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-3 px-3 py-2 rounded-lg transition-colors',
                  isActive
                    ? 'bg-primary-50 dark:bg-primary-900/20 text-primary-600 font-medium'
                    : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700'
                )
              }
              onClick={() => setSidebarOpen(false)}
            >
              <item.icon className="h-5 w-5" />
              {item.name}
            </NavLink>
          ))}
        </nav>

        {/* Back to Home */}
        <div className="shrink-0 p-4 border-t border-gray-200 dark:border-gray-700 space-y-2">
          <HaneChip />
          <a
            href="/id/account"
            className="flex items-center justify-center gap-2 px-3 py-2 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
          >
            Back to Account
          </a>
        </div>
      </aside>

      {/* Main content */}
      <div className="lg:pl-64">
        {/* Top bar */}
        <header className="h-16 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between px-4">
          <button
            className="lg:hidden p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu className="h-5 w-5" />
          </button>

          <div className="min-w-0 flex-1 lg:flex-initial">
            <h1 className="text-lg font-semibold truncate lg:hidden" title={currentOrganization?.name || 'All Organizations'}>
              {currentOrganization?.name || 'All Organizations'}
            </h1>
          </div>

          <div className="flex items-center gap-4">
            <div className="lg:hidden">
              <HaneChip />
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="p-4 lg:p-6">
          {loading ? (
            <div className="flex items-center justify-center h-64">
              <p className="text-gray-500">Loading organizations...</p>
            </div>
          ) : error ? (
            <div role="alert" className="flex flex-col items-center justify-center min-h-64 gap-4 rounded-xl border border-amber-200 bg-white p-6 text-center shadow-sm dark:border-amber-800 dark:bg-gray-800">
              <ShieldCheck className="h-12 w-12 text-amber-600 dark:text-amber-400" aria-hidden="true" />
              <h2 className="text-xl font-semibold">
                {error.kind === 'denied' ? 'Admin access required' : error.kind === 'signed-out' ? 'Sign in required' : 'Unable to load Admin'}
              </h2>
              <p className="max-w-md text-gray-600 dark:text-gray-300">
                {error.kind === 'denied'
                  ? 'Your account does not have permission to load this Admin information. Ask an administrator to review your access.'
                  : error.kind === 'signed-out'
                    ? 'Sign in again to load your Admin information.'
                    : 'Admin information could not be loaded. Your organizations have not been changed. Please try again.'}
              </p>
              <button type="button" onClick={retryInitialData}
                className="rounded-lg bg-primary-600 px-4 py-2 text-white hover:bg-primary-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600">
                Try again
              </button>
            </div>
          ) : hasOrganizations ? (
            <Outlet />
          ) : (
            <div className="flex flex-col items-center justify-center h-64 gap-4">
              <Building2 className="h-16 w-16 text-gray-300" />
              <h2 className="text-xl font-semibold text-gray-700 dark:text-gray-300">No Organizations</h2>
              <p className="text-gray-500 text-center max-w-md">
                You don't have any organizations yet. Create your first organization to start managing your team.
              </p>
              <button
                onClick={() => navigate('/create-organization')}
                className="mt-4 inline-flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
              >
                <Plus className="h-5 w-5" />
                Create Organization
              </button>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
