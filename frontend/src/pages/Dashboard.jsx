import { useQuery } from '@tanstack/react-query'
import { Building2, Users, Briefcase, Network, TrendingUp, UserCheck, RefreshCw } from 'lucide-react'
import { useAdmin } from '../contexts/AdminContext'
import { orgChartApi } from '../services/api'
import clsx from 'clsx'

function StatCard({ title, value, icon: Icon, color, loading }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-gray-500 dark:text-gray-400">{title}</p>
          <p className="text-3xl font-bold mt-1">
            {loading ? '...' : value}
          </p>
        </div>
        <div className={clsx('p-3 rounded-xl', color)}>
          <Icon className="h-6 w-6 text-white" />
        </div>
      </div>
    </div>
  )
}

function DepartmentSizeChart({ data }) {
  if (!data?.length) return null

  const maxCount = Math.max(...data.map(d => d.employee_count))

  return (
    <div className="space-y-3">
      {data.slice(0, 5).map((dept, index) => (
        <div key={index} className="space-y-1">
          <div className="flex justify-between text-sm">
            <span className="font-medium truncate">{dept.name}</span>
            <span className="text-gray-500">{dept.employee_count}</span>
          </div>
          <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-primary-500 rounded-full transition-all"
              style={{ width: `${(dept.employee_count / maxCount) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

function StatusBreakdown({ title, data, colors }) {
  if (!data) return null

  const entries = Object.entries(data)
  const total = entries.reduce((sum, [, count]) => sum + count, 0)

  return (
    <div className="space-y-4">
      <h4 className="font-medium text-gray-700 dark:text-gray-300">{title}</h4>
      <div className="space-y-2">
        {entries.map(([status, count]) => (
          <div key={status} className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className={clsx('w-3 h-3 rounded-full', colors[status] || 'bg-gray-400')} />
              <span className="text-sm capitalize">
                {status.replace('_', ' ')}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">{count}</span>
              <span className="text-xs text-gray-500">
                ({total > 0 ? Math.round((count / total) * 100) : 0}%)
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { currentOrganization, user, loading: organizationLoading } = useAdmin()

  const query = useQuery({
    queryKey: ['org-stats', user?.id, currentOrganization?.slug],
    queryFn: () => orgChartApi.stats(currentOrganization.slug).then(res => res.data),
    enabled: !!user?.id && !!currentOrganization?.slug,
    staleTime: 30000,
    refetchInterval: 30000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  })

  const permissionDenied = [401, 403].includes(query.error?.response?.status)
  const stats = permissionDenied ? undefined : query.data
  const isLoading = organizationLoading || query.isLoading
  const unavailable = !stats && !isLoading

  const statusColors = {
    active: 'bg-green-500',
    on_leave: 'bg-yellow-500',
    probation: 'bg-blue-500',
    suspended: 'bg-red-500',
    terminated: 'bg-gray-500',
    resigned: 'bg-gray-400',
  }

  const typeColors = {
    full_time: 'bg-primary-500',
    part_time: 'bg-purple-500',
    contractor: 'bg-orange-500',
    intern: 'bg-teal-500',
    consultant: 'bg-pink-500',
    temporary: 'bg-gray-500',
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="text-gray-500 dark:text-gray-400">
          Organization overview for {currentOrganization?.name}
        </p>
      </div>

      {!currentOrganization && !organizationLoading && (
        <p role="status" className="text-sm text-gray-500">Select an organization to view its metrics.</p>
      )}
      {currentOrganization && (
        <div className="flex items-center justify-between gap-3 text-sm">
          <p role="status" className={query.isError ? 'text-amber-600 dark:text-amber-400' : 'text-gray-500'}>
            {query.isError
              ? (stats ? 'Updates unavailable; showing the last successful observation.' : 'Organization metrics unavailable.')
              : query.dataUpdatedAt ? `Updated ${new Date(query.dataUpdatedAt).toLocaleTimeString()}` : 'Loading organization metrics…'}
          </p>
          <button type="button" onClick={() => query.refetch({ cancelRefetch: false })} disabled={query.isFetching}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 dark:border-gray-600 px-3 py-1.5 disabled:opacity-50">
            <RefreshCw className={`h-4 w-4 ${query.isFetching ? 'animate-spin' : ''}`} />
            {query.isError ? 'Retry' : 'Refresh'}
          </button>
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Total Employees"
          value={stats?.total_employees ?? '—'}
          icon={Users}
          color="bg-primary-500"
          loading={isLoading}
        />
        <StatCard
          title="Departments"
          value={stats?.total_departments ?? '—'}
          icon={Building2}
          color="bg-green-500"
          loading={isLoading}
        />
        <StatCard
          title="Teams"
          value={stats?.total_teams ?? '—'}
          icon={Network}
          color="bg-purple-500"
          loading={isLoading}
        />
        <StatCard
          title="Active"
          value={stats?.status_breakdown ? (stats.status_breakdown.active ?? 0) : '—'}
          icon={UserCheck}
          color="bg-teal-500"
          loading={isLoading}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Department Sizes */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="text-lg font-semibold mb-4">Largest Departments</h3>
          {isLoading ? (
            <p className="text-gray-500">Loading...</p>
          ) : unavailable ? (
            <p className="text-gray-500">Department metrics unavailable</p>
          ) : stats?.largest_departments?.length > 0 ? (
            <DepartmentSizeChart data={stats.largest_departments} />
          ) : (
            <p className="text-gray-500">No department data yet</p>
          )}
        </div>

        {/* Employment Status */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="text-lg font-semibold mb-4">Employment Status</h3>
          {isLoading ? (
            <p className="text-gray-500">Loading...</p>
          ) : unavailable ? (
            <p className="text-gray-500">Employee metrics unavailable</p>
          ) : stats?.status_breakdown ? (
            <StatusBreakdown
              title=""
              data={stats.status_breakdown}
              colors={statusColors}
            />
          ) : (
            <p className="text-gray-500">No employee data yet</p>
          )}
        </div>

        {/* Employment Type */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="text-lg font-semibold mb-4">Employment Type</h3>
          {isLoading ? (
            <p className="text-gray-500">Loading...</p>
          ) : unavailable ? (
            <p className="text-gray-500">Employee metrics unavailable</p>
          ) : stats?.type_breakdown ? (
            <StatusBreakdown
              title=""
              data={stats.type_breakdown}
              colors={typeColors}
            />
          ) : (
            <p className="text-gray-500">No employee data yet</p>
          )}
        </div>
      </div>

      {/* Quick Actions */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
        <h3 className="text-lg font-semibold mb-4">Quick Actions</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <a
            href="/admin/departments"
            className="flex flex-col items-center gap-2 p-4 rounded-lg bg-gray-50 dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600 transition-colors"
          >
            <Building2 className="h-8 w-8 text-primary-500" />
            <span className="text-sm font-medium">Add Department</span>
          </a>
          <a
            href="/admin/teams"
            className="flex flex-col items-center gap-2 p-4 rounded-lg bg-gray-50 dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600 transition-colors"
          >
            <Network className="h-8 w-8 text-purple-500" />
            <span className="text-sm font-medium">Create Team</span>
          </a>
          <a
            href="/admin/employees"
            className="flex flex-col items-center gap-2 p-4 rounded-lg bg-gray-50 dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600 transition-colors"
          >
            <Users className="h-8 w-8 text-green-500" />
            <span className="text-sm font-medium">Manage Employees</span>
          </a>
          <a
            href="/admin/org-chart"
            className="flex flex-col items-center gap-2 p-4 rounded-lg bg-gray-50 dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600 transition-colors"
          >
            <TrendingUp className="h-8 w-8 text-teal-500" />
            <span className="text-sm font-medium">View Org Chart</span>
          </a>
        </div>
      </div>
    </div>
  )
}
