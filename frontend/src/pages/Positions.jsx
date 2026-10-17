import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Briefcase, Plus, Edit2, Trash2, X, Users } from 'lucide-react'
import { useAdmin } from '../contexts/AdminContext'
import { positionsApi, departmentsApi } from '../services/api'
import clsx from 'clsx'

function PositionCard({ position, onEdit, onDelete }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center">
            <Briefcase className="h-5 w-5 text-primary-600" />
          </div>
          <div>
            <h3 className="font-semibold">{position.title}</h3>
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <span>Level {position.level}</span>
              {position.pay_grade && (
                <>
                  <span>•</span>
                  <span>{position.pay_grade}</span>
                </>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => onEdit(position)}
            className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
            title="Edit"
          >
            <Edit2 className="h-4 w-4" />
          </button>
          <button
            onClick={() => onDelete(position)}
            className="p-1 hover:bg-red-100 dark:hover:bg-red-900/30 rounded text-red-500"
            title="Delete"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {position.description && (
        <p className="text-sm text-gray-600 dark:text-gray-400 mt-3 line-clamp-2">
          {position.description}
        </p>
      )}

      <div className="flex items-center justify-between mt-4 pt-3 border-t border-gray-100 dark:border-gray-700 text-sm text-gray-500">
        <div className="flex items-center gap-1">
          <Users className="h-4 w-4" />
          <span>{position.employee_count || 0} employees</span>
        </div>
        {position.department_name && (
          <span className="truncate">{position.department_name}</span>
        )}
      </div>

      {position.code && (
        <div className="mt-2">
          <span className="text-xs px-2 py-0.5 bg-gray-100 dark:bg-gray-700 rounded">
            {position.code}
          </span>
        </div>
      )}
    </div>
  )
}

