import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Users, UserPlus, Mail, Shield, Crown, X, Clock, UserMinus, Briefcase } from 'lucide-react'
import { useAdmin } from '../contexts/AdminContext'
import { organizationsApi, userApi, employeesApi } from '../services/api'
import clsx from 'clsx'

const roleColors = {
  owner: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
  admin: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  member: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
}

const roleIcons = {
  owner: Crown,
  admin: Shield,
  member: Users,
}

/**
 * Check if current user can remove a target member.
 *
 * Permission Logic:
 * | Requester | Can Remove | Cannot Remove |
 * |-----------|------------|---------------|
 * | Superuser | Anyone (except last owner) | Last owner |
 * | Owner | Admins, members, viewers | Last owner (self if sole) |
 * | Admin | Members, viewers | Owners, other admins |
 * | Member/Viewer | Nobody | Everyone |
 */
function canRemoveMember(currentUser, currentMembership, targetMember, ownerCount) {
  if (!currentUser) return false

  const targetRole = targetMember.role
  const targetUserId = targetMember.user_id

  // Cannot remove the last owner
  if (targetRole === 'owner' && ownerCount <= 1) {
    return false
  }

  // Superuser can remove anyone (except last owner - already checked)
  if (currentUser.is_superuser) {
    return true
  }

  // No membership means no permission
  if (!currentMembership) {
    return false
  }

  const requesterRole = currentMembership.role

  // Self-removal should use leave (handled separately)
  if (targetUserId && targetUserId === currentUser.id) {
    return false
  }

  // Owners can remove anyone except last owner (already checked)
  if (requesterRole === 'owner') {
    return true
  }

  // Admins can remove members and viewers only
  if (requesterRole === 'admin') {
    return targetRole === 'member' || targetRole === 'viewer'
  }

  // Members and viewers cannot remove anyone
  return false
}

function MemberCard({ member, currentUser, currentMembership, ownerCount, onRemove, hasProfile }) {
  const RoleIcon = roleIcons[member.role] || Users
  const showRemoveButton = canRemoveMember(currentUser, currentMembership, member, ownerCount)
  const isSelf = currentUser && member.user_id === currentUser.id

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5">
      <div className="flex items-start gap-4">
        <div className="w-12 h-12 rounded-full bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center flex-shrink-0">
          <RoleIcon className="h-6 w-6 text-primary-600" />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold truncate">{member.display_name || member.user_email}</h3>
            <span className={clsx('text-xs px-2 py-0.5 rounded capitalize', roleColors[member.role])}>
              {member.role}
            </span>
            {member.is_pending && (
              <span className="text-xs px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 flex items-center gap-1">
                <Clock className="h-3 w-3" />
                Pending
              </span>
            )}
            {isSelf && (
              <span className="text-xs px-2 py-0.5 rounded bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400">
                You
              </span>
            )}
          </div>

          <div className="flex items-center gap-4 mt-2 text-sm text-gray-500">
            <span className="flex items-center gap-1">
              <Mail className="h-3 w-3" />
              <span className="truncate">{member.user_email}</span>
            </span>
          </div>

          <div className="flex items-center gap-2 mt-2">
            {member.accepted_at && (
              <p className="text-xs text-gray-400">
                Joined {new Date(member.accepted_at).toLocaleDateString()}
              </p>
            )}
            {!hasProfile && !member.is_pending && (
              <Link
                to={`/employees?create=${member.id}`}
                className="inline-flex items-center gap-1 text-xs px-2 py-1 text-primary-600 hover:bg-primary-50 dark:hover:bg-primary-900/20 rounded transition-colors"
              >
                <Briefcase className="h-3 w-3" />
                Create Profile
              </Link>
            )}
          </div>
        </div>

        {showRemoveButton && (
          <button
            onClick={() => onRemove(member)}
            className="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
            title={member.is_pending ? 'Cancel invitation' : 'Remove member'}
          >
            <UserMinus className="h-5 w-5" />
          </button>
        )}
      </div>
    </div>
  )
}

