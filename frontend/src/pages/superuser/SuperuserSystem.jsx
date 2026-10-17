import { useQuery } from '@tanstack/react-query'
import { Activity, Loader2, RefreshCw, Server, Database, HardDrive } from 'lucide-react'
import { superuserApi } from '../../services/api'
import clsx from 'clsx'

const statusColors = {
  healthy: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 border-green-200 dark:border-green-800',
  unhealthy: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 border-red-200 dark:border-red-800',
  timeout: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400 border-yellow-200 dark:border-yellow-800',
  unreachable: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-400 border-gray-200 dark:border-gray-600',
  not_deployed: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400 border-gray-200 dark:border-gray-700',
}

const statusDot = {
  healthy: 'bg-green-500',
  unhealthy: 'bg-red-500',
  timeout: 'bg-yellow-500',
  unreachable: 'bg-gray-400',
  not_deployed: 'bg-gray-400',
}

export default function SuperuserSystem() {
  const { data, isLoading, refetch, isFetching, dataUpdatedAt } = useQuery({
    queryKey: ['superuser-system-health'],
    queryFn: () => superuserApi.systemHealth().then(res => res.data),
    refetchInterval: 30000,
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">System Health</h2>
          <p className="text-sm text-gray-500">
            Monitoring all services and infrastructure.
            {dataUpdatedAt && (
              <span className="ml-2">Last checked: {new Date(dataUpdatedAt).toLocaleTimeString()}</span>
            )}
          </p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="px-3 py-1.5 text-sm bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-lg flex items-center gap-2 disabled:opacity-50"
        >
          <RefreshCw className={clsx('h-4 w-4', isFetching && 'animate-spin')} />
          Refresh
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-32">
          <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
          <span className="ml-2 text-gray-500">Checking services...</span>
        </div>
      ) : data ? (
        <>
          {/* Summary */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4 text-center">
              <p className="text-3xl font-bold text-green-600">{data.summary?.healthy || 0}</p>
              <p className="text-sm text-gray-500">Healthy</p>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4 text-center">
              <p className="text-3xl font-bold text-red-600">{data.summary?.unhealthy || 0}</p>
              <p className="text-sm text-gray-500">Unhealthy</p>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4 text-center">
              <p className="text-3xl font-bold text-gray-500">{data.summary?.not_deployed || 0}</p>
              <p className="text-sm text-gray-500">Not deployed</p>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4 text-center">
              <p className="text-3xl font-bold">{data.summary?.total || 0}</p>
              <p className="text-sm text-gray-500">Total Services</p>
            </div>
          </div>

          {/* Services Grid */}
          <div>
            <h3 className="font-semibold mb-3 flex items-center gap-2">
              <Server className="h-4 w-4" />
              Application Services
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {(data.services || []).map((service) => (
                <div
                  key={service.name}
                  className={clsx(
                    'rounded-lg border p-4',
                    statusColors[service.status]
                  )}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className={clsx('w-2.5 h-2.5 rounded-full', statusDot[service.status])} />
                      <span className="font-medium text-sm">{service.name}</span>
                    </div>
                    <span className="text-xs capitalize font-medium">{String(service.status || '').replace(/_/g, ' ')}</span>
                  </div>
                  <div className="flex items-center justify-between text-xs opacity-75">
                    <span>{service.response_ms}ms</span>
                    {service.status_code && <span>HTTP {service.status_code}</span>}
                  </div>
                  {service.error && (
                    <p className="text-xs mt-1 opacity-75 truncate" title={service.error}>{service.error}</p>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Infrastructure */}
          {data.infrastructure?.length > 0 && (
            <div>
              <h3 className="font-semibold mb-3 flex items-center gap-2">
                <Database className="h-4 w-4" />
                Infrastructure
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {data.infrastructure.map((infra) => {
                  const Icon = infra.name === 'PostgreSQL' ? Database : infra.name === 'MinIO' ? HardDrive : Server
                  return (
                    <div
                      key={infra.name}
                      className={clsx(
                        'rounded-lg border p-4',
                        statusColors[infra.status]
                      )}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Icon className="h-5 w-5" />
                          <span className="font-medium">{infra.name}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className={clsx('w-2.5 h-2.5 rounded-full', statusDot[infra.status])} />
                          <span className="text-sm capitalize">{infra.status}</span>
                        </div>
                      </div>
                      {infra.response_ms && (
                        <p className="text-xs mt-1 opacity-75">{infra.response_ms}ms</p>
                      )}
                      {infra.error && (
                        <p className="text-xs mt-1 opacity-75 truncate" title={infra.error}>{infra.error}</p>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Django Admin Links */}
          <div>
            <h3 className="font-semibold mb-3">Quick Links</h3>
            <div className="flex flex-wrap gap-2">
              {(data.services || [])
                .filter(s => s.status === 'healthy')
                .map((service) => {
                  const adminUrl = service.url.replace('/api/', '/admin/')
                  return (
                    <a
                      key={service.name}
                      href={adminUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="px-3 py-1.5 text-sm bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-lg"
                    >
                      {service.name.replace('shizuha-', '')} admin
                    </a>
                  )
                })}
            </div>
          </div>
        </>
      ) : null}
    </div>
  )
}
