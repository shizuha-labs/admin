import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import {
  Users, Search, Filter, ChevronDown, Mail, Phone, Building2, User, UserPlus, X
} from 'lucide-react'
import { useAdmin } from '../contexts/AdminContext'
import { employeesApi, departmentsApi, positionsApi, organizationsApi } from '../services/api'
import clsx from 'clsx'

const statusColors = {
  active: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  on_leave: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
  probation: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  suspended: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  terminated: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-400',
  resigned: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-400',
}

const typeLabels = {
  full_time: 'Full-time',
  part_time: 'Part-time',
  contractor: 'Contractor',
  intern: 'Intern',
  consultant: 'Consultant',
  temporary: 'Temporary',
}

function EmployeeCard({ employee }) {
  return (
    <Link
      to={`/employees/${employee.id}`}
      className="block bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5 hover:shadow-md transition-shadow"
    >
      <div className="flex items-start gap-4">
        <div className="w-12 h-12 rounded-full bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center flex-shrink-0">
          {employee.avatar_url ? (
            <img
              src={employee.avatar_url}
              alt={employee.display_name}
              className="w-12 h-12 rounded-full object-cover"
            />
          ) : (
            <User className="h-6 w-6 text-primary-600" />
          )}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold truncate">{employee.display_name}</h3>
            <span className={clsx('text-xs px-2 py-0.5 rounded capitalize', statusColors[employee.employment_status])}>
              {employee.employment_status?.replace('_', ' ') || 'Unknown'}
            </span>
          </div>

          <p className="text-sm text-gray-600 dark:text-gray-400 truncate">
            {employee.job_title || 'No title'}
          </p>

          <div className="flex items-center gap-4 mt-2 text-sm text-gray-500">
            <span className="flex items-center gap-1">
              <Mail className="h-3 w-3" />
              <span className="truncate">{employee.user_email}</span>
            </span>
          </div>

          <div className="flex items-center gap-2 mt-2">
            <span className="text-xs px-2 py-0.5 bg-gray-100 dark:bg-gray-700 rounded">
              {typeLabels[employee.employment_type] || employee.employment_type}
            </span>
            <span className="text-xs px-2 py-0.5 bg-gray-100 dark:bg-gray-700 rounded capitalize">
              {employee.role}
            </span>
          </div>
        </div>
      </div>
    </Link>
  )
}

