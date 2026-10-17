import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import {
  UserCircle, Search, Plus, X, Loader2, ExternalLink, ChevronLeft, ChevronRight,
  Clock, Check, XCircle,
} from 'lucide-react'
import { superuserApi } from '../../services/api'
import { useAdmin } from '../../contexts/AdminContext'
import clsx from 'clsx'

function CreateUserModal({ onClose }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    username: '',
    email: '',
    password: '',
    first_name: '',
    last_name: '',
    is_staff: false,
    is_superuser: false,
  })
  const [error, setError] = useState(null)

  const createMutation = useMutation({
    mutationFn: (data) => superuserApi.createUser(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['superuser-users'] })
      onClose()
    },
    onError: (err) => {
      setError(err.response?.data?.error || err.response?.data?.detail || 'Failed to create user')
    },
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    setError(null)
    createMutation.mutate(form)
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-md overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold">Create User</h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">Username *</label>
              <input
                type="text"
                required
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Email *</label>
              <input
                type="email"
                required
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Password *</label>
            <input
              type="password"
              required
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">First Name</label>
              <input
                type="text"
                value={form.first_name}
                onChange={(e) => setForm({ ...form, first_name: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Last Name</label>
              <input
                type="text"
                value={form.last_name}
                onChange={(e) => setForm({ ...form, last_name: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
            </div>
          </div>

          <div className="flex items-center gap-6">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.is_staff}
                onChange={(e) => setForm({ ...form, is_staff: e.target.checked })}
                className="rounded border-gray-300 dark:border-gray-600"
              />
              Staff
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.is_superuser}
                onChange={(e) => setForm({ ...form, is_superuser: e.target.checked })}
                className="rounded border-gray-300 dark:border-gray-600"
              />
              Superuser
            </label>
          </div>

          {error && (
            <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-3 rounded-lg text-sm">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg flex items-center gap-2 disabled:opacity-50"
            >
              {createMutation.isPending ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> Creating...</>
              ) : (
                <><Plus className="h-4 w-4" /> Create User</>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function PendingUserRow({ user, onApprove, onDeny, isPending }) {
  return (
    <div className="px-4 py-3 flex items-center justify-between">
      <div className="flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium">{user.username}</span>
          <span className="text-sm text-gray-500">{user.email}</span>
        </div>
        <div className="flex items-center gap-3 mt-1">
          {(user.first_name || user.last_name) && (
            <span className="text-sm text-gray-500">{user.first_name} {user.last_name}</span>
          )}
          <span className="text-xs text-gray-400">
            Registered {new Date(user.date_joined).toLocaleDateString()}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-2 ml-4">
        <button
          onClick={() => onApprove(user.id)}
          disabled={isPending}
          className="px-3 py-1.5 text-sm bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded-lg hover:bg-green-200 dark:hover:bg-green-900/50 disabled:opacity-50 flex items-center gap-1"
        >
          <Check className="h-3.5 w-3.5" /> Approve
        </button>
        <button
          onClick={() => onDeny(user.id)}
          disabled={isPending}
          className="px-3 py-1.5 text-sm bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 rounded-lg hover:bg-red-200 dark:hover:bg-red-900/50 disabled:opacity-50 flex items-center gap-1"
        >
          <XCircle className="h-3.5 w-3.5" /> Deny
        </button>
      </div>
    </div>
  )
}

export default function SuperuserUsers() {
  const { isSuperuser } = useAdmin()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [showCreate, setShowCreate] = useState(false)

  const search = searchParams.get('search') || ''
  const isStaffFilter = searchParams.get('is_staff') || ''
  const isSuperuserFilter = searchParams.get('is_superuser') || ''
  const isActiveFilter = searchParams.get('is_active') || ''
  const page = parseInt(searchParams.get('page') || '1')
  const limit = 25

  const [searchInput, setSearchInput] = useState(search)

  const queryParams = useMemo(() => {
    const params = { limit, offset: (page - 1) * limit }
    if (search) params.search = search
    if (isStaffFilter) params.is_staff = isStaffFilter
    if (isSuperuserFilter) params.is_superuser = isSuperuserFilter
    if (isActiveFilter) params.is_active = isActiveFilter
    return params
  }, [search, isStaffFilter, isSuperuserFilter, isActiveFilter, page])

  const { data, isLoading } = useQuery({
    queryKey: ['superuser-users', queryParams],
    queryFn: () => superuserApi.listUsers(queryParams).then(res => res.data),
  })

  // Pending users query
  const { data: pendingUsers = [] } = useQuery({
    queryKey: ['superuser-pending-users'],
    queryFn: () => superuserApi.pendingUsers().then(res => res.data),
  })

  const approvalMutation = useMutation({
    mutationFn: ({ userId, status, review_note }) =>
      superuserApi.approveUser(userId, { status, review_note }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['superuser-pending-users'] })
      queryClient.invalidateQueries({ queryKey: ['superuser-users'] })
    },
  })

  const users = data?.results || data || []
  const total = data?.count || users.length

  const handleSearch = (e) => {
    e.preventDefault()
    const params = Object.fromEntries(searchParams)
    if (searchInput) params.search = searchInput
    else delete params.search
    params.page = '1'
    setSearchParams(params)
  }

  const setFilter = (key, value) => {
    const params = Object.fromEntries(searchParams)
    if (value) params[key] = value
    else delete params[key]
    params.page = '1'
    setSearchParams(params)
  }

  const totalPages = Math.ceil(total / limit)

  return (
    <div className="space-y-4">
      {showCreate && <CreateUserModal onClose={() => setShowCreate(false)} />}

      {/* Pending Approvals */}
      {pendingUsers.length > 0 && (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-yellow-200 dark:border-yellow-800">
          <div className="px-4 py-3 border-b border-yellow-200 dark:border-yellow-800 flex items-center gap-2">
            <Clock className="h-4 w-4 text-yellow-600 dark:text-yellow-400" />
            <h3 className="font-medium text-sm">Pending Approvals</h3>
            <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 font-medium">
              {pendingUsers.length}
            </span>
          </div>
          <div className="divide-y divide-gray-100 dark:divide-gray-700/50">
            {pendingUsers.map((user) => (
              <PendingUserRow
                key={user.id}
                user={user}
                onApprove={(userId) => approvalMutation.mutate({ userId, status: 'approved' })}
                onDeny={(userId) => approvalMutation.mutate({ userId, status: 'denied' })}
                isPending={approvalMutation.isPending}
              />
            ))}
          </div>
        </div>
      )}

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        <form onSubmit={handleSearch} className="flex-1 min-w-[240px] relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search users by name, email..."
            className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        </form>

        <select
          value={isStaffFilter}
          onChange={(e) => setFilter('is_staff', e.target.value)}
          className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-sm"
        >
          <option value="">All Roles</option>
          <option value="true">Staff</option>
          <option value="false">Non-Staff</option>
        </select>

        <select
          value={isActiveFilter}
          onChange={(e) => setFilter('is_active', e.target.value)}
          className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-sm"
        >
          <option value="">All Status</option>
          <option value="true">Active</option>
          <option value="false">Inactive</option>
        </select>

        {isSuperuser && (
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg flex items-center gap-2 text-sm"
          >
            <Plus className="h-4 w-4" />
            Create User
          </button>
        )}
      </div>

      {/* Users List */}
      {isLoading ? (
        <div className="flex items-center justify-center h-32">
          <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
        </div>
      ) : users.length > 0 ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
          <div className="divide-y divide-gray-100 dark:divide-gray-700/50">
            {users.map((user) => (
              <Link
                key={user.id}
                to={`/superuser/users/${user.id}`}
                className="flex items-center justify-between px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-gray-200 dark:bg-gray-600 flex items-center justify-center">
                    <UserCircle className="h-6 w-6 text-gray-500 dark:text-gray-400" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{user.username}</span>
                      {user.is_staff && (
                        <span className="text-xs px-2 py-0.5 rounded bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">Staff</span>
                      )}
                      {user.is_superuser && (
                        <span className="text-xs px-2 py-0.5 rounded bg-yellow-100 dark:bg-yellow-900/30 text-yellow-600 dark:text-yellow-400">Superuser</span>
                      )}
                      {user.is_active === false && (
                        <span className="text-xs px-2 py-0.5 rounded bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400">Inactive</span>
                      )}
                    </div>
                    <p className="text-sm text-gray-500">{user.email}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="text-right text-sm text-gray-500">
                    <p>ID: {user.id}</p>
                    {user.date_joined && (
                      <p className="text-xs">Joined {new Date(user.date_joined).toLocaleDateString()}</p>
                    )}
                  </div>
                  <ExternalLink className="h-4 w-4 text-gray-400" />
                </div>
              </Link>
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 dark:border-gray-700">
              <p className="text-sm text-gray-500">
                Showing {(page - 1) * limit + 1}–{Math.min(page * limit, total)} of {total}
              </p>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setSearchParams({ ...Object.fromEntries(searchParams), page: String(page - 1) })}
                  disabled={page <= 1}
                  className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="text-sm text-gray-500">Page {page} of {totalPages}</span>
                <button
                  onClick={() => setSearchParams({ ...Object.fromEntries(searchParams), page: String(page + 1) })}
                  disabled={page >= totalPages}
                  className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-12 text-center">
          <UserCircle className="h-12 w-12 text-gray-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium">No users found</h3>
          <p className="text-gray-500 mt-1">
            {search ? 'Try adjusting your search or filters.' : 'Could not fetch users from Shizuha ID.'}
          </p>
        </div>
      )}
    </div>
  )
}
