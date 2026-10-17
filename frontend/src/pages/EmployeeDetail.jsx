import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, User, Mail, Phone, Building2, Calendar, MapPin, Users, ChevronRight, Edit2, X
} from 'lucide-react'
import { useAdmin } from '../contexts/AdminContext'
import { employeesApi, departmentsApi, positionsApi } from '../services/api'
import { format } from 'date-fns'
import clsx from 'clsx'

const statusColors = {
  active: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  on_leave: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
  probation: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  suspended: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  terminated: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-400',
  resigned: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-400',
}

function InfoSection({ title, children }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
      <h2 className="text-lg font-semibold mb-4">{title}</h2>
      {children}
    </div>
  )
}

function InfoRow({ label, value, icon: Icon }) {
  if (!value) return null
  return (
    <div className="flex items-center gap-3 py-2">
      {Icon && <Icon className="h-4 w-4 text-gray-400" />}
      <span className="text-sm text-gray-500 w-32">{label}</span>
      <span className="text-sm font-medium">{value}</span>
    </div>
  )
}

function ReportCard({ employee, type }) {
  return (
    <Link
      to={`/employees/${employee.id}`}
      className="flex items-center gap-3 p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
    >
      <div className="w-10 h-10 rounded-full bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center">
        {employee.avatar_url ? (
          <img
            src={employee.avatar_url}
            alt={employee.display_name}
            className="w-10 h-10 rounded-full object-cover"
          />
        ) : (
          <User className="h-5 w-5 text-primary-600" />
        )}
      </div>
      <div className="flex-1">
        <div className="font-medium">{employee.display_name}</div>
        <div className="text-sm text-gray-500">{employee.job_title || 'No title'}</div>
      </div>
      <ChevronRight className="h-4 w-4 text-gray-400" />
    </Link>
  )
}

