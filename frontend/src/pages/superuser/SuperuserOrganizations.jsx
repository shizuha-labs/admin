import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import {
  Building2, Users, Search, Plus, X, Loader2, ExternalLink, ChevronLeft, ChevronRight,
} from 'lucide-react'
import { superuserApi } from '../../services/api'
import { useAdmin } from '../../contexts/AdminContext'
import clsx from 'clsx'

const planColors = {
  free: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400',
  team: 'bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400',
  business: 'bg-purple-100 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400',
  enterprise: 'bg-yellow-100 text-yellow-600 dark:bg-yellow-900/30 dark:text-yellow-400',
}

function slugify(text) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
}

function CreateOrgModal({ onClose }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    name: '',
    slug: '',
    owner_id: '',
    plan: 'free',
    description: '',
  })
  const [autoSlug, setAutoSlug] = useState(true)
  const [error, setError] = useState(null)

  const createMutation = useMutation({
    mutationFn: (data) => superuserApi.createOrg({ ...data, owner_id: parseInt(data.owner_id) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['superuser-orgs'] })
      onClose()
    },
    onError: (err) => {
      setError(err.response?.data?.error || 'Failed to create organization')
    },
  })

  const handleNameChange = (name) => {
    setForm({ ...form, name, ...(autoSlug ? { slug: slugify(name) } : {}) })
  }

  const handleSlugChange = (slug) => {
    setAutoSlug(false)
    setForm({ ...form, slug })
  }

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
          <h2 className="text-lg font-semibold">Create Organization</h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">Name *</label>
            <input
              type="text"
              required
              value={form.name}
              onChange={(e) => handleNameChange(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500"
              placeholder="Acme Inc."
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Slug *</label>
            <input
              type="text"
              required
              value={form.slug}
              onChange={(e) => handleSlugChange(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono"
              placeholder="acme-inc"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Owner User ID *</label>
            <input
              type="number"
              required
              value={form.owner_id}
              onChange={(e) => setForm({ ...form, owner_id: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500"
              placeholder="1"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Plan</label>
            <select
              value={form.plan}
              onChange={(e) => setForm({ ...form, plan: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700"
            >
              <option value="free">Free</option>
              <option value="team">Team</option>
              <option value="business">Business</option>
              <option value="enterprise">Enterprise</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Description</label>
            <textarea
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              rows={2}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>

          {error && (
            <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-3 rounded-lg text-sm">{error}</div>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg">
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
                <><Plus className="h-4 w-4" /> Create Organization</>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function SuperuserOrganizations() {
  const { isSuperuser } = useAdmin()
  const [searchParams, setSearchParams] = useSearchParams()
  const [showCreate, setShowCreate] = useState(false)

  const search = searchParams.get('search') || ''
  const page = parseInt(searchParams.get('page') || '1')
  const limit = 25
  const [searchInput, setSearchInput] = useState(search)

  const queryParams = useMemo(() => {
    const params = { limit, offset: (page - 1) * limit }
    if (search) params.search = search
    return params
  }, [search, page])

  const { data, isLoading } = useQuery({
    queryKey: ['superuser-orgs', queryParams],
    queryFn: () => superuserApi.listOrgs(queryParams).then(res => res.data),
  })

  const orgs = data?.results || []
  const total = data?.count || orgs.length
  const totalPages = Math.ceil(total / limit)

  const handleSearch = (e) => {
    e.preventDefault()
    const params = Object.fromEntries(searchParams)
    if (searchInput) params.search = searchInput
    else delete params.search
    params.page = '1'
    setSearchParams(params)
  }

  return (
    <div className="space-y-4">
      {showCreate && <CreateOrgModal onClose={() => setShowCreate(false)} />}

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        <form onSubmit={handleSearch} className="flex-1 min-w-[240px] relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search organizations by name or slug..."
            className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        </form>

        {isSuperuser && (
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg flex items-center gap-2 text-sm"
          >
            <Plus className="h-4 w-4" />
            Create Organization
          </button>
        )}
      </div>

      {/* Organizations List */}
      {isLoading ? (
        <div className="flex items-center justify-center h-32">
          <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
        </div>
      ) : orgs.length > 0 ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
          <div className="divide-y divide-gray-100 dark:divide-gray-700/50">
            {orgs.map((org) => (
              <Link
                key={org.id}
                to={`/superuser/organizations/${org.slug}`}
                className="flex items-center justify-between px-4 py-4 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center">
                    <Building2 className="h-5 w-5 text-primary-600" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{org.name}</span>
                      <span className={clsx('text-xs px-2 py-0.5 rounded capitalize', planColors[org.plan])}>{org.plan}</span>
                    </div>
                    <p className="text-sm text-gray-500">/{org.slug}</p>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-1 text-sm text-gray-500">
                    <Users className="h-4 w-4" />
                    {org.member_count}
                  </div>
                  <div className="text-right text-xs text-gray-500">
                    {org.created_at && new Date(org.created_at).toLocaleDateString()}
                  </div>
                  <ExternalLink className="h-4 w-4 text-gray-400" />
                </div>
              </Link>
            ))}
          </div>

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
          <Building2 className="h-12 w-12 text-gray-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium">No organizations found</h3>
          <p className="text-gray-500 mt-1">
            {search ? 'Try adjusting your search.' : 'Organizations will appear here once created.'}
          </p>
        </div>
      )}
    </div>
  )
}
