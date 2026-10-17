import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Building2, Users, ArrowLeft, Loader2, Save, Crown, Shield, Blocks,
  UserCircle, Network, UsersRound, Clock,
} from 'lucide-react'
import { superuserApi, servicesApi } from '../../services/api'
import { useAdmin } from '../../contexts/AdminContext'
import clsx from 'clsx'

const roleColors = {
  owner: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
  admin: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  member: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  viewer: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-400',
}

const planColors = {
  free: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400',
  team: 'bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400',
  business: 'bg-purple-100 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400',
  enterprise: 'bg-yellow-100 text-yellow-600 dark:bg-yellow-900/30 dark:text-yellow-400',
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

function OrgServicesSection({ orgSlug }) {
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['superuser-org-services', orgSlug],
    queryFn: () => servicesApi.getOrgServices(orgSlug).then(res => res.data),
    enabled: !!orgSlug,
  })

  const toggleMutation = useMutation({
    mutationFn: ({ slugs, action }) => servicesApi.updateOrgServices(orgSlug, { service_slugs: slugs, action }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['superuser-org-services', orgSlug] })
    },
  })

  if (isLoading) {
    return <div className="flex items-center justify-center py-4"><Loader2 className="h-4 w-4 animate-spin text-gray-400" /></div>
  }

  const services = data?.services || data || []

  return (
    <div>
      <h3 className="font-semibold mb-3 flex items-center gap-2">
        <Blocks className="h-4 w-4" />
        Enabled Services
      </h3>
      <div className="grid grid-cols-2 gap-2">
        {services.map((svc) => {
          const slug = svc.slug || svc.service_slug || svc
          const name = svc.name || slug
          const enabled = svc.is_enabled !== undefined ? svc.is_enabled : true

          return (
            <label
              key={slug}
              className="flex items-center justify-between p-2 bg-gray-50 dark:bg-gray-700/50 rounded-lg text-sm"
            >
              <span>{name}</span>
              <ServiceToggle
                enabled={enabled}
                disabled={toggleMutation.isPending}
                onToggle={() => toggleMutation.mutate({
                  slugs: [slug],
                  action: enabled ? 'revoke' : 'grant'
                })}
              />
            </label>
          )
        })}
      </div>
    </div>
  )
}