function PositionForm({ position, departments, onSave, onCancel }) {
  const [title, setTitle] = useState(position?.title || '')
  const [code, setCode] = useState(position?.code || '')
  const [description, setDescription] = useState(position?.description || '')
  const [departmentId, setDepartmentId] = useState(position?.department || '')
  const [level, setLevel] = useState(position?.level || 1)
  const [payGrade, setPayGrade] = useState(position?.pay_grade || '')

  const handleSubmit = (e) => {
    e.preventDefault()
    onSave({
      title,
      code: code || null,
      description,
      department: departmentId || null,
      level,
      pay_grade: payGrade || null,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium mb-1">Position Title *</label>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g., Software Engineer"
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
          required
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium mb-1">Position Code</label>
          <input
            type="text"
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            placeholder="e.g., SWE-L3"
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Level</label>
          <input
            type="number"
            value={level}
            onChange={(e) => setLevel(parseInt(e.target.value) || 1)}
            min={1}
            max={20}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
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
          <label className="block text-sm font-medium mb-1">Pay Grade</label>
          <input
            type="text"
            value={payGrade}
            onChange={(e) => setPayGrade(e.target.value)}
            placeholder="e.g., Band 4"
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
          placeholder="Job description and responsibilities..."
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
          {position ? 'Update' : 'Create'} Position
        </button>
      </div>
    </form>
  )
}

export default function Positions() {
  const { currentOrganization } = useAdmin()
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [editingPosition, setEditingPosition] = useState(null)
  const [deleteConfirm, setDeleteConfirm] = useState(null)

  const { data: positionsData, isLoading } = useQuery({
    queryKey: ['positions', currentOrganization?.slug],
    queryFn: () => positionsApi.list(currentOrganization.slug).then(res => res.data),
    enabled: !!currentOrganization?.slug,
  })

  const { data: departmentsData } = useQuery({
    queryKey: ['departments', currentOrganization?.slug],
    queryFn: () => departmentsApi.list(currentOrganization.slug).then(res => res.data),
    enabled: !!currentOrganization?.slug,
  })

  // Handle paginated response - API returns { results: [...] } or direct array
  const positions = Array.isArray(positionsData) ? positionsData : (positionsData?.results || [])
  const departments = Array.isArray(departmentsData) ? departmentsData : (departmentsData?.results || [])

  const createMutation = useMutation({
    mutationFn: (data) => positionsApi.create(currentOrganization.slug, data),
    onSuccess: () => {
      queryClient.invalidateQueries(['positions', currentOrganization.slug])
      setShowForm(false)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }) => positionsApi.update(currentOrganization.slug, id, data),
    onSuccess: () => {
      queryClient.invalidateQueries(['positions', currentOrganization.slug])
      setEditingPosition(null)
      setShowForm(false)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => positionsApi.delete(currentOrganization.slug, id),
    onSuccess: () => {
      queryClient.invalidateQueries(['positions', currentOrganization.slug])
      setDeleteConfirm(null)
    },
  })

  const handleSave = (data) => {
    if (editingPosition) {
      updateMutation.mutate({ id: editingPosition.id, data })
    } else {
      createMutation.mutate(data)
    }
  }

  // Group positions by level
  const positionsByLevel = positions?.reduce((acc, pos) => {
    const level = pos.level || 1
    if (!acc[level]) acc[level] = []
    acc[level].push(pos)
    return acc
  }, {}) || {}

  const sortedLevels = Object.keys(positionsByLevel).sort((a, b) => Number(b) - Number(a))

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Positions</h1>
          <p className="text-gray-500 dark:text-gray-400">
            Job title catalog and position management (stub for future phases)
          </p>
        </div>
        <button
          onClick={() => {
            setEditingPosition(null)
            setShowForm(true)
          }}
          className="flex items-center gap-2 px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600"
        >
          <Plus className="h-4 w-4" />
          Add Position
        </button>
      </div>

      {/* Info Banner */}
      <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
        <p className="text-sm text-blue-700 dark:text-blue-300">
          <strong>Note:</strong> Position management is currently in stub phase. Full features including pay grade integration,
          required skills, and qualifications will be available in future updates.
        </p>
      </div>

      {/* Positions by Level */}
      {isLoading ? (
        <p className="text-gray-500">Loading positions...</p>
      ) : positions?.length > 0 ? (
        <div className="space-y-6">
          {sortedLevels.map((level) => (
            <div key={level}>
              <h2 className="text-lg font-semibold mb-3">Level {level}</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {positionsByLevel[level].map((position) => (
                  <PositionCard
                    key={position.id}
                    position={position}
                    onEdit={(p) => {
                      setEditingPosition(p)
                      setShowForm(true)
                    }}
                    onDelete={(p) => setDeleteConfirm(p)}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-12 text-center">
          <Briefcase className="h-12 w-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
          <h3 className="text-lg font-medium">No positions yet</h3>
          <p className="text-gray-500 mt-1">Create position templates for your organization</p>
          <button
            onClick={() => setShowForm(true)}
            className="mt-4 px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600"
          >
            Create Position
          </button>
        </div>
      )}

      {/* Form Modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-bold">
                {editingPosition ? 'Edit Position' : 'New Position'}
              </h2>
              <button
                onClick={() => {
                  setShowForm(false)
                  setEditingPosition(null)
                }}
                className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <PositionForm
              position={editingPosition}
              departments={departments}
              onSave={handleSave}
              onCancel={() => {
                setShowForm(false)
                setEditingPosition(null)
              }}
            />
          </div>
        </div>
      )}

      {/* Delete Confirmation */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-sm mx-4 p-6">
            <h2 className="text-xl font-bold mb-2">Delete Position</h2>
            <p className="text-gray-600 dark:text-gray-400 mb-4">
              Are you sure you want to delete <strong>{deleteConfirm.title}</strong>?
            </p>
            {deleteMutation.isError && (
              <p className="text-red-500 text-sm mb-4">
                {deleteMutation.error?.response?.data?.error || 'Failed to delete position'}
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