function RemoveMemberModal({ isOpen, onClose, member, orgSlug }) {
  const queryClient = useQueryClient()

  const removeMutation = useMutation({
    mutationFn: () => organizationsApi.removeMember(orgSlug, member.id),
    onSuccess: () => {
      queryClient.invalidateQueries(['org-members', orgSlug])
      onClose()
    },
  })

  if (!isOpen || !member) return null

  const isPending = member.is_pending
  const title = isPending ? 'Cancel Invitation' : 'Remove Member'
  const message = isPending
    ? `Are you sure you want to cancel the invitation for ${member.user_email}?`
    : `Are you sure you want to remove ${member.user_email} from this organization?`
  const buttonText = isPending ? 'Cancel Invitation' : 'Remove Member'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-white dark:bg-gray-800 rounded-xl shadow-xl p-6 w-full max-w-md mx-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-red-600">{title}</h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded">
            <X className="h-5 w-5" />
          </button>
        </div>

        <p className="text-gray-600 dark:text-gray-400 mb-6">{message}</p>

        {!isPending && (
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
            This will remove their access to the organization and all associated resources.
          </p>
        )}

        {removeMutation.error && (
          <p className="text-sm text-red-600 mb-4">
            {removeMutation.error.response?.data?.error || 'Failed to remove member'}
          </p>
        )}

        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
          >
            Cancel
          </button>
          <button
            onClick={() => removeMutation.mutate()}
            disabled={removeMutation.isPending}
            className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
          >
            {removeMutation.isPending ? 'Removing...' : buttonText}
          </button>
        </div>
      </div>
    </div>
  )
}

