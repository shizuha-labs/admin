import { useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Users, Plus, Edit2, Trash2, X, Calendar
} from 'lucide-react'
import { useAdmin } from '../contexts/AdminContext'
import { teamsApi, departmentsApi, employeesApi } from '../services/api'
import { format } from 'date-fns'
import clsx from 'clsx'
import { groupTeamMembers, isDirectoryMember } from '../utils/teamMembers'

const teamTypeColors = {
  permanent: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  project: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  task_force: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  committee: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400',
}

function TeamCard({ team, onEdit, onDelete, onManageMembers }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center"
            style={{ backgroundColor: team.color + '20' }}
          >
            <Users className="h-5 w-5" style={{ color: team.color }} />
          </div>
          <div>
            <h3 className="font-semibold">
              <button onClick={() => onManageMembers(team)} className="text-left hover:text-primary-600 focus-visible:outline-primary-500 rounded" aria-label={`View members of ${team.name}`}>
                {team.name}
              </button>
            </h3>
            <span className={clsx('text-xs px-2 py-0.5 rounded', teamTypeColors[team.team_type])}>
              {team.team_type?.replace('_', ' ') || 'Unknown'}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => onEdit(team)}
            className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
            title="Edit"
          >
            <Edit2 className="h-4 w-4" />
          </button>
          <button
            onClick={() => onDelete(team)}
            className="p-1 hover:bg-red-100 dark:hover:bg-red-900/30 rounded text-red-500"
            title="Delete"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {team.description && (
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-3 line-clamp-2">
          {team.description}
        </p>
      )}

      <div className="flex items-center justify-between text-sm text-gray-500">
        <button onClick={() => onManageMembers(team)} className="flex items-center gap-2 text-primary-600 dark:text-primary-400 hover:underline rounded focus-visible:outline-primary-500" aria-label={`View ${team.member_count ?? 0} members of ${team.name}`}>
          <Users className="h-4 w-4" />
          <span>{team.member_count ?? 0} {team.member_count === 1 ? 'member' : 'members'} · View</span>
        </button>
        {team.department_name && (
          <span className="truncate">{team.department_name}</span>
        )}
      </div>

      {(team.start_date || team.end_date) && (
        <div className="flex items-center gap-1 mt-2 text-xs text-gray-500">
          <Calendar className="h-3 w-3" />
          <span>
            {team.start_date && format(new Date(team.start_date), 'MMM d, yyyy')}
            {team.end_date && ` - ${format(new Date(team.end_date), 'MMM d, yyyy')}`}
          </span>
        </div>
      )}
    </div>
  )
}

