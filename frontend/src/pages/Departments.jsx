import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Building2, Plus, ChevronRight, ChevronDown, Users, Edit2, Trash2, X
} from 'lucide-react'
import { useAdmin } from '../contexts/AdminContext'
import { departmentsApi } from '../services/api'
import clsx from 'clsx'

function DepartmentNode({ department, level = 0, onEdit, onDelete }) {
  const [expanded, setExpanded] = useState(true)
  const hasChildren = department.children?.length > 0

  return (
    <div className={clsx(
      level > 0 && 'border-l-2 border-gray-200 dark:border-gray-700 ml-4'
    )}>
      <div
        className={clsx(
          'flex items-center gap-2 py-2 px-3 hover:bg-gray-50 dark:hover:bg-gray-700/50 rounded-lg group',
          level > 0 && 'ml-4'
        )}
      >
        {hasChildren ? (
          <button
            onClick={() => setExpanded(!expanded)}
            className="p-1 hover:bg-gray-200 dark:hover:bg-gray-600 rounded"
          >
            {expanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>
        ) : (
          <div className="w-6" />
        )}

        <Building2 className="h-5 w-5 text-primary-500" />

        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium">{department.name}</span>
            {department.code && (
              <span className="text-xs px-2 py-0.5 bg-gray-100 dark:bg-gray-700 rounded">
                {department.code}
              </span>
            )}
          </div>
          {department.head_name && (
            <p className="text-sm text-gray-500">Head: {department.head_name}</p>
          )}
        </div>

        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Users className="h-4 w-4" />
          <span>{department.member_count || 0}</span>
        </div>

        <div className="opacity-0 group-hover:opacity-100 flex items-center gap-1">
          <button
            onClick={() => onEdit(department)}
            className="p-1 hover:bg-gray-200 dark:hover:bg-gray-600 rounded"
            title="Edit"
          >
            <Edit2 className="h-4 w-4" />
          </button>
          <button
            onClick={() => onDelete(department)}
            className="p-1 hover:bg-red-100 dark:hover:bg-red-900/30 rounded text-red-500"
            title="Delete"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {expanded && hasChildren && (
        <div className="ml-2">
          {department.children.map((child) => (
            <DepartmentNode
              key={child.id}
              department={child}
              level={level + 1}
              onEdit={onEdit}
              onDelete={onDelete}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function DepartmentForm({ department, departments, onSave, onCancel }) {
  const [name, setName] = useState(department?.name || '')
  const [code, setCode] = useState(department?.code || '')
  const [description, setDescription] = useState(department?.description || '')
  const [parentId, setParentId] = useState(department?.parent || '')
  const [headEmail, setHeadEmail] = useState(department?.head_email || '')

  const handleSubmit = (e) => {
    e.preventDefault()
    onSave({
      name,
      code,
      description,
      parent: parentId || null,
      head_email: headEmail || null,
    })
  }

  // Build flat list of departments for parent selection
  const flatDepartments = []
  const flatten = (deps, prefix = '') => {
    deps.forEach((d) => {
      if (d.id !== department?.id) { // Exclude current department
        flatDepartments.push({ id: d.id, name: prefix + d.name })
        if (d.children) flatten(d.children, prefix + '  ')
      }
    })
  }
  flatten(departments || [])

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium mb-1">Department Name *</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
          required
        />
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">Code</label>
        <input
          type="text"
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          placeholder="e.g., ENG, HR"
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
        />
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">Parent Department</label>
        <select
          value={parentId}
          onChange={(e) => setParentId(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
        >
          <option value="">None (Root Department)</option>
          {flatDepartments.map((d) => (
            <option key={d.id} value={d.id}>{d.name}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">Department Head Email</label>
        <input
          type="email"
          value={headEmail}
          onChange={(e) => setHeadEmail(e.target.value)}
          placeholder="head@example.com"
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
        />
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
          {department ? 'Update' : 'Create'} Department
        </button>
      </div>
    </form>
  )
}

export default function Departments() {
  const { currentOrganization } = useAdmin()
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [editingDepartment, setEditingDepartment] = useState(null)
  const [deleteConfirm, setDeleteConfirm] = useState(null)

  const { data: treeData, isLoading } = useQuery({
    queryKey: ['departments-tree', currentOrganization?.slug],
    queryFn: () => departmentsApi.tree(currentOrganization.slug).then(res => res.data),
    enabled: !!currentOrganization?.slug,
  })

  const createMutation = useMutation({
    mutationFn: (data) => departmentsApi.create(currentOrganization.slug, data),
    onSuccess: () => {
      queryClient.invalidateQueries(['departments-tree', currentOrganization.slug])
      setShowForm(false)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }) => departmentsApi.update(currentOrganization.slug, id, data),
    onSuccess: () => {
      queryClient.invalidateQueries(['departments-tree', currentOrganization.slug])
      setEditingDepartment(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => departmentsApi.delete(currentOrganization.slug, id),
    onSuccess: () => {
      queryClient.invalidateQueries(['departments-tree', currentOrganization.slug])
      setDeleteConfirm(null)
    },
  })

  const handleSave = (data) => {
    if (editingDepartment) {
      updateMutation.mutate({ id: editingDepartment.id, data })
    } else {
      createMutation.mutate(data)
    }
  }

  const handleEdit = (dept) => {
    setEditingDepartment(dept)
    setShowForm(true)
  }

  const handleDelete = (dept) => {
    setDeleteConfirm(dept)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Departments</h1>
          <p className="text-gray-500 dark:text-gray-400">
            Manage organization hierarchy and departments
          </p>
        </div>
        <button
          onClick={() => {
            setEditingDepartment(null)
            setShowForm(true)
          }}
          className="flex items-center gap-2 px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600"
        >
          <Plus className="h-4 w-4" />
          Add Department
        </button>
      </div>

      {/* Department Tree */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
        {isLoading ? (
          <p className="text-gray-500">Loading departments...</p>
        ) : treeData?.departments?.length > 0 ? (
          <div className="space-y-2">
            {treeData.departments.map((dept) => (
              <DepartmentNode
                key={dept.id}
                department={dept}
                onEdit={handleEdit}
                onDelete={handleDelete}
              />
            ))}
          </div>
        ) : (
          <div className="text-center py-12">
            <Building2 className="h-12 w-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 dark:text-gray-100">No departments yet</h3>
            <p className="text-gray-500 dark:text-gray-400 mt-1">
              Get started by creating your first department
            </p>
            <button
              onClick={() => setShowForm(true)}
              className="mt-4 px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600"
            >
              Create Department
            </button>
          </div>
        )}
      </div>

      {/* Form Modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-bold">
                {editingDepartment ? 'Edit Department' : 'New Department'}
              </h2>
              <button
                onClick={() => {
                  setShowForm(false)
                  setEditingDepartment(null)
                }}
                className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <DepartmentForm
              department={editingDepartment}
              departments={treeData?.departments || []}
              onSave={handleSave}
              onCancel={() => {
                setShowForm(false)
                setEditingDepartment(null)
              }}
            />
          </div>
        </div>
      )}

      {/* Delete Confirmation */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-sm mx-4 p-6">
            <h2 className="text-xl font-bold mb-2">Delete Department</h2>
            <p className="text-gray-600 dark:text-gray-400 mb-4">
              Are you sure you want to delete <strong>{deleteConfirm.name}</strong>? This action cannot be undone.
            </p>
            {deleteMutation.isError && (
              <p className="text-red-500 text-sm mb-4">
                {deleteMutation.error?.response?.data?.error || 'Failed to delete department'}
              </p>
            )}
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
