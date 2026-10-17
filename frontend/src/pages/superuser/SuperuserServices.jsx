import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Blocks, Loader2, Check, XCircle, MessageSquare,
} from 'lucide-react'
import { servicesApi } from '../../services/api'
import clsx from 'clsx'

function AccessRequestRow({ request, onApprove, onDeny, isPending }) {
  return (
    <div className="px-4 py-3 flex items-center justify-between">
      <div className="flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium">{request.user_email || `User #${request.user_id}`}</span>
          <span className="text-xs px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700 font-mono">
            {request.tool_slug || request.tool?.slug}
          </span>
        </div>
        {request.reason && <p className="text-sm text-gray-500 mt-1">{request.reason}</p>}
        <p className="text-xs text-gray-400 mt-1">{new Date(request.created_at).toLocaleDateString()}</p>
      </div>
      {request.status === 'pending' && (
        <div className="flex items-center gap-2 ml-4">
          <button
            onClick={onApprove}
            disabled={isPending}
            className="px-3 py-1.5 text-sm bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded-lg hover:bg-green-200 dark:hover:bg-green-900/50 disabled:opacity-50 flex items-center gap-1"
          >
            <Check className="h-3.5 w-3.5" /> Approve
          </button>
          <button
            onClick={onDeny}
            disabled={isPending}
            className="px-3 py-1.5 text-sm bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 rounded-lg hover:bg-red-200 dark:hover:bg-red-900/50 disabled:opacity-50 flex items-center gap-1"
          >
            <XCircle className="h-3.5 w-3.5" /> Deny
          </button>
        </div>
      )}
      {request.status !== 'pending' && (
        <span className={clsx(
          'text-xs px-2 py-1 rounded capitalize',
          request.status === 'approved' && 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400',
          request.status === 'denied' && 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400'
        )}>
          {request.status}
        </span>
      )}
    </div>
  )
}

export default function SuperuserServices() {
  const queryClient = useQueryClient()
  const [requestFilter, setRequestFilter] = useState('pending')

  const { data: services, isLoading } = useQuery({
    queryKey: ['superuser-services'],
    queryFn: () => servicesApi.list().then(res => res.data),
  })

  const { data: requests, isLoading: requestsLoading } = useQuery({
    queryKey: ['superuser-requests', requestFilter],
    queryFn: () => servicesApi.listRequests({ status: requestFilter }).then(res => res.data),
  })

  const reviewMutation = useMutation({
    mutationFn: ({ requestId, data }) => servicesApi.reviewRequest(requestId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['superuser-requests'] })
      queryClient.invalidateQueries({ queryKey: ['superuser-services'] })
    },
  })

  return (
    <div className="space-y-6">
      {/* Platform Services */}
      <div>
        <h2 className="text-lg font-semibold mb-1">Platform Services</h2>
        <p className="text-sm text-gray-500 mb-4">Configure service defaults and availability across the platform.</p>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
          </div>
        ) : (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-700 text-left text-sm text-gray-500">
                  <th className="px-4 py-3 font-medium">Service</th>
                  <th className="px-4 py-3 font-medium">Slug</th>
                  <th className="px-4 py-3 font-medium text-center">Default On</th>
                  <th className="px-4 py-3 font-medium text-center">Requires Approval</th>
                  <th className="px-4 py-3 font-medium text-center">Active</th>
                  <th className="px-4 py-3 font-medium text-right">Users</th>
                </tr>
              </thead>
              <tbody>
                {(services || []).map((service) => (
                  <tr key={service.slug || service.service_slug} className="border-b border-gray-100 dark:border-gray-700/50 hover:bg-gray-50 dark:hover:bg-gray-700/30">
                    <td className="px-4 py-3 font-medium">{service.name || service.service_slug}</td>
                    <td className="px-4 py-3 text-sm text-gray-500 font-mono">{service.slug || service.service_slug}</td>
                    <td className="px-4 py-3 text-center">
                      <span className={clsx('inline-block w-2 h-2 rounded-full', service.is_default_enabled ? 'bg-green-500' : 'bg-gray-300')} />
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className={clsx('inline-block w-2 h-2 rounded-full', service.requires_approval ? 'bg-yellow-500' : 'bg-gray-300')} />
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className={clsx('inline-block w-2 h-2 rounded-full', service.is_active ? 'bg-green-500' : 'bg-red-500')} />
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-gray-500">{service.user_count ?? service.enabled_org_count ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Access Requests */}
      <div>
        <h2 className="text-lg font-semibold mb-1">Access Requests</h2>
        <p className="text-sm text-gray-500 mb-4">Review and manage user requests for restricted services.</p>

        <div className="flex gap-2 mb-4">
          {['pending', 'approved', 'denied'].map((s) => (
            <button
              key={s}
              onClick={() => setRequestFilter(s)}
              className={clsx(
                'px-3 py-1.5 text-sm rounded-lg capitalize',
                requestFilter === s
                  ? 'bg-primary-500 text-white'
                  : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600'
              )}
            >
              {s}
            </button>
          ))}
        </div>

        {requestsLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
          </div>
        ) : (requests || []).length === 0 ? (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-8 text-center">
            <MessageSquare className="h-10 w-10 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-500">No {requestFilter} requests.</p>
          </div>
        ) : (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 divide-y divide-gray-100 dark:divide-gray-700/50">
            {(requests || []).map((req) => (
              <AccessRequestRow
                key={req.id}
                request={req}
                onApprove={() => reviewMutation.mutate({ requestId: req.id, data: { status: 'approved' } })}
                onDeny={() => reviewMutation.mutate({ requestId: req.id, data: { status: 'denied' } })}
                isPending={reviewMutation.isPending}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