function TeamForm({ team, departments, onSave, onCancel }) {
  const [name, setName] = useState(team?.name || '')
  const [description, setDescription] = useState(team?.description || '')
  const [teamType, setTeamType] = useState(team?.team_type || 'permanent')
  const [departmentId, setDepartmentId] = useState(team?.department || '')
  const [leadEmail, setLeadEmail] = useState(team?.lead_email || '')
  const [color, setColor] = useState(team?.color || '#6366f1')
  const [startDate, setStartDate] = useState(team?.start_date || '')
  const [endDate, setEndDate] = useState(team?.end_date || '')

  const handleSubmit = (e) => {
    e.preventDefault()
    onSave({
      name,
      description,
      team_type: teamType,
      department: departmentId || null,
      lead_email: leadEmail || null,
      color,
      start_date: startDate || null,
      end_date: endDate || null,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium mb-1">Team Name *</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
          required
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium mb-1">Team Type</label>
          <select
            value={teamType}
            onChange={(e) => setTeamType(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
          >
            <option value="permanent">Permanent</option>
            <option value="project">Project-based</option>
            <option value="task_force">Task Force</option>
            <option value="committee">Committee</option>
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Color</label>
          <input
            type="color"
            value={color}
            onChange={(e) => setColor(e.target.value)}
            className="w-full h-10 px-1 py-1 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700"
          />
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">Department</label>
        <select
          value={departmentId}
          onChange={(e) => setDepartmentId(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
        >
          <option value="">None</option>
          {departments.map((d) => (
            <option key={d.id} value={d.id}>{d.name}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">Team Lead Email</label>
        <input
          type="email"
          value={leadEmail}
          onChange={(e) => setLeadEmail(e.target.value)}
          placeholder="lead@example.com"
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium mb-1">Start Date</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">End Date</label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
          />
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">Description</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
        />
      </div>

      <div className="flex justify-end gap-2 pt-4">
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
        >
          Cancel
        </button>
        <button
          type="submit"
          className="px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600"
        >
          {team ? 'Update' : 'Create'} Team
        </button>
      </div>
    </form>
  )
}

function MemberIdentity({ person, onRemove, removing }) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 p-4 space-y-3">
      <div className="min-w-0">
        <div className="font-semibold break-words">{person.name}</div>
        {person.email && <div className="text-sm text-gray-600 dark:text-gray-300 break-all">{person.email}</div>}
        {person.title && <div className="text-sm text-gray-500 dark:text-gray-400">{person.title}</div>}
      </div>
      {person.routing.map((member, index) => (
        <div key={member.routing_identity || index} className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full bg-primary-50 text-primary-700 dark:bg-primary-900/30 dark:text-primary-300 px-2 py-1">Task routing</span>
          <span className="text-gray-500 dark:text-gray-400">Pulse roster · <span className="capitalize">{member.role || 'member'}</span></span>
        </div>
      ))}
      {person.directory.map((member) => (
        <div key={member.id} className="flex items-center justify-between gap-3 text-xs">
          <span className="text-gray-500 dark:text-gray-400">Admin directory · <span className="capitalize">{member.role || 'member'}</span></span>
          <button onClick={() => onRemove(member)} disabled={removing} className="shrink-0 text-red-600 dark:text-red-400 hover:underline disabled:opacity-50 rounded focus-visible:outline-primary-500" aria-label={`Remove directory record for ${person.name}`}>
            Remove directory record
          </button>
        </div>
      ))}
      {person.other.length > 0 && <p className="text-xs text-gray-500">Membership source unavailable · read only</p>}
    </div>
  )
}

function TeamMembersModal({ team, orgSlug, onClose }) {
  const queryClient = useQueryClient()
  const dialogRef = useRef(null)
  const { data: membersData, isLoading: membersLoading, isError: membersError, refetch: retryMembers } = useQuery({
    queryKey: ['team-members', orgSlug, team.id],
    queryFn: () => teamsApi.members(orgSlug, team.id).then(res => res.data),
  })
  const { data: employeesRaw, isError: employeesError } = useQuery({
    queryKey: ['employees-list', orgSlug],
    queryFn: () => employeesApi.list(orgSlug).then(res => res.data),
  })
  const [selectedEmployee, setSelectedEmployee] = useState('')
  const [selectedRole, setSelectedRole] = useState('member')
  const employeesData = Array.isArray(employeesRaw) ? employeesRaw : (employeesRaw?.results || [])
  const people = groupTeamMembers(membersData?.members || [])
  const routing = people.filter(person => person.routing.length > 0)
  const directoryOnly = people.filter(person => person.routing.length === 0 && person.directory.length > 0)
  const unclassified = people.filter(person => person.routing.length === 0 && person.directory.length === 0)
  const directoryRows = (membersData?.members || []).filter(isDirectoryMember)

  // Keep keyboard navigation inside the member view and restore its opener.
  useEffect(() => {
    const opener = document.activeElement
    const dialog = dialogRef.current
    dialog?.querySelector('button')?.focus()
    const keydown = event => {
      if (event.key === 'Escape') { event.preventDefault(); onClose(); return }
      if (event.key !== 'Tab') return
      const controls = [...dialog.querySelectorAll('button:not(:disabled), select:not(:disabled), summary')].filter(el => el.getClientRects().length)
      const first = controls[0], last = controls[controls.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    dialog?.addEventListener('keydown', keydown)
    return () => { dialog?.removeEventListener('keydown', keydown); opener?.focus() }
  }, [onClose])

  const invalidateMembers = () => {
    queryClient.invalidateQueries({ queryKey: ['team-members', orgSlug, team.id] })
    queryClient.invalidateQueries({ queryKey: ['teams', orgSlug] })
  }
  const addMemberMutation = useMutation({
    mutationFn: data => teamsApi.addMember(orgSlug, team.id, data),
    onSuccess: () => { setSelectedEmployee(''); invalidateMembers() },
  })
  const removeMemberMutation = useMutation({
    mutationFn: member => {
      if (!isDirectoryMember(member)) throw new Error('Only directory records can be removed here')
      return teamsApi.removeMember(orgSlug, team.id, member.id)
    },
    onSuccess: invalidateMembers,
  })
  const availableEmployees = employeesData.filter(employee => !directoryRows.some(member => member.employee_profile === employee.id))
  const handleAddMember = () => {
    if (!selectedEmployee || !membersData || membersError) return
    addMemberMutation.mutate({ employee_profile_id: Number(selectedEmployee), role: selectedRole })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="team-members-title" className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-xl max-h-[85vh] flex flex-col">
        <div className="flex items-start justify-between gap-4 p-5 border-b border-gray-200 dark:border-gray-700">
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wide text-primary-600 dark:text-primary-400 mb-1">Team members</p>
            <h2 id="team-members-title" className="text-xl font-bold break-words">{team.name}</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              {membersData ? `${membersData.routing_count ?? routing.length} routing ${(membersData.routing_count ?? routing.length) === 1 ? 'member' : 'members'} · ${membersData.directory_count ?? directoryRows.length} directory records` : 'Members and directory records'}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close team members" className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"><X className="h-5 w-5" /></button>
        </div>
        <div className="overflow-y-auto p-5 space-y-5">
          {membersLoading ? <p role="status" className="text-gray-500">Loading members…</p> : !membersData && membersError ? (
            <div role="alert" className="rounded-lg bg-red-50 dark:bg-red-900/20 p-4 text-sm">
              <p>Members could not be loaded. Team membership is unknown.</p>
              <button onClick={() => retryMembers()} className="mt-2 font-medium text-primary-600 hover:underline">Try again</button>
            </div>
          ) : membersData && (
            <>
              <section aria-labelledby="routing-members-title" className="space-y-3">
                <h3 id="routing-members-title" className="text-sm font-semibold">Task-routing members</h3>
                <p className="text-xs text-gray-500 dark:text-gray-400">The Pulse roster determines who receives this team's tasks.</p>
                {routing.length ? routing.map(person => <MemberIdentity key={person.key} person={person} onRemove={removeMemberMutation.mutate} removing={membersError || removeMemberMutation.isPending} />) : <p className="text-sm text-gray-500 py-2">No task-routing members.</p>}
              </section>
              {directoryOnly.length > 0 && (
                <section aria-labelledby="directory-only-title" className="space-y-3 border-t border-gray-200 dark:border-gray-700 pt-4">
                  <h3 id="directory-only-title" className="text-sm font-semibold">Directory only</h3>
                  <p className="text-xs text-gray-500 dark:text-gray-400">These records do not make someone a task-routing member.</p>
                  {directoryOnly.map(person => <MemberIdentity key={person.key} person={person} onRemove={removeMemberMutation.mutate} removing={membersError || removeMemberMutation.isPending} />)}
                </section>
              )}
              {unclassified.length > 0 && (
                <section aria-label="Unclassified records" className="space-y-3">
                  <h3 className="text-sm font-semibold">Unclassified records</h3>
                  {unclassified.map(person => <MemberIdentity key={person.key} person={person} onRemove={removeMemberMutation.mutate} removing />)}
                </section>
              )}
              <details className="border-t border-gray-200 dark:border-gray-700 pt-4">
                <summary className="cursor-pointer text-sm font-medium text-primary-600 dark:text-primary-400">Add a directory record</summary>
                <p className="text-xs text-gray-500 my-3">Directory changes do not change the task-routing roster.</p>
                {employeesError ? <p role="alert" className="text-sm text-red-600">Employee directory could not be loaded.</p> : (
                  <div className="flex flex-wrap gap-2">
                    <select aria-label="Employee" value={selectedEmployee} onChange={event => setSelectedEmployee(event.target.value)} className="w-full min-w-0 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700">
                      <option value="">Select employee…</option>
                      {availableEmployees.map(employee => <option key={employee.id} value={employee.id}>{employee.display_name} — {employee.job_title || 'No title'}</option>)}
                    </select>
                    <select aria-label="Directory role" value={selectedRole} onChange={event => setSelectedRole(event.target.value)} className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700">
                      <option value="member">Member</option><option value="lead">Lead</option><option value="advisor">Advisor</option>
                    </select>
                    <button onClick={handleAddMember} disabled={!selectedEmployee || membersError || addMemberMutation.isPending} className="px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 disabled:opacity-50">Add record</button>
                  </div>
                )}
              </details>
            </>
          )}
          {(addMemberMutation.isError || removeMemberMutation.isError) && <p role="alert" className="text-sm text-red-600">Directory change failed. Please try again.</p>}
        </div>
      </div>
    </div>
  )
}

export default function Teams() {
  const { currentOrganization } = useAdmin()
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [editingTeam, setEditingTeam] = useState(null)
  const [deleteConfirm, setDeleteConfirm] = useState(null)
  const [managingTeam, setManagingTeam] = useState(null)

  const { data: teamsData, isLoading, isError: teamsError, refetch: retryTeams } = useQuery({
    queryKey: ['teams', currentOrganization?.slug],
    queryFn: () => teamsApi.list(currentOrganization.slug).then(res => res.data),
    enabled: !!currentOrganization?.slug,
  })

  const { data: departmentsData } = useQuery({
    queryKey: ['departments', currentOrganization?.slug],
    queryFn: () => departmentsApi.list(currentOrganization.slug).then(res => res.data),
    enabled: !!currentOrganization?.slug,
  })

  // Handle paginated response - API returns { results: [...] } or direct array
  const teams = Array.isArray(teamsData) ? teamsData : (teamsData?.results || [])
  const departments = Array.isArray(departmentsData) ? departmentsData : (departmentsData?.results || [])

  const createMutation = useMutation({
    mutationFn: (data) => teamsApi.create(currentOrganization.slug, data),
    onSuccess: () => {
      queryClient.invalidateQueries(['teams', currentOrganization.slug])
      setShowForm(false)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }) => teamsApi.update(currentOrganization.slug, id, data),
    onSuccess: () => {
      queryClient.invalidateQueries(['teams', currentOrganization.slug])
      setEditingTeam(null)
      setShowForm(false)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => teamsApi.delete(currentOrganization.slug, id),
    onSuccess: () => {
      queryClient.invalidateQueries(['teams', currentOrganization.slug])
      setDeleteConfirm(null)
    },
  })

  const handleSave = (data) => {
    if (editingTeam) {
      updateMutation.mutate({ id: editingTeam.id, data })
    } else {
      createMutation.mutate(data)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Teams</h1>
          <p className="text-gray-500 dark:text-gray-400">
            Manage cross-functional teams and groups
          </p>
        </div>
        {currentOrganization && (
          <button
            onClick={() => {
              setEditingTeam(null)
              setShowForm(true)
            }}
            className="flex items-center gap-2 px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600"
          >
            <Plus className="h-4 w-4" />
            Create Team
          </button>
        )}
      </div>

      {/* Teams Grid */}
      {!currentOrganization ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-12 text-center">
          <Users className="h-12 w-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
          <h3 className="text-lg font-medium">Select an organization</h3>
          <p className="text-gray-500 mt-1">
            Teams are managed per organization. Choose one from the organization
            switcher at the top to view and manage its teams.
          </p>
        </div>
      ) : isLoading ? (
        <p className="text-gray-500">Loading teams...</p>
      ) : teamsError && !teamsData ? (
        <div role="alert" className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-8">
          <h3 className="font-semibold">Teams could not be loaded</h3>
          <p className="text-sm text-gray-500 mt-1">Try again to view your organization's teams.</p>
          <button onClick={() => retryTeams()} className="mt-3 text-primary-600 font-medium hover:underline">Try again</button>
        </div>
      ) : teams?.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {teams.map((team) => (
            <TeamCard
              key={team.id}
              team={team}
              onEdit={(t) => {
                setEditingTeam(t)
                setShowForm(true)
              }}
              onDelete={(t) => setDeleteConfirm(t)}
              onManageMembers={(t) => setManagingTeam(t)}
            />
          ))}
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-12 text-center">
          <Users className="h-12 w-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
          <h3 className="text-lg font-medium">No teams yet</h3>
          <p className="text-gray-500 mt-1">Create your first team to get started</p>
          <button
            onClick={() => setShowForm(true)}
            className="mt-4 px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600"
          >
            Create Team
          </button>
        </div>
      )}

      {/* Form Modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-md mx-4 p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-bold">
                {editingTeam ? 'Edit Team' : 'Create Team'}
              </h2>
              <button
                onClick={() => {
                  setShowForm(false)
                  setEditingTeam(null)
                }}
                className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <TeamForm
              team={editingTeam}
              departments={departments}
              onSave={handleSave}
              onCancel={() => {
                setShowForm(false)
                setEditingTeam(null)
              }}
            />
          </div>
        </div>
      )}

      {/* Members Modal */}
      {managingTeam && (
        <TeamMembersModal
          team={managingTeam}
          orgSlug={currentOrganization.slug}
          onClose={() => setManagingTeam(null)}
        />
      )}

      {/* Delete Confirmation */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-sm mx-4 p-6">
            <h2 className="text-xl font-bold mb-2">Delete Team</h2>
            <p className="text-gray-600 dark:text-gray-400 mb-4">
              Are you sure you want to delete <strong>{deleteConfirm.name}</strong>?
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="px-4 py-2 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={() => deleteMutation.mutate(deleteConfirm.id)}
                disabled={deleteMutation.isPending}
                className="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 disabled:opacity-50"
              >
                {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