function EditEmployeeModal({ isOpen, onClose, employee, orgSlug }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    job_title: employee?.job_title || '',
    department: employee?.department || '',
    position: employee?.position || '',
    manager_id: employee?.manager_id || '',
    employment_status: employee?.employment_status || 'active',
    employment_type: employee?.employment_type || 'full_time',
    start_date: employee?.start_date || '',
    work_phone: employee?.work_phone || '',
    work_email: employee?.work_email || '',
    office_location: employee?.office_location || '',
    employee_id: employee?.employee_id || '',
    bio: employee?.bio || '',
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

  const { data: allEmployeesData } = useQuery({
    queryKey: ['employees', orgSlug],
    queryFn: () => employeesApi.list(orgSlug).then(res => res.data),
    enabled: isOpen && !!orgSlug,
  })

  const departments = Array.isArray(departmentsData) ? departmentsData : (departmentsData?.results || [])
  const positions = Array.isArray(positionsData) ? positionsData : (positionsData?.results || [])
  const allEmployees = Array.isArray(allEmployeesData) ? allEmployeesData : (allEmployeesData?.results || [])
  const managerOptions = allEmployees.filter(e => e.id !== employee?.id)

  const updateMutation = useMutation({
    mutationFn: (data) => employeesApi.update(orgSlug, employee.id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['employee', orgSlug, String(employee.id)] })
      queryClient.invalidateQueries({ queryKey: ['direct-reports', orgSlug] })
      queryClient.invalidateQueries({ queryKey: ['management-chain', orgSlug] })
      queryClient.invalidateQueries({ queryKey: ['employees', orgSlug] })
      onClose()
    },
  })

  if (!isOpen || !employee) return null

  const handleSubmit = (e) => {
    e.preventDefault()
    const selectedManager = managerOptions.find(emp => String(emp.user_id) === String(form.manager_id))
    const payload = {
      job_title: form.job_title || '',
      department: form.department || null,
      position: form.position || null,
      manager_id: form.manager_id ? Number(form.manager_id) : null,
      manager_email: selectedManager?.user_email || '',
      employment_status: form.employment_status,
      employment_type: form.employment_type,
      start_date: form.start_date || null,
      work_phone: form.work_phone || '',
      work_email: form.work_email || '',
      office_location: form.office_location || '',
      employee_id: form.employee_id || '',
      bio: form.bio || '',
    }
    updateMutation.mutate(payload)
  }

  const setField = (field, value) => setForm(prev => ({ ...prev, [field]: value }))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-white dark:bg-gray-800 rounded-xl shadow-xl p-6 w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Edit Employee</h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
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
              {managerOptions.map((emp) => (
                <option key={emp.id} value={emp.user_id}>
                  {emp.display_name}{emp.job_title ? ` - ${emp.job_title}` : ''}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">Employment Status</label>
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
              <label className="block text-sm font-medium mb-1">Employment Type</label>
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

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">Work Phone</label>
              <input
                type="text"
                value={form.work_phone}
                onChange={(e) => setField('work_phone', e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Work Email</label>
              <input
                type="email"
                value={form.work_email}
                onChange={(e) => setField('work_email', e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">Office Location</label>
              <input
                type="text"
                value={form.office_location}
                onChange={(e) => setField('office_location', e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Employee ID</label>
              <input
                type="text"
                value={form.employee_id}
                onChange={(e) => setField('employee_id', e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Bio</label>
            <textarea
              value={form.bio}
              onChange={(e) => setField('bio', e.target.value)}
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
            />
          </div>

          {updateMutation.error && (
            <p className="text-sm text-red-600">
              {updateMutation.error.response?.data?.error || updateMutation.error.response?.data?.detail || 'Failed to update employee'}
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
              disabled={updateMutation.isPending}
              className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
            >
              {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function EmployeeDetail() {
  const { id } = useParams()
  const { currentOrganization } = useAdmin()
  const [showEditModal, setShowEditModal] = useState(false)

  const { data: employee, isLoading } = useQuery({
    queryKey: ['employee', currentOrganization?.slug, id],
    queryFn: () => employeesApi.get(currentOrganization.slug, id).then(res => res.data),
    enabled: !!currentOrganization?.slug && !!id,
  })

  const { data: directReports } = useQuery({
    queryKey: ['direct-reports', currentOrganization?.slug, id],
    queryFn: () => employeesApi.directReports(currentOrganization.slug, id).then(res => res.data),
    enabled: !!currentOrganization?.slug && !!id,
  })

  const { data: managementChain } = useQuery({
    queryKey: ['management-chain', currentOrganization?.slug, id],
    queryFn: () => employeesApi.managementChain(currentOrganization.slug, id).then(res => res.data),
    enabled: !!currentOrganization?.slug && !!id,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-gray-500">Loading employee details...</p>
      </div>
    )
  }

  if (!employee) {
    return (
      <div className="text-center py-12">
        <User className="h-12 w-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
        <h3 className="text-lg font-medium">Employee not found</h3>
        <Link to="/employees" className="text-primary-600 hover:underline mt-2 inline-block">
          Back to employees
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Back Link */}
      <Link
        to="/employees"
        className="inline-flex items-center gap-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Employees
      </Link>

      {/* Header */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
        <div className="flex items-start gap-6">
          <div className="w-24 h-24 rounded-full bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center flex-shrink-0">
            {employee.avatar_url ? (
              <img
                src={employee.avatar_url}
                alt={employee.display_name}
                className="w-24 h-24 rounded-full object-cover"
              />
            ) : (
              <User className="h-12 w-12 text-primary-600" />
            )}
          </div>

          <div className="flex-1">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-2xl font-bold">{employee.display_name}</h1>
              <span className={clsx('px-2 py-1 rounded text-sm capitalize', statusColors[employee.employment_status])}>
                {employee.employment_status?.replace('_', ' ') || 'Unknown'}
              </span>
              <button
                onClick={() => setShowEditModal(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
              >
                <Edit2 className="h-3.5 w-3.5" />
                Edit
              </button>
            </div>

            <p className="text-lg text-gray-600 dark:text-gray-400 mt-1">
              {employee.effective_job_title || 'No title'}
            </p>

            <div className="flex flex-wrap gap-4 mt-4 text-sm text-gray-500">
              <span className="flex items-center gap-1">
                <Mail className="h-4 w-4" />
                {employee.user_email}
              </span>
              {employee.work_phone && (
                <span className="flex items-center gap-1">
                  <Phone className="h-4 w-4" />
                  {employee.work_phone}
                </span>
              )}
              {employee.department_name && (
                <span className="flex items-center gap-1">
                  <Building2 className="h-4 w-4" />
                  {employee.department_name}
                </span>
              )}
              {employee.office_location && (
                <span className="flex items-center gap-1">
                  <MapPin className="h-4 w-4" />
                  {employee.office_location}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Info */}
        <div className="lg:col-span-2 space-y-6">
          {/* Employment Details */}
          <InfoSection title="Employment Details">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <InfoRow label="Employee ID" value={employee.employee_id} />
                <InfoRow
                  label="Employment Type"
                  value={employee.employment_type?.replace('_', ' ')}
                />
                <InfoRow
                  label="Start Date"
                  value={employee.start_date && format(new Date(employee.start_date), 'MMM d, yyyy')}
                  icon={Calendar}
                />
                <InfoRow
                  label="End Date"
                  value={employee.end_date && format(new Date(employee.end_date), 'MMM d, yyyy')}
                  icon={Calendar}
                />
              </div>
              <div>
                <InfoRow label="Department" value={employee.department_name} icon={Building2} />
                <InfoRow label="Position" value={employee.position_title} />
                <InfoRow label="Manager" value={employee.manager_name} icon={User} />
                <InfoRow
                  label="Probation End"
                  value={employee.probation_end_date && format(new Date(employee.probation_end_date), 'MMM d, yyyy')}
                />
              </div>
            </div>
          </InfoSection>

          {/* Contact Information */}
          <InfoSection title="Contact Information">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <InfoRow label="Work Email" value={employee.work_email || employee.user_email} icon={Mail} />
                <InfoRow label="Work Phone" value={employee.work_phone} icon={Phone} />
                <InfoRow label="Extension" value={employee.extension} />
              </div>
              <div>
                <InfoRow label="Office" value={employee.office_location} icon={MapPin} />
                <InfoRow label="Desk" value={employee.desk_number} />
                <InfoRow label="Timezone" value={employee.timezone} />
              </div>
            </div>
          </InfoSection>

          {/* Bio */}
          {employee.bio && (
            <InfoSection title="About">
              <p className="text-gray-600 dark:text-gray-400 whitespace-pre-wrap">
                {employee.bio}
              </p>
            </InfoSection>
          )}

          {/* Team Memberships */}
          {employee.team_memberships_list?.length > 0 && (
            <InfoSection title="Team Memberships">
              <div className="space-y-2">
                {employee.team_memberships_list.map((tm) => (
                  <div
                    key={tm.team_id}
                    className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg"
                  >
                    <div className="flex items-center gap-3">
                      <Users className="h-5 w-5 text-gray-400" />
                      <span className="font-medium">{tm.team_name}</span>
                    </div>
                    <span className="text-sm text-gray-500 capitalize">{tm.role}</span>
                  </div>
                ))}
              </div>
            </InfoSection>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Management Chain */}
          {managementChain?.management_chain?.length > 0 && (
            <InfoSection title="Reports To">
              <div className="space-y-2">
                {managementChain.management_chain.map((manager, index) => (
                  <ReportCard key={manager.id} employee={manager} type="manager" />
                ))}
              </div>
            </InfoSection>
          )}

          {/* Direct Reports */}
          {directReports?.direct_reports?.length > 0 && (
            <InfoSection title={`Direct Reports (${directReports.count})`}>
              <div className="space-y-2">
                {directReports.direct_reports.map((report) => (
                  <ReportCard key={report.id} employee={report} type="report" />
                ))}
              </div>
            </InfoSection>
          )}

          {/* Quick Stats */}
          <InfoSection title="Quick Stats">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-500">Direct Reports</span>
                <span className="font-medium">{employee.direct_reports_count || 0}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-500">Teams</span>
                <span className="font-medium">{employee.team_memberships_list?.length || 0}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-500">Organization Role</span>
                <span className="font-medium capitalize">{employee.org_role}</span>
              </div>
            </div>
          </InfoSection>
        </div>
      </div>

      <EditEmployeeModal
        isOpen={showEditModal}
        onClose={() => setShowEditModal(false)}
        employee={employee}
        orgSlug={currentOrganization?.slug}
      />
    </div>
  )
}
