import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { UserCircle, Building2, FolderKanban, Users, ArrowRight } from 'lucide-react'
import { superuserApi } from '../../services/api'

function StatSkeleton() {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5 animate-pulse">
      <div className="flex items-center gap-4">
        <div className="h-12 w-12 rounded-lg bg-gray-200 dark:bg-gray-700" />
        <div className="flex-1 space-y-2">
          <div className="h-8 w-16 rounded bg-gray-200 dark:bg-gray-700" />
          <div className="h-3 w-24 rounded bg-gray-200 dark:bg-gray-700" />
        </div>
      </div>
    </div>
  )
}

export default function SuperuserOverview() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['superuser-dashboard'],
    queryFn: () => superuserApi.dashboard().then(res => res.data),
    staleTime: 30_000,
  })

  const stats = [
    {
      label: 'Total Users',
      value: data?.stats?.total_users || data?.users?.length || 0,
      icon: UserCircle,
      color: 'bg-green-100 dark:bg-green-900/30 text-green-600',
      link: '/superuser/users',
    },
    {
      label: 'Organizations',
      value: data?.stats?.total_organizations || 0,
      icon: Building2,
      color: 'bg-primary-100 dark:bg-primary-900/30 text-primary-600',
      link: '/superuser/organizations',
    },
    {
      label: 'Departments',
      value: data?.stats?.total_departments || 0,
      icon: FolderKanban,
      color: 'bg-blue-100 dark:bg-blue-900/30 text-blue-600',
      link: null,
    },
    {
      label: 'Org Memberships',
      value: data?.stats?.total_members || 0,
      icon: Users,
      color: 'bg-purple-100 dark:bg-purple-900/30 text-purple-600',
      link: null,
    },
  ]

  return (
    <div className="space-y-6">
      <p className="text-gray-500">
        View users, organizations, and memberships across the Shizuha ecosystem.
      </p>

      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-4 rounded-lg">
          Failed to load system data. Please try again.
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {isLoading && !data
          ? [1, 2, 3, 4].map((key) => <StatSkeleton key={key} />)
          : stats.map(({ label, value, icon: Icon, color, link }) => (
          <div
            key={label}
            className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5"
          >
            <div className="flex items-center gap-4">
              <div className={`p-3 rounded-lg ${color}`}>
                <Icon className="h-6 w-6" />
              </div>
              <div className="flex-1">
                <p className="text-3xl font-bold">{value}</p>
                <p className="text-sm text-gray-500">{label}</p>
              </div>
            </div>
            {link && (
              <Link
                to={link}
                className="mt-3 flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700 dark:text-primary-400"
              >
                View all <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            )}
          </div>
        ))}
      </div>

      {/* Quick Links */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Link
          to="/superuser/system"
          className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
        >
          <h3 className="font-semibold mb-1">System Health</h3>
          <p className="text-sm text-gray-500">Check the status of all services and infrastructure.</p>
        </Link>
        <Link
          to="/superuser/services"
          className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
        >
          <h3 className="font-semibold mb-1">Service Management</h3>
          <p className="text-sm text-gray-500">Manage platform services and review access requests.</p>
        </Link>
      </div>

      {/* Recent Users */}
      {data?.users?.length > 0 && (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
            <h3 className="font-semibold">Recent Users</h3>
            <Link to="/superuser/users" className="text-sm text-primary-600 hover:text-primary-700 dark:text-primary-400">
              View all
            </Link>
          </div>
          <div className="divide-y divide-gray-100 dark:divide-gray-700/50">
            {data.users.slice(0, 5).map(user => (
              <Link
                key={user.id}
                to={`/superuser/users/${user.id}`}
                className="flex items-center justify-between px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/50"
              >
                <div className="flex items-center gap-3">
                  <UserCircle className="h-8 w-8 text-gray-400" />
                  <div>
                    <span className="font-medium">{user.username}</span>
                    <p className="text-sm text-gray-500">{user.email}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {user.is_staff && (
                    <span className="text-xs px-2 py-0.5 rounded bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">Staff</span>
                  )}
                  {user.is_superuser && (
                    <span className="text-xs px-2 py-0.5 rounded bg-yellow-100 dark:bg-yellow-900/30 text-yellow-600 dark:text-yellow-400">Superuser</span>
                  )}
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
