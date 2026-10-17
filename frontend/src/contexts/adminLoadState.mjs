export function requestFailure(error, resource) {
  const status = error?.response?.status
  return {
    resource,
    kind: status === 401 ? 'signed-out' : status === 403 ? 'denied' : 'unavailable',
  }
}

export function organizationRows(response) {
  const data = response.data
  if (Array.isArray(data)) return data
  if (Array.isArray(data?.results)) return data.results
  throw new Error('Invalid organization response')
}

// Independent results must survive a sibling failure. The caller keeps the
// last organization observation on failure instead of inventing an empty list.
export async function loadAdminData(userApi, organizationsApi) {
  const [userResult, orgResult] = await Promise.allSettled([
    Promise.resolve().then(() => userApi.me()),
    Promise.resolve().then(() => organizationsApi.list()).then(organizationRows),
  ])
  return {
    user: userResult.status === 'fulfilled' ? userResult.value.data : null,
    organizations: orgResult.status === 'fulfilled' ? orgResult.value : undefined,
    errors: {
      user: userResult.status === 'rejected' ? requestFailure(userResult.reason, 'profile') : null,
      organizations: orgResult.status === 'rejected' ? requestFailure(orgResult.reason, 'organizations') : null,
    },
  }
}

export function loadingFailure(errors) {
  const failures = Object.values(errors).filter(Boolean)
  return failures.find(error => error.kind === 'signed-out')
    || failures.find(error => error.kind === 'denied') || failures[0] || null
}
