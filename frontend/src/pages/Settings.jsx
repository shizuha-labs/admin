import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Building2, Globe, Mail, CreditCard, Shield, Bell, Blocks, Loader2, Lock } from 'lucide-react'
import { useAdmin } from '../contexts/AdminContext'
import { organizationsApi, servicesApi } from '../services/api'
import clsx from 'clsx'
import { profileFieldsFromOrg, mergeProfileUpdate } from './settingsHydration.mjs'
import { normalizeOrgServices } from './orgServices.mjs'

function SettingsSection({ title, description, icon: Icon, children }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
      <div className="flex items-start gap-4 mb-6">
        <div className="p-2 bg-primary-100 dark:bg-primary-900/30 rounded-lg">
          <Icon className="h-5 w-5 text-primary-600" />
        </div>
        <div>
          <h2 className="text-lg font-semibold">{title}</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400">{description}</p>
        </div>
      </div>
      {children}
    </div>
  )
}

function OrgEnabledServices({ orgSlug }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['org-services', orgSlug],
    queryFn: () => servicesApi.getMyOrgServices(orgSlug).then(res => res.data),
    enabled: !!orgSlug,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-6">
        <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
      </div>
    )
  }

  if (error) {
    return (
      <p className="text-sm text-red-500">Failed to load services.</p>
    )
  }

  const services = normalizeOrgServices(data)
  const enabled = services.filter(s => s.is_enabled)
  const disabled = services.filter(s => !s.is_enabled)

  return (
    <div className="space-y-4">
      {enabled.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            Active Services ({enabled.length})
          </h3>
          <div className="grid grid-cols-2 gap-2">
            {enabled.map((svc) => (
              <div
                key={svc.slug || svc.service_slug}
                className="flex items-center gap-2 p-2.5 bg-green-50 dark:bg-green-900/20 rounded-lg text-sm"
              >
                <span className="w-2 h-2 rounded-full bg-green-500 shrink-0" />
                <span className="text-green-800 dark:text-green-300">{svc.name || svc.slug || svc.service_slug}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {disabled.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            Not Available
          </h3>
          <div className="grid grid-cols-2 gap-2">
            {disabled.map((svc) => (
              <div
                key={svc.slug || svc.service_slug}
                className="flex items-center gap-2 p-2.5 bg-gray-50 dark:bg-gray-700/50 rounded-lg text-sm"
              >
                <Lock className="h-3.5 w-3.5 text-gray-400 shrink-0" />
                <span className="text-gray-500">{svc.name || svc.slug || svc.service_slug}</span>
              </div>
            ))}
          </div>
          <p className="text-xs text-gray-400 mt-2">
            Contact a system administrator to enable additional services.
          </p>
        </div>
      )}

      {services.length === 0 && (
        <p className="text-sm text-gray-500">No service information available.</p>
      )}
    </div>
  )
}

export default function Settings() {
  const { currentOrganization, refreshOrganizations, loading: adminLoading } = useAdmin()
  const queryClient = useQueryClient()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [website, setWebsite] = useState('')
  const [logoUrl, setLogoUrl] = useState('')
  const [billingEmail, setBillingEmail] = useState('')
  // Snapshot of the org we last hydrated the form from — used so save cannot
  // blank a persisted field that never made it into local state (PLAT-5084).
  const [hydratedOrg, setHydratedOrg] = useState(null)

  // Depend on the same server fields we hydrate, not object identity: an
  // unrelated organization refresh must not overwrite an in-progress edit.
  const {
    slug: organizationSlug, name: organizationName, description: organizationDescription,
    website: organizationWebsite, logo_url: organizationLogo, billing_email: organizationBillingEmail,
  } = currentOrganization || {}

  // Re-hydrate whenever the selected org changes or its server fields arrive.
  // useState(initial) alone only runs on first mount, when currentOrganization
  // is still null — leaving Name empty after the org list loads.
  useEffect(() => {
    if (!organizationSlug) {
      setHydratedOrg(null)
      setName('')
      setDescription('')
      setWebsite('')
      setLogoUrl('')
      setBillingEmail('')
      return
    }
    const snapshot = {
      slug: organizationSlug, name: organizationName, description: organizationDescription,
      website: organizationWebsite, logo_url: organizationLogo, billing_email: organizationBillingEmail,
    }
    const fields = profileFieldsFromOrg(snapshot)
    setName(fields.name)
    setDescription(fields.description)
    setWebsite(fields.website)
    setLogoUrl(fields.logoUrl)
    setBillingEmail(fields.billingEmail)
    setHydratedOrg(snapshot)
  }, [
    organizationSlug, organizationName, organizationDescription,
    organizationWebsite, organizationLogo, organizationBillingEmail,
  ])

  const updateMutation = useMutation({
    mutationFn: (data) => organizationsApi.update(currentOrganization.slug, data),
    onSuccess: () => {
      queryClient.invalidateQueries(['organizations'])
      refreshOrganizations()
    },
  })
  const updateMutationBusy = Boolean(
    updateMutation.isPending || updateMutation.isLoading,
  )

  const profileHydrated = Boolean(
    hydratedOrg?.slug && hydratedOrg.slug === currentOrganization?.slug,
  )
  // If the server has a name, the form must show it before save is enabled.
  const nameReady = !hydratedOrg?.name || Boolean(name)
  const canSaveProfile = profileHydrated && nameReady && !updateMutationBusy

  const handleSaveProfile = (e) => {
    e.preventDefault()
    if (!canSaveProfile) return
    updateMutation.mutate(
      mergeProfileUpdate(hydratedOrg, { name, description, website, logoUrl }),
    )
  }

  const handleSaveBilling = (e) => {
    e.preventDefault()
    if (!profileHydrated) return
    updateMutation.mutate({
      billing_email: billingEmail || null,
    })
  }

  if (adminLoading && !currentOrganization) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    )
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-bold">Organization Settings</h1>
        <p className="text-gray-500 dark:text-gray-400">
          Manage settings for {currentOrganization?.name || '…'}
        </p>
      </div>

      {/* Organization Profile */}
      <SettingsSection
        title="Organization Profile"
        description="Basic information about your organization"
        icon={Building2}
      >
        <form onSubmit={handleSaveProfile} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">Organization Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={!profileHydrated}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500 disabled:opacity-60"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Slug</label>
            <input
              type="text"
              value={currentOrganization?.slug || ''}
              disabled
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-gray-100 dark:bg-gray-600 text-gray-500"
            />
            <p className="text-xs text-gray-500 mt-1">Slug cannot be changed after creation</p>
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

          <div>
            <label className="block text-sm font-medium mb-1">Website</label>
            <div className="flex items-center">
              <span className="px-3 py-2 bg-gray-100 dark:bg-gray-600 border border-r-0 border-gray-300 dark:border-gray-600 rounded-l-lg text-gray-500">
                <Globe className="h-4 w-4" />
              </span>
              <input
                type="url"
                value={website}
                onChange={(e) => setWebsite(e.target.value)}
                placeholder="https://example.com"
                className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-r-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Logo URL</label>
            <input
              type="url"
              value={logoUrl}
              onChange={(e) => setLogoUrl(e.target.value)}
              placeholder="https://example.com/logo.png"
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
            />
          </div>

          <div className="flex justify-end pt-4">
            <button
              type="submit"
              disabled={!canSaveProfile}
              className="px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 disabled:opacity-50"
            >
              {updateMutationBusy ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
          {!profileHydrated && (
            <p className="text-xs text-gray-500">Loading organization profile…</p>
          )}
        </form>
      </SettingsSection>

      {/* Billing */}
      <SettingsSection
        title="Billing"
        description="Billing contact and subscription information"
        icon={CreditCard}
      >
        <form onSubmit={handleSaveBilling} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">Current Plan</label>
            <div className="flex items-center gap-3">
              <span className={clsx(
                'px-3 py-1 rounded-full text-sm font-medium capitalize',
                currentOrganization?.plan === 'enterprise' && 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
                currentOrganization?.plan === 'business' && 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
                currentOrganization?.plan === 'team' && 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
                currentOrganization?.plan === 'free' && 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
              )}>
                {currentOrganization?.plan || 'free'}
              </span>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Billing Email</label>
            <div className="flex items-center">
              <span className="px-3 py-2 bg-gray-100 dark:bg-gray-600 border border-r-0 border-gray-300 dark:border-gray-600 rounded-l-lg text-gray-500">
                <Mail className="h-4 w-4" />
              </span>
              <input
                type="email"
                value={billingEmail}
                onChange={(e) => setBillingEmail(e.target.value)}
                placeholder="billing@example.com"
                className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-r-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500"
              />
            </div>
          </div>

          <div className="flex justify-end pt-4">
            <button
              type="submit"
              disabled={updateMutation.isPending}
              className="px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 disabled:opacity-50"
            >
              {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </form>
      </SettingsSection>

      {/* Enabled Services */}
      <SettingsSection
        title="Enabled Services"
        description="Services available to members of this organization"
        icon={Blocks}
      >
        <OrgEnabledServices orgSlug={currentOrganization?.slug} />
      </SettingsSection>

      {/* Notifications */}
      <SettingsSection
        title="Notifications"
        description="Configure organization notification preferences"
        icon={Bell}
      >
        <div className="space-y-4">
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Notification settings will be available in future updates.
          </p>

          <div className="space-y-3">
            <label className="flex items-center justify-between cursor-pointer">
              <span>Email notifications for new members</span>
              <input type="checkbox" defaultChecked className="w-4 h-4 text-primary-600 rounded" disabled />
            </label>
            <label className="flex items-center justify-between cursor-pointer">
              <span>Weekly organization summary</span>
              <input type="checkbox" className="w-4 h-4 text-primary-600 rounded" disabled />
            </label>
            <label className="flex items-center justify-between cursor-pointer">
              <span>Department changes alerts</span>
              <input type="checkbox" defaultChecked className="w-4 h-4 text-primary-600 rounded" disabled />
            </label>
          </div>
        </div>
      </SettingsSection>

      {/* Danger Zone */}
      <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl p-6">
        <h2 className="text-lg font-semibold text-red-700 dark:text-red-400 mb-2">Danger Zone</h2>
        <p className="text-sm text-red-600 dark:text-red-400 mb-4">
          Irreversible actions. Please be careful.
        </p>
        <button
          onClick={() => alert('Organization deletion is not available in this version')}
          className="px-4 py-2 bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 rounded-lg hover:bg-red-200 dark:hover:bg-red-900/50"
        >
          Delete Organization
        </button>
      </div>
    </div>
  )
}