function EmployeeTable({ employees }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-gray-200 dark:border-gray-700">
            <th className="text-left py-3 px-4 font-medium text-gray-500">Employee</th>
            <th className="text-left py-3 px-4 font-medium text-gray-500">Title</th>
            <th className="text-left py-3 px-4 font-medium text-gray-500">Department</th>
            <th className="text-left py-3 px-4 font-medium text-gray-500">Status</th>
            <th className="text-left py-3 px-4 font-medium text-gray-500">Type</th>
          </tr>
        </thead>
        <tbody>
          {employees.map((employee) => (
            <tr
              key={employee.id}
              className="border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/50"
            >
              <td className="py-3 px-4">
                <Link
                  to={`/employees/${employee.id}`}
                  className="flex items-center gap-3 hover:text-primary-600"
                >
                  <div className="w-8 h-8 rounded-full bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center flex-shrink-0">
                    {employee.avatar_url ? (
                      <img
                        src={employee.avatar_url}
                        alt={employee.display_name}
                        className="w-8 h-8 rounded-full object-cover"
                      />
                    ) : (
                      <User className="h-4 w-4 text-primary-600" />
                    )}
                  </div>
                  <div>
                    <div className="font-medium">{employee.display_name}</div>
                    <div className="text-sm text-gray-500">{employee.user_email}</div>
                  </div>
                </Link>
              </td>
              <td className="py-3 px-4 text-sm">
                {employee.job_title || '-'}
              </td>
              <td className="py-3 px-4 text-sm">
                -
              </td>
              <td className="py-3 px-4">
                <span className={clsx('text-xs px-2 py-0.5 rounded capitalize', statusColors[employee.employment_status])}>
                  {employee.employment_status?.replace('_', ' ') || 'Unknown'}
                </span>
              </td>
              <td className="py-3 px-4 text-sm">
                {typeLabels[employee.employment_type] || employee.employment_type}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function CreateEmployeeModal({ isOpen, onClose, orgSlug, prefillMembershipId }) {
  const queryClient = useQueryClient()
  const today = new Date().toISOString().split('T')[0]
  const [form, setForm] = useState({
    membership_id: prefillMembershipId || '',
    job_title: '',
    department: '',
    position: '',
    manager_id: '',
    employment_status: 'active',
    employment_type: 'full_time',
    start_date: today,
  })

  useEffect(() => {
    if (prefillMembershipId) {
      setForm(prev => ({ ...prev, membership_id: prefillMembershipId }))
    }
  }, [prefillMembershipId])

  const { data: membersData } = useQuery({
    queryKey: ['org-members', orgSlug],
    queryFn: () => organizationsApi.members(orgSlug).then(res => res.data),
    enabled: isOpen && !!orgSlug,
  })

  const { data: existingEmployeesData } = useQuery({
    queryKey: ['employees', orgSlug],
    queryFn: () => employeesApi.list(orgSlug).then(res => res.data),
    enabled: isOpen && !!orgSlug,
  })

  const { data: departmentsData } = useQuery({
    queryKey: ['departments', orgSlug],
    queryFn: () => departmentsApi.list(orgSlug).then(res => res.data),
    enabled: isOpen && !!orgSlug,
  })

  const { data: positionsData } = useQuery({
    queryKey: ['positions', orgSlug],
    queryFn: () => positionsApi.list(orgSlug).then(res => res.data),
    enabled: isOpen && !!orgSlug,
  })

  const members = membersData?.members || []
  const existingEmployees = Array.isArray(existingEmployeesData) ? existingEmployeesData : (existingEmployeesData?.results || [])
  const departments = Array.isArray(departmentsData) ? departmentsData : (departmentsData?.results || [])
  const positions = Array.isArray(positionsData) ? positionsData : (positionsData?.results || [])

  const employeeMembershipIds = new Set(existingEmployees.map(e => e.membership))
  const availableMembers = members.filter(m => !employeeMembershipIds.has(m.id))

  const createMutation = useMutation({
    mutationFn: (data) => employeesApi.create(orgSlug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['employees', orgSlug] })
      onClose()
      setForm({
        membership_id: '',
        job_title: '',
        department: '',
        position: '',
        manager_id: '',
        employment_status: 'active',
        employment_type: 'full_time',
        start_date: today,
      })
    },
  })

  if (!isOpen) return null

  const handleSubmit = (e) => {
    e.preventDefault()
    const selectedManager = existingEmployees.find(emp => String(emp.user_id) === String(form.manager_id))
    const payload = {
      membership_id: Number(form.membership_id),
      job_title: form.job_title || '',
      department: form.department || null,
      position: form.position || null,
      manager_id: form.manager_id ? Number(form.manager_id) : null,
      manager_email: selectedManager?.user_email || '',
      employment_status: form.employment_status,
      employment_type: form.employment_type,
      start_date: form.start_date || null,
    }
    createMutation.mutate(payload)
  }

  const setField = (field, value) => setForm(prev => ({ ...prev, [field]: value }))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-white dark:bg-gray-800 rounded-xl shadow-xl p-6 w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Create Employee Profile</h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">Member *</label>
            <select
              value={form.membership_id}
              onChange={(e) => setField('membership_id', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
              required
            >
              <option value="">Select a member...</option>
              {availableMembers.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.user_email} ({m.role})
                </option>
              ))}
            </select>
            {availableMembers.length === 0 && members.length > 0 && (
              <p className="text-xs text-gray-500 mt-1">All members already have employee profiles.</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Job Title</label>
            <input
              type="text"
              value={form.job_title}
              onChange={(e) => setField('job_title', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Department</label>
            <select
              value={form.department}
              onChange={(e) => setField('department', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
            >
              <option value="">None</option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Position</label>
            <select
              value={form.position}
              onChange={(e) => setField('position', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
            >
              <option value="">None</option>
              {positions.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title}{p.department_name ? ` (${p.department_name})` : ''}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Reports To</label>
            <select
              value={form.manager_id}
              onChange={(e) => setField('manager_id', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
            >
              <option value="">None (Top-level)</option>
              {existingEmployees.map((emp) => (
                <option key={emp.id} value={emp.user_id}>
                  {emp.display_name}{emp.job_title ? ` - ${emp.job_title}` : ''}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">Status</label>
              <select
                value={form.employment_status}
                onChange={(e) => setField('employment_status', e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
              >
                <option value="active">Active</option>
                <option value="on_leave">On Leave</option>
                <option value="probation">Probation</option>
                <option value="suspended">Suspended</option>
                <option value="terminated">Terminated</option>
                <option value="resigned">Resigned</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Type</label>
              <select
                value={form.employment_type}
                onChange={(e) => setField('employment_type', e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
              >
                <option value="full_time">Full-time</option>
                <option value="part_time">Part-time</option>
                <option value="contractor">Contractor</option>
                <option value="intern">Intern</option>
                <option value="consultant">Consultant</option>
                <option value="temporary">Temporary</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Start Date</label>
            <input
              type="date"
              value={form.start_date}
              onChange={(e) => setField('start_date', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
            />
          </div>

          {createMutation.error && (
            <p className="text-sm text-red-600">
              {createMutation.error.response?.data?.error || createMutation.error.response?.data?.detail || 'Failed to create employee profile'}
            </p>
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
              className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
            >
              {createMutation.isPending ? 'Creating...' : 'Create Profile'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function Employees() {
  const { currentOrganization } = useAdmin()
  const [searchParams, setSearchParams] = useSearchParams()
  const [viewMode, setViewMode] = useState('grid')
  const [search, setSearch] = useState('')
  const [filterDepartment, setFilterDepartment] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [filterType, setFilterType] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [showCreateModal, setShowCreateModal] = useState(false)

  // Handle ?create=<membership_id> from Members page
  const createParam = searchParams.get('create')
  useEffect(() => {
    if (createParam) {
      setShowCreateModal(true)
    }
  }, [createParam])

  const handleCloseCreateModal = () => {
    setShowCreateModal(false)
    if (createParam) {
      searchParams.delete('create')
      setSearchParams(searchParams, { replace: true })
    }
  }

  const { data: employeesData, isLoading } = useQuery({
    queryKey: ['employees', currentOrganization?.slug, { search, department: filterDepartment, status: filterStatus, type: filterType }],
    queryFn: () => employeesApi.list(currentOrganization.slug, {
      search: search || undefined,
      department: filterDepartment || undefined,
      status: filterStatus || undefined,
      type: filterType || undefined,
    }).then(res => res.data),
    enabled: !!currentOrganization?.slug,
  })

  const { data: departmentsData } = useQuery({
    queryKey: ['departments', currentOrganization?.slug],
    queryFn: () => departmentsApi.list(currentOrganization.slug).then(res => res.data),
    enabled: !!currentOrganization?.slug,
  })

  // Handle paginated response - API returns { results: [...] } or direct array
  const employees = Array.isArray(employeesData) ? employeesData : (employeesData?.results || [])
  const departments = Array.isArray(departmentsData) ? departmentsData : (departmentsData?.results || [])

  const clearFilters = () => {
    setSearch('')
    setFilterDepartment('')
    setFilterStatus('')
    setFilterType('')
  }

  const hasFilters = search || filterDepartment || filterStatus || filterType

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Employees</h1>
          <p className="text-gray-500 dark:text-gray-400">
            View and manage employee profiles
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowCreateModal(true)}
            className="inline-flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
          >
            <UserPlus className="h-4 w-4" />
            Create Employee Profile
          </button>
          <button
            onClick={() => setViewMode('grid')}
            className={clsx(
              'p-2 rounded-lg',
              viewMode === 'grid'
                ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-600'
                : 'hover:bg-gray-100 dark:hover:bg-gray-700'
            )}
          >
            <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
              <path d="M5 3a2 2 0 00-2 2v2a2 2 0 002 2h2a2 2 0 002-2V5a2 2 0 00-2-2H5zM5 11a2 2 0 00-2 2v2a2 2 0 002 2h2a2 2 0 002-2v-2a2 2 0 00-2-2H5zM11 5a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V5zM11 13a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
            </svg>
          </button>
          <button
            onClick={() => setViewMode('table')}
            className={clsx(
              'p-2 rounded-lg',
              viewMode === 'table'
                ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-600'
                : 'hover:bg-gray-100 dark:hover:bg-gray-700'
            )}
          >
            <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M3 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" clipRule="evenodd" />
            </svg>
          </button>
        </div>
      </div>

      {/* Search and Filters */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
        <div className="flex flex-col md:flex-row gap-4">
          {/* Search */}
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name, email, or employee ID..."
              className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
            />
          </div>

          <button
            onClick={() => setShowFilters(!showFilters)}
            className={clsx(
              'flex items-center gap-2 px-4 py-2 border rounded-lg',
              hasFilters
                ? 'border-primary-500 text-primary-600 bg-primary-50 dark:bg-primary-900/20'
                : 'border-gray-300 dark:border-gray-600'
            )}
          >
            <Filter className="h-4 w-4" />
            Filters
            {hasFilters && (
              <span className="w-2 h-2 bg-primary-500 rounded-full" />
            )}
            <ChevronDown className={clsx('h-4 w-4 transition-transform', showFilters && 'rotate-180')} />
          </button>
        </div>

        {/* Filter Row */}
        {showFilters && (
          <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700 flex flex-wrap gap-4">
            <select
              value={filterDepartment}
              onChange={(e) => setFilterDepartment(e.target.value)}
              className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700"
            >
              <option value="">All Departments</option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>

            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700"
            >
              <option value="">All Status</option>
              <option value="active">Active</option>
              <option value="on_leave">On Leave</option>
              <option value="probation">Probation</option>
              <option value="suspended">Suspended</option>
              <option value="terminated">Terminated</option>
              <option value="resigned">Resigned</option>
            </select>

            <select
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700"
            >
              <option value="">All Types</option>
              <option value="full_time">Full-time</option>
              <option value="part_time">Part-time</option>
              <option value="contractor">Contractor</option>
              <option value="intern">Intern</option>
              <option value="consultant">Consultant</option>
              <option value="temporary">Temporary</option>
            </select>

            {hasFilters && (
              <button
                onClick={clearFilters}
                className="px-3 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100"
              >
                Clear filters
              </button>
            )}
          </div>
        )}
      </div>

      {/* Results */}
      {isLoading ? (
        <p className="text-gray-500">Loading employees...</p>
      ) : employees?.length > 0 ? (
        viewMode === 'grid' ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {employees.map((employee) => (
              <EmployeeCard key={employee.id} employee={employee} />
            ))}
          </div>
        ) : (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
            <EmployeeTable employees={employees} />
          </div>
        )
      ) : (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-12 text-center">
          <Users className="h-12 w-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
          <h3 className="text-lg font-medium">No employees found</h3>
          <p className="text-gray-500 mt-1">
            {hasFilters
              ? 'Try adjusting your filters'
              : 'Employee profiles will appear here once created'
            }
          </p>
        </div>
      )}

      <CreateEmployeeModal
        isOpen={showCreateModal}
        onClose={handleCloseCreateModal}
        orgSlug={currentOrganization?.slug}
        prefillMembershipId={createParam || ''}
      />
    </div>
  )
}
