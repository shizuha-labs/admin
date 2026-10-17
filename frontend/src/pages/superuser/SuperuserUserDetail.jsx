import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  UserCircle, Mail, Building2, FolderKanban, CheckSquare, Blocks, Clock, AlertCircle,
  Circle, ArrowLeft, Trash2, AlertTriangle, Loader2, X, Save, Key, Shield, Crown,
} from 'lucide-react'
import { superuserApi, servicesApi } from '../../services/api'
import { useAdmin } from '../../contexts/AdminContext'
import clsx from 'clsx'

const roleColors = {
  owner: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
  admin: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  member: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
}

function ServiceToggle({ enabled, onToggle, disabled }) {
  return (
    <button
      onClick={onToggle}
      disabled={disabled}
      className={clsx(
        'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
        enabled ? 'bg-primary-500' : 'bg-gray-300 dark:bg-gray-600',
        disabled && 'opacity-50 cursor-not-allowed'
      )}
    >
      <span
        className={clsx(
          'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
          enabled ? 'translate-x-6' : 'translate-x-1'
        )}
      />
    </button>
  )
}

function UserServicesSection({ userId }) {
  const queryClient = useQueryClient()

  // Fetch full platform service catalog
  const { data: allServicesData, isLoading: catalogLoading } = useQuery({
    queryKey: ['superuser-services'],
    queryFn: () => servicesApi.list().then(res => res.data),
  })

  // Fetch this user's enabled services
  const { data: userServicesData, isLoading: userLoading } = useQuery({
    queryKey: ['superuser-user-services', userId],
    queryFn: () => servicesApi.getUserServices(userId).then(res => res.data),
    enabled: !!userId,
  })

  const grantMutation = useMutation({
    mutationFn: ({ slugs, action }) => servicesApi.updateUserServices(userId, { service_slugs: slugs, action }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['superuser-user-services', userId] })
    },
  })

  if (catalogLoading || userLoading) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
      </div>
    )
  }

  // Build enabled slugs set from user services response
  // API returns: {user_id, username, email, enabled_services: ["slug1", "slug2", ...]}
  const enabledSlugs = new Set(
    Array.isArray(userServicesData?.enabled_services) ? userServicesData.enabled_services
    : Array.isArray(userServicesData) ? userServicesData.map(s => typeof s === 'string' ? s : s.slug || s.service_slug)
    : []
  )

  // Build catalog from /superuser/services/
  // API returns: [{service_slug: "pulse", enabled_org_count: 2}, ...]
  const rawCatalog = Array.isArray(allServicesData) ? allServicesData
    : Array.isArray(allServicesData?.services) ? allServicesData.services
    : []

  // Helper: slug → display name (e.g. "shizuha-pulse" → "Pulse", "pulse" → "Pulse")
  const slugToName = (slug) => {
    const clean = slug.replace(/^shizuha[-_]/, '')
    return clean.charAt(0).toUpperCase() + clean.slice(1)
  }

  // Merge catalog with enabled state; also include any enabled slugs not in catalog
  const catalogSlugs = new Set()
  const services = rawCatalog.map(svc => {
    const slug = typeof svc === 'string' ? svc : (svc.service_slug || svc.slug || '')
    catalogSlugs.add(slug)
    return {
      slug,
      name: svc.name || slugToName(slug),
      is_enabled: enabledSlugs.has(slug),
    }
  })
  // Add any user-enabled services not present in the catalog
  for (const slug of enabledSlugs) {
    if (!catalogSlugs.has(slug)) {
      services.push({ slug, name: slugToName(slug), is_enabled: true })
    }
  }

  return (
    <div>
      <h3 className="font-semibold mb-3 flex items-center gap-2">
        <Blocks className="h-4 w-4" />
        Enabled Services
      </h3>
      {services.length === 0 ? (
        <p className="text-sm text-gray-500">No services available</p>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          {services.map((svc) => (
            <label
              key={svc.slug}
              className="flex items-center justify-between p-2 bg-gray-50 dark:bg-gray-700/50 rounded-lg text-sm"
            >
              <span>{svc.name}</span>
              <ServiceToggle
                enabled={svc.is_enabled}
                disabled={grantMutation.isPending}
                onToggle={() => grantMutation.mutate({
                  slugs: [svc.slug],
                  action: svc.is_enabled ? 'revoke' : 'grant'
                })}
              />
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

function DeleteUserDialog({ userId, username, onClose, onDeleted }) {
  const [confirmText, setConfirmText] = useState('')
  const queryClient = useQueryClient()

  const { data: preview, isLoading: previewLoading } = useQuery({
    queryKey: ['user-delete-preview', userId],
    queryFn: () => superuserApi.userDeletePreview(userId).then(res => res.data),
    enabled: !!userId,
  })

  const deleteMutation = useMutation({
    mutationFn: () => superuserApi.userDelete(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['superuser-users'] })
      onDeleted?.()
      onClose()
    },
  })

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[60]" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700 bg-red-50 dark:bg-red-900/20">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400" />
            <h2 className="text-lg font-semibold text-red-700 dark:text-red-400">Delete User</h2>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-red-100 dark:hover:bg-red-900/30 rounded-lg">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          {previewLoading && (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
            </div>
          )}

          {preview && (
            <>
              <div className="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-3 space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-600 dark:text-gray-400">Tasks to unassign:</span>
                  <span className="font-medium">{preview.impact.assigned_tasks_count}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600 dark:text-gray-400">Org memberships:</span>
                  <span className="font-medium">{preview.impact.organization_memberships_count}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600 dark:text-gray-400">Team memberships:</span>
                  <span className="font-medium">{preview.impact.team_memberships_count}</span>
                </div>
              </div>

              {preview.warnings?.length > 0 && (
                <div className="bg-yellow-50 dark:bg-yellow-900/20 rounded-lg p-3 space-y-1">
                  {preview.warnings.map((w, i) => (
                    <div key={i} className="flex items-start gap-2 text-sm text-yellow-700 dark:text-yellow-400">
                      <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                      <span>{w}</span>
                    </div>
                  ))}
                </div>
              )}

              <div>
                <label className="text-sm text-gray-700 dark:text-gray-300">
                  Type <span className="font-mono font-semibold bg-gray-100 dark:bg-gray-700 px-1 rounded">{username}</span> to confirm:
                </label>
                <input
                  type="text"
                  value={confirmText}
                  onChange={(e) => setConfirmText(e.target.value)}
                  className="mt-1 w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-red-500"
                />
              </div>

              {deleteMutation.isError && (
                <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-3 rounded-lg text-sm">
                  {deleteMutation.error?.response?.data?.error || 'Failed to delete user.'}
                </div>
              )}
            </>
          )}
        </div>

        <div className="flex justify-end gap-3 p-4 border-t border-gray-200 dark:border-gray-700">
          <button onClick={onClose} className="px-4 py-2 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg">
            Cancel
          </button>
          <button
            onClick={() => deleteMutation.mutate()}
            disabled={confirmText !== username || deleteMutation.isPending || previewLoading}
            className={clsx(
              'px-4 py-2 rounded-lg flex items-center gap-2',
              confirmText === username && !deleteMutation.isPending
                ? 'bg-red-600 hover:bg-red-700 text-white'
                : 'bg-gray-300 dark:bg-gray-600 text-gray-500 cursor-not-allowed'
            )}
          >
            {deleteMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
            Delete User
          </button>
        </div>
      </div>
    </div>
  )
}

export default function SuperuserUserDetail() {
  const { userId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user: currentUser, isSuperuser } = useAdmin()

  const [showDelete, setShowDelete] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editForm, setEditForm] = useState({})
  const [showPasswordReset, setShowPasswordReset] = useState(false)
  const [newPassword, setNewPassword] = useState('')

  const { data, isLoading, error } = useQuery({
    queryKey: ['superuser-user-detail', userId],
    queryFn: () => superuserApi.userDetail(userId).then(res => res.data),
    enabled: !!userId,
  })

  const updateMutation = useMutation({
    mutationFn: (updates) => superuserApi.updateUser(userId, updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['superuser-user-detail', userId] })
      queryClient.invalidateQueries({ queryKey: ['superuser-users'] })
      setEditing(false)
      setShowPasswordReset(false)
      setNewPassword('')
    },
  })

  const user = data?.user
  const organizations = data?.organizations || []
  const assignedTasks = data?.assigned_tasks || []
  const canDelete = isSuperuser && parseInt(userId) !== currentUser?.id

  const startEditing = () => {
    setEditForm({
      first_name: user.first_name || '',
      last_name: user.last_name || '',
      email: user.email || '',
      is_staff: user.is_staff || false,
      is_superuser: user.is_superuser || false,
      is_active: user.is_active !== false,
    })
    setEditing(true)
  }

  const taskStatusColors = {
    pending: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
    in_progress: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    completed: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-32">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    )
  }

  if (error || !user) {
    return (
      <div className="space-y-4">
        <button onClick={() => navigate('/superuser/users')} className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700">
          <ArrowLeft className="h-4 w-4" /> Back to Users
        </button>
        <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-4 rounded-lg">
          User not found or failed to load.
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {showDelete && (
        <DeleteUserDialog
          userId={userId}
          username={user.username}
          onClose={() => setShowDelete(false)}
          onDeleted={() => navigate('/superuser/users')}
        />
      )}

      {/* Back button */}
      <button onClick={() => navigate('/superuser/users')} className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300">
        <ArrowLeft className="h-4 w-4" /> Back to Users
      </button>

      {/* User Header */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
        <div className="flex items-start justify-between">
          <div className="flex items-start gap-4">
            <div className="w-16 h-16 rounded-full bg-gray-200 dark:bg-gray-600 flex items-center justify-center">
              <UserCircle className="h-10 w-10 text-gray-500 dark:text-gray-400" />
            </div>
            <div>
              {editing ? (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <input
                      type="text"
                      value={editForm.first_name}
                      onChange={(e) => setEditForm({ ...editForm, first_name: e.target.value })}
                      placeholder="First name"
                      className="px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-sm"
                    />
                    <input
                      type="text"
                      value={editForm.last_name}
                      onChange={(e) => setEditForm({ ...editForm, last_name: e.target.value })}
                      placeholder="Last name"
                      className="px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-sm"
                    />
                  </div>
                  <input
                    type="email"
                    value={editForm.email}
                    onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
                    className="w-full px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-sm"
                  />
                  <div className="flex items-center gap-4">
                    <label className="flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={editForm.is_staff} onChange={(e) => setEditForm({ ...editForm, is_staff: e.target.checked })} />
                      Staff
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={editForm.is_superuser} onChange={(e) => setEditForm({ ...editForm, is_superuser: e.target.checked })} />
                      Superuser
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={editForm.is_active} onChange={(e) => setEditForm({ ...editForm, is_active: e.target.checked })} />
                      Active
                    </label>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => updateMutation.mutate(editForm)}
                      disabled={updateMutation.isPending}
                      className="px-3 py-1.5 bg-primary-600 hover:bg-primary-700 text-white rounded-lg text-sm flex items-center gap-1"
                    >
                      {updateMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                      Save
                    </button>
                    <button onClick={() => setEditing(false)} className="px-3 py-1.5 text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg text-sm">
                      Cancel
                    </button>
                  </div>
                  {updateMutation.isError && (
                    <p className="text-sm text-red-600">{updateMutation.error?.response?.data?.error || 'Update failed'}</p>
                  )}
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-2 flex-wrap">
                    <h2 className="text-xl font-semibold">{user.username}</h2>
                    {user.is_staff && (
                      <span className="text-xs px-2 py-0.5 rounded bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 flex items-center gap-1">
                        <Shield className="h-3 w-3" /> Staff
                      </span>
                    )}
                    {user.is_superuser && (
                      <span className="text-xs px-2 py-0.5 rounded bg-yellow-100 dark:bg-yellow-900/30 text-yellow-600 dark:text-yellow-400 flex items-center gap-1">
                        <Crown className="h-3 w-3" /> Superuser
                      </span>
                    )}
                    {user.is_active === false && (
                      <span className="text-xs px-2 py-0.5 rounded bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400">Inactive</span>
                    )}
                  </div>
                  <p className="text-gray-500 flex items-center gap-1 mt-1">
                    <Mail className="h-4 w-4" /> {user.email}
                  </p>
                  {(user.first_name || user.last_name) && (
                    <p className="text-gray-600 dark:text-gray-400 mt-1">{user.first_name} {user.last_name}</p>
                  )}
                  <div className="text-sm text-gray-500 mt-2">
                    <p>ID: {user.id}</p>
                    {user.date_joined && <p>Joined: {new Date(user.date_joined).toLocaleDateString()}</p>}
                    {user.last_login && <p>Last login: {new Date(user.last_login).toLocaleDateString()}</p>}
                  </div>
                </>
              )}
            </div>
          </div>

          {isSuperuser && !editing && (
            <div className="flex items-center gap-2">
              <button
                onClick={startEditing}
                className="px-3 py-1.5 text-sm bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-lg"
              >
                Edit
              </button>
              <button
                onClick={() => setShowPasswordReset(!showPasswordReset)}
                className="px-3 py-1.5 text-sm bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-lg flex items-center gap-1"
              >
                <Key className="h-3.5 w-3.5" /> Reset Password
              </button>
              {canDelete && (
                <button
                  onClick={() => setShowDelete(true)}
                  className="px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg flex items-center gap-1"
                >
                  <Trash2 className="h-3.5 w-3.5" /> Delete
                </button>
              )}
            </div>
          )}
        </div>

        {/* Password Reset */}
        {showPasswordReset && (
          <div className="mt-4 p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
            <h3 className="text-sm font-medium mb-2">Reset Password</h3>
            <div className="flex gap-2">
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="New password"
                className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-sm"
              />
              <button
                onClick={() => updateMutation.mutate({ password: newPassword })}
                disabled={!newPassword || updateMutation.isPending}
                className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg text-sm disabled:opacity-50"
              >
                {updateMutation.isPending ? 'Saving...' : 'Set Password'}
              </button>
            </div>
            {updateMutation.isError && (
              <p className="text-sm text-red-600 mt-2">{updateMutation.error?.response?.data?.error || 'Failed'}</p>
            )}
          </div>
        )}
      </div>

      {/* Organization Memberships */}
      {organizations.length > 0 && (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="font-semibold mb-4 flex items-center gap-2">
            <Building2 className="h-4 w-4" />
            Organization Memberships ({organizations.length})
          </h3>
          <div className="space-y-3">
            {organizations.map((org, idx) => (
              <div key={idx} className="p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
                <div className="flex items-center justify-between mb-1">
                  <Link to={`/superuser/organizations/${org.slug}`} className="font-medium hover:text-primary-600">
                    {org.name} <span className="text-gray-500 text-sm">/{org.slug}</span>
                  </Link>
                  <span className={clsx('text-xs px-2 py-0.5 rounded capitalize', roleColors[org.role])}>
                    {org.role}
                  </span>
                </div>
                {org.employee_profile && (
                  <div className="text-sm text-gray-600 dark:text-gray-400 mt-1 pl-2 border-l-2 border-gray-300 dark:border-gray-600">
                    {org.employee_profile.job_title && <p>Title: {org.employee_profile.job_title}</p>}
                    {org.employee_profile.department?.name && <p>Department: {org.employee_profile.department.name}</p>}
                    {org.employee_profile.manager?.email && <p>Reports to: {org.employee_profile.manager.email}</p>}
                  </div>
                )}
                {org.teams?.length > 0 && (
                  <div className="mt-1 text-sm">
                    <span className="text-gray-500">Teams: </span>
                    {org.teams.map((t, i) => (
                      <span key={i} className="inline-block bg-gray-200 dark:bg-gray-600 px-1.5 py-0.5 rounded text-xs mr-1">{t.name}</span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Assigned Tasks */}
      {assignedTasks.length > 0 && (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="font-semibold mb-4 flex items-center gap-2">
            <CheckSquare className="h-4 w-4" />
            Assigned Tasks ({assignedTasks.length})
          </h3>
          <div className="space-y-2">
            {assignedTasks.map((task, idx) => (
              <div key={idx} className="p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2 flex-wrap">
                    {task.item_key && (
                      <span className="text-xs text-gray-500 bg-gray-200 dark:bg-gray-600 px-1.5 py-0.5 rounded font-mono">{task.item_key}</span>
                    )}
                    <span className="font-medium">{task.title}</span>
                  </div>
                  {task.project_name && <p className="text-sm text-gray-500 mt-1">Project: {task.project_name}</p>}
                  {task.due_date && (
                    <p className="text-xs text-gray-500 mt-1 flex items-center gap-1">
                      <Clock className="h-3 w-3" /> Due: {new Date(task.due_date).toLocaleDateString()}
                      {task.is_overdue && <span className="text-red-500 flex items-center gap-0.5"><AlertCircle className="h-3 w-3" /> Overdue</span>}
                    </p>
                  )}
                </div>
                <span className={clsx('text-xs px-2 py-0.5 rounded capitalize', taskStatusColors[task.status] || 'bg-gray-200 dark:bg-gray-700')}>
                  {task.status?.replace('_', ' ')}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Services */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
        <UserServicesSection userId={parseInt(userId)} />
      </div>
    </div>
  )
}
