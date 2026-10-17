import { NavLink, Outlet } from 'react-router-dom'
import { Crown, Shield, Users, Building2, Blocks, Activity } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useAdmin } from '../../contexts/AdminContext'
import { superuserApi } from '../../services/api'
import clsx from 'clsx'

const navItems = [
  { to: '/superuser', label: 'Overview', icon: Crown, end: true },
  { to: '/superuser/users', label: 'Users', icon: Users, badgeKey: 'pendingUsers' },
  { to: '/superuser/organizations', label: 'Organizations', icon: Building2 },
  { to: '/superuser/services', label: 'Services', icon: Blocks },
  { to: '/superuser/system', label: 'System', icon: Activity },
]

export default function SuperuserLayout() {
  const { isStaff } = useAdmin()

  const { data: pendingData } = useQuery({
    queryKey: ['superuser-pending-users-count'],
    queryFn: () => superuserApi.pendingUsersCount().then(res => res.data),
    refetchInterval: 60000,
    enabled: isStaff,
  })
  const pendingCount = pendingData?.count || 0

  if (!isStaff) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <Shield className="h-12 w-12 text-gray-300 mx-auto mb-4" />
          <h2 className="text-xl font-semibold text-gray-700 dark:text-gray-300">Access Denied</h2>
          <p className="text-gray-500 mt-1">This page is only available to staff users.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-1">
          <Crown className="h-5 w-5 text-yellow-500" />
          <span className="text-sm font-medium text-yellow-600 dark:text-yellow-400">Superuser View</span>
        </div>
        <h1 className="text-2xl font-bold">System Dashboard</h1>
      </div>

      {/* Sub-nav */}
      <nav className="flex border-b border-gray-200 dark:border-gray-700">
        {navItems.map(({ to, label, icon: Icon, end, badgeKey }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              clsx(
                'px-4 py-2 font-medium border-b-2 -mb-px flex items-center gap-2 text-sm',
                isActive
                  ? 'border-primary-500 text-primary-600 dark:text-primary-400'
                  : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
              )
            }
          >
            <Icon className="h-4 w-4" />
            {label}
            {badgeKey === 'pendingUsers' && pendingCount > 0 && (
              <span className="text-xs px-1.5 py-0.5 rounded-full bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 font-medium min-w-[20px] text-center">
                {pendingCount}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Page content */}
      <Outlet />
    </div>
  )
}