function InviteModal({ isOpen, onClose, orgSlug }) {
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('member')
  const queryClient = useQueryClient()

  const inviteMutation = useMutation({
    mutationFn: (data) => organizationsApi.inviteMember(orgSlug, data),
    onSuccess: () => {
      queryClient.invalidateQueries(['org-members', orgSlug])
      onClose()
      setEmail('')
      setRole('member')
    },
  })

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-white dark:bg-gray-800 rounded-xl shadow-xl p-6 w-full max-w-md mx-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Invite Member</h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={(e) => {
          e.preventDefault()
          inviteMutation.mutate({ user_email: email, role })
        }}>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">Email Address</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                placeholder="user@example.com"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Role</label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              >
                <option value="member">Member</option>
                <option value="admin">Admin</option>
              </select>
            </div>

            {inviteMutation.error && (
              <p className="text-sm text-red-600">
                {inviteMutation.error.response?.data?.error || 'Failed to send invitation'}
              </p>
            )}

            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={inviteMutation.isPending}
                className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
              >
                {inviteMutation.isPending ? 'Sending...' : 'Send Invitation'}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function Members() {
  const { currentOrganization } = useAdmin()
  const [showInviteModal, setShowInviteModal] = useState(false)
  const [memberToRemove, setMemberToRemove] = useState(null)

  // Fetch current user info for permission checks
  const { data: currentUser } = useQuery({
    queryKey: ['current-user'],
    queryFn: () => userApi.me().then(res => res.data),
  })

  const { data, isLoading, error } = useQuery({
    queryKey: ['org-members', currentOrganization?.slug],
    queryFn: () => organizationsApi.members(currentOrganization.slug).then(res => res.data),
    enabled: !!currentOrganization?.slug,
  })

  const { data: employeesData } = useQuery({
    queryKey: ['employees', currentOrganization?.slug],
    queryFn: () => employeesApi.list(currentOrganization.slug).then(res => res.data),
    enabled: !!currentOrganization?.slug,
  })

  const allEmployees = Array.isArray(employeesData) ? employeesData : (employeesData?.results || [])
  const employeeMembershipIds = new Set(allEmployees.map(e => e.membership))

  // Group members by role
  const membersByRole = {
    owner: [],
    admin: [],
    member: [],
  }

  if (data?.members) {
    data.members.forEach(member => {
      if (membersByRole[member.role]) {
        membersByRole[member.role].push(member)
      }
    })
  }

  // Find current user's membership for permission checks
  const currentMembership = data?.members?.find(m => m.user_id === currentUser?.id)
  const ownerCount = membersByRole.owner.length

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Members</h1>
          <p className="text-gray-500 mt-1">
            Manage organization members and their roles
          </p>
        </div>
        {currentOrganization && (
          <button
            onClick={() => setShowInviteModal(true)}
            className="inline-flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
          >
            <UserPlus className="h-5 w-5" />
            Invite Member
          </button>
        )}
      </div>

      {!currentOrganization ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-12 text-center">
          <Users className="h-12 w-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
          <h3 className="text-lg font-medium">Select an organization</h3>
          <p className="text-gray-500 mt-1">
            Members are managed per organization. Choose one from the organization
            switcher at the top to view and manage its members.
          </p>
        </div>
      ) : (
      <>
      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-yellow-100 dark:bg-yellow-900/30 rounded-lg">
              <Crown className="h-5 w-5 text-yellow-600" />
            </div>
            <div>
              <p className="text-2xl font-bold">{membersByRole.owner.length}</p>
              <p className="text-sm text-gray-500">Owners</p>
            </div>
          </div>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-100 dark:bg-purple-900/30 rounded-lg">
              <Shield className="h-5 w-5 text-purple-600" />
            </div>
            <div>
              <p className="text-2xl font-bold">{membersByRole.admin.length}</p>
              <p className="text-sm text-gray-500">Admins</p>
            </div>
          </div>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
              <Users className="h-5 w-5 text-blue-600" />
            </div>
            <div>
              <p className="text-2xl font-bold">{membersByRole.member.length}</p>
              <p className="text-sm text-gray-500">Members</p>
            </div>
          </div>
        </div>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="flex items-center justify-center h-32">
          <p className="text-gray-500">Loading members...</p>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-4 rounded-lg">
          Failed to load members. Please try again.
        </div>
      )}

      {/* Members list */}
      {!isLoading && !error && (
        <div className="space-y-6">
          {/* Owners */}
          {membersByRole.owner.length > 0 && (
            <div>
              <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
                <Crown className="h-5 w-5 text-yellow-600" />
                Owners
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {membersByRole.owner.map(member => (
                  <MemberCard
                    key={member.id}
                    member={member}
                    currentUser={currentUser}
                    currentMembership={currentMembership}
                    ownerCount={ownerCount}
                    onRemove={setMemberToRemove}
                    hasProfile={employeeMembershipIds.has(member.id)}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Admins */}
          {membersByRole.admin.length > 0 && (
            <div>
              <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
                <Shield className="h-5 w-5 text-purple-600" />
                Admins
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {membersByRole.admin.map(member => (
                  <MemberCard
                    key={member.id}
                    member={member}
                    currentUser={currentUser}
                    currentMembership={currentMembership}
                    ownerCount={ownerCount}
                    onRemove={setMemberToRemove}
                    hasProfile={employeeMembershipIds.has(member.id)}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Members */}
          {membersByRole.member.length > 0 && (
            <div>
              <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
                <Users className="h-5 w-5 text-blue-600" />
                Members
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {membersByRole.member.map(member => (
                  <MemberCard
                    key={member.id}
                    member={member}
                    currentUser={currentUser}
                    currentMembership={currentMembership}
                    ownerCount={ownerCount}
                    onRemove={setMemberToRemove}
                    hasProfile={employeeMembershipIds.has(member.id)}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Empty state */}
          {data?.members?.length === 0 && (
            <div className="text-center py-12">
              <Users className="h-12 w-12 text-gray-300 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-gray-700 dark:text-gray-300">No members yet</h3>
              <p className="text-gray-500 mt-1">Invite members to your organization to get started.</p>
            </div>
          )}
        </div>
      )}
      </>
      )}

      {/* Invite Modal */}
      <InviteModal
        isOpen={showInviteModal}
        onClose={() => setShowInviteModal(false)}
        orgSlug={currentOrganization?.slug}
      />

      {/* Remove Member Modal */}
      <RemoveMemberModal
        isOpen={!!memberToRemove}
        onClose={() => setMemberToRemove(null)}
        member={memberToRemove}
        orgSlug={currentOrganization?.slug}
      />
    </div>
  )
}
