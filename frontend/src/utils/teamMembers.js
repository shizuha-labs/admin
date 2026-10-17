// Routing identities are read-only. Only concrete Admin directory edges have
// a delete endpoint; a routing row's null ID must never reach that endpoint.
export function isDirectoryMember(member) {
  return member.source === 'admin-directory' && member.routing_member === false && Number.isInteger(member.id) && member.id > 0
}

export function groupTeamMembers(members) {
  const people = new Map()
  for (const [index, member] of members.entries()) {
    // A profile ID is stronger than a display name or email alias. Do not merge
    // different profiles just because their visible names happen to match.
    const email = (member.employee_email || '').trim().toLowerCase()
    const key = member.employee_profile != null ? `profile:${member.employee_profile}` : email ? `email:${email}` : `row:${index}`
    if (!people.has(key)) people.set(key, {
      key, name: member.employee_name || email || 'Unnamed member', email,
      title: member.employee_title || '', routing: [], directory: [], other: [],
    })
    const person = people.get(key)
    if (member.routing_member === true) person.routing.push(member)
    else if (isDirectoryMember(member)) person.directory.push(member)
    else person.other.push(member)
  }
  return [...people.values()]
}