export default function SuperuserOrgDetail() {
  const { slug } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { isSuperuser } = useAdmin()

  const [activeTab, setActiveTab] = useState('members')
  const [editing, setEditing] = useState(false)
  const [editForm, setEditForm] = useState({})

  const { data, isLoading, error } = useQuery({
    queryKey: ['superuser-org-detail', slug],
    queryFn: () => superuserApi.orgDetail(slug).then(res => res.data),
    enabled: !!slug,
  })

  const updateMutation = useMutation({
    mutationFn: (updates) => superuserApi.updateOrg(slug, updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['superuser-org-detail', slug] })
      queryClient.invalidateQueries({ queryKey: ['superuser-orgs'] })
      setEditing(false)
    },
  })

  const startEditing = () => {
    setEditForm({
      name: data?.name || '',
      description: data?.description || '',
      plan: data?.plan || 'free',
      billing_email: data?.billing_email || '',
      is_active: data?.is_active !== false,
    })
    setEditing(true)
  }

  if (isLoading) {
    return <div className="flex items-center justify-center h-32"><Loader2 className="h-6 w-6 animate-spin text-gray-400" /></div>
  }

  if (error || !data) {
    return (
      <div className="space-y-4">
        <button onClick={() => navigate('/superuser/organizations')} className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700">
          <ArrowLeft className="h-4 w-4" /> Back to Organizations
        </button>
        <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-4 rounded-lg">Organization not found.</div>
      </div>
    )
  }

  const tabs = [
    { key: 'members', label: 'Members', icon: Users, count: data.members?.length },
    { key: 'departments', label: 'Departments', icon: Network, count: data.departments?.length },
    { key: 'teams', label: 'Teams', icon: UsersRound, count: data.teams?.length },
    { key: 'services', label: 'Services', icon: Blocks },
  ]

  return (
    <div className="space-y-6">
      <button onClick={() => navigate('/superuser/organizations')} className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300">
        <ArrowLeft className="h-4 w-4" /> Back to Organizations
      </button>

      {/* Org Header */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
        <div className="flex items-start justify-between">
          <div className="flex items-start gap-4">
            <div className="w-14 h-14 rounded-lg bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center">
              <Building2 className="h-7 w-7 text-primary-600" />
            </div>
            <div>
              {editing ? (
                <div className="space-y-3">
                  <input
                    type="text"
                    value={editForm.name}
                    onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                    className="px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-lg font-semibold"
                  />
                  <div className="grid grid-cols-2 gap-3">
                    <select
                      value={editForm.plan}
                      onChange={(e) => setEditForm({ ...editForm, plan: e.target.value })}
                      className="px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-sm"
                    >
                      <option value="free">Free</option>
                      <option value="team">Team</option>
                      <option value="business">Business</option>
                      <option value="enterprise">Enterprise</option>
                    </select>
                    <input
                      type="email"
                      value={editForm.billing_email}
                      onChange={(e) => setEditForm({ ...editForm, billing_email: e.target.value })}
                      placeholder="Billing email"
                      className="px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-sm"
                    />
                  </div>
                  <textarea
                    value={editForm.description}
                    onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                    rows={2}
                    placeholder="Description"
                    className="w-full px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-sm"
                  />
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={editForm.is_active} onChange={(e) => setEditForm({ ...editForm, is_active: e.target.checked })} />
                    Active
                  </label>
                  <div className="flex gap-2">
                    <button
                      onClick={() => updateMutation.mutate(editForm)}
                      disabled={updateMutation.isPending}
                      className="px-3 py-1.5 bg-primary-600 hover:bg-primary-700 text-white rounded-lg text-sm flex items-center gap-1"
                    >
                      {updateMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />} Save
                    </button>
                    <button onClick={() => setEditing(false)} className="px-3 py-1.5 text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg text-sm">Cancel</button>
                  </div>
                  {updateMutation.isError && <p className="text-sm text-red-600">{updateMutation.error?.response?.data?.error || 'Update failed'}</p>}
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-2">
                    <h2 className="text-xl font-semibold">{data.name}</h2>
                    <span className={clsx('text-xs px-2 py-0.5 rounded capitalize', planColors[data.plan])}>{data.plan}</span>
                    {!data.is_active && <span className="text-xs px-2 py-0.5 rounded bg-red-100 dark:bg-red-900/30 text-red-600">Inactive</span>}
                  </div>
                  <p className="text-sm text-gray-500">/{data.slug}</p>
                  {data.description && <p className="text-gray-600 dark:text-gray-400 mt-1 text-sm">{data.description}</p>}
                  <div className="flex items-center gap-4 mt-2 text-sm text-gray-500">
                    <span className="flex items-center gap-1"><Users className="h-4 w-4" /> {data.members?.length || 0} members</span>
                    {data.billing_email && <span>Billing: {data.billing_email}</span>}
                    {data.created_at && <span>Created: {new Date(data.created_at).toLocaleDateString()}</span>}
                  </div>
                </>
              )}
            </div>
          </div>

          {isSuperuser && !editing && (
            <button onClick={startEditing} className="px-3 py-1.5 text-sm bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-lg">
              Edit
            </button>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
        <div className="flex border-b border-gray-200 dark:border-gray-700">
          {tabs.map(({ key, label, icon: Icon, count }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={clsx(
                'px-4 py-3 font-medium border-b-2 -mb-px flex items-center gap-2 text-sm',
                activeTab === key
                  ? 'border-primary-500 text-primary-600 dark:text-primary-400'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
              {count !== undefined && <span className="text-xs bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded">{count}</span>}
            </button>
          ))}
        </div>

        <div className="p-4">
          {/* Members Tab */}
          {activeTab === 'members' && (
            <div className="space-y-2">
              {data.members?.length > 0 ? data.members.map((member) => (
                <div key={member.id} className="flex items-center justify-between py-2 px-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
                  <div className="flex items-center gap-3">
                    <UserCircle className="h-8 w-8 text-gray-400" />
                    <div>
                      <div className="flex items-center gap-2">
                        {member.user_id ? (
                          <Link to={`/superuser/users/${member.user_id}`} className="font-medium hover:text-primary-600">
                            {member.user_email || `User #${member.user_id}`}
                          </Link>
                        ) : (
                          <span className="font-medium">{member.user_email}</span>
                        )}
                        {member.is_pending && (
                          <span className="text-xs px-2 py-0.5 rounded bg-gray-200 dark:bg-gray-600 text-gray-600 dark:text-gray-400 flex items-center gap-1">
                            <Clock className="h-3 w-3" /> Pending
                          </span>
                        )}
                      </div>
                      {member.employee_profile && (
                        <p className="text-xs text-gray-500">
                          {member.employee_profile.job_title}
                          {member.employee_profile.department && ` - ${member.employee_profile.department}`}
                        </p>
                      )}
                    </div>
                  </div>
                  <span className={clsx('text-xs px-2 py-0.5 rounded capitalize', roleColors[member.role])}>{member.role}</span>
                </div>
              )) : (
                <p className="text-center text-gray-500 py-4">No members.</p>
              )}
            </div>
          )}

          {/* Departments Tab */}
          {activeTab === 'departments' && (
            <div className="space-y-2">
              {data.departments?.length > 0 ? data.departments.map((dept) => (
                <div key={dept.id} className="flex items-center justify-between py-2 px-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{dept.name}</span>
                      {dept.code && <span className="text-xs text-gray-500 bg-gray-200 dark:bg-gray-600 px-1.5 py-0.5 rounded">{dept.code}</span>}
                    </div>
                    {dept.head_email && <p className="text-xs text-gray-500">Head: {dept.head_email}</p>}
                  </div>
                  <span className="text-sm text-gray-500">{dept.employee_count} employees</span>
                </div>
              )) : (
                <p className="text-center text-gray-500 py-4">No departments.</p>
              )}
            </div>
          )}

          {/* Teams Tab */}
          {activeTab === 'teams' && (
            <div className="space-y-2">
              {data.teams?.length > 0 ? data.teams.map((team) => (
                <div key={team.id} className="flex items-center justify-between py-2 px-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{team.name}</span>
                      <span className="text-xs text-gray-500 bg-gray-200 dark:bg-gray-600 px-1.5 py-0.5 rounded capitalize">{team.team_type}</span>
                    </div>
                    {team.lead_email && <p className="text-xs text-gray-500">Lead: {team.lead_email}</p>}
                  </div>
                  <span className="text-sm text-gray-500">{team.member_count} members</span>
                </div>
              )) : (
                <p className="text-center text-gray-500 py-4">No teams.</p>
              )}
            </div>
          )}

          {/* Services Tab */}
          {activeTab === 'services' && <OrgServicesSection orgSlug={slug} />}
        </div>
      </div>
    </div>
  )
}
