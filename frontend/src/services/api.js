import axios from 'axios'

// Get API base URL from environment or default
const API_BASE_URL = import.meta.env.VITE_API_URL || '/admin/api'

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Add auth token to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('shizuha_access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Handle auth errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Redirect to login
      window.location.href = '/id/login?continue=/admin/'
    }
    return Promise.reject(error)
  }
)

// Organization API
export const organizationsApi = {
  list: () => api.get('/organizations/'),
  get: (slug) => api.get(`/organizations/${slug}/`),
  create: (data) => api.post('/organizations/', data),
  update: (slug, data) => api.patch(`/organizations/${slug}/`, data),
  members: (slug) => api.get(`/organizations/${slug}/members/`),
  inviteMember: (slug, data) => api.post(`/organizations/${slug}/members/`, data),
  removeMember: (slug, memberId) => api.delete(`/organizations/${slug}/members/${memberId}/`),
  leave: (slug) => api.post(`/organizations/${slug}/leave/`),
}

// Department API
export const departmentsApi = {
  list: (orgSlug) => api.get(`/organizations/${orgSlug}/departments/`),
  get: (orgSlug, id) => api.get(`/organizations/${orgSlug}/departments/${id}/`),
  create: (orgSlug, data) => api.post(`/organizations/${orgSlug}/departments/`, data),
  update: (orgSlug, id, data) => api.patch(`/organizations/${orgSlug}/departments/${id}/`, data),
  delete: (orgSlug, id) => api.delete(`/organizations/${orgSlug}/departments/${id}/`),
  tree: (orgSlug) => api.get(`/organizations/${orgSlug}/departments/tree/`),
  employees: (orgSlug, id) => api.get(`/organizations/${orgSlug}/departments/${id}/employees/`),
}

// Team API
export const teamsApi = {
  list: (orgSlug) => api.get(`/organizations/${orgSlug}/teams/`),
  get: (orgSlug, id) => api.get(`/organizations/${orgSlug}/teams/${id}/`),
  create: (orgSlug, data) => api.post(`/organizations/${orgSlug}/teams/`, data),
  update: (orgSlug, id, data) => api.patch(`/organizations/${orgSlug}/teams/${id}/`, data),
  delete: (orgSlug, id) => api.delete(`/organizations/${orgSlug}/teams/${id}/`),
  members: (orgSlug, id) => api.get(`/organizations/${orgSlug}/teams/${id}/members/`),
  addMember: (orgSlug, id, data) => api.post(`/organizations/${orgSlug}/teams/${id}/members/`, data),
  removeMember: (orgSlug, teamId, memberId) =>
    api.delete(`/organizations/${orgSlug}/teams/${teamId}/members/${memberId}/`),
}

// Position API
export const positionsApi = {
  list: (orgSlug) => api.get(`/organizations/${orgSlug}/positions/`),
  get: (orgSlug, id) => api.get(`/organizations/${orgSlug}/positions/${id}/`),
  create: (orgSlug, data) => api.post(`/organizations/${orgSlug}/positions/`, data),
  update: (orgSlug, id, data) => api.patch(`/organizations/${orgSlug}/positions/${id}/`, data),
  delete: (orgSlug, id) => api.delete(`/organizations/${orgSlug}/positions/${id}/`),
}

// Employee API
export const employeesApi = {
  list: (orgSlug, params = {}) => api.get(`/organizations/${orgSlug}/employees/`, { params }),
  get: (orgSlug, id) => api.get(`/organizations/${orgSlug}/employees/${id}/`),
  create: (orgSlug, data) => api.post(`/organizations/${orgSlug}/employees/`, data),
  update: (orgSlug, id, data) => api.patch(`/organizations/${orgSlug}/employees/${id}/`, data),
  directReports: (orgSlug, id) => api.get(`/organizations/${orgSlug}/employees/${id}/direct-reports/`),
  managementChain: (orgSlug, id) => api.get(`/organizations/${orgSlug}/employees/${id}/management-chain/`),
}

// Org Chart API
export const orgChartApi = {
  get: (orgSlug) => api.get(`/organizations/${orgSlug}/org-chart/`),
  byDepartment: (orgSlug, departmentId) =>
    api.get(`/organizations/${orgSlug}/org-chart/by-department/`, { params: { department_id: departmentId } }),
  stats: (orgSlug) => api.get(`/organizations/${orgSlug}/org-chart/stats/`),
}

// User API
export const userApi = {
  me: () => api.get('/me/'),
}

// Superuser API
export const superuserApi = {
  dashboard: () => api.get('/superuser/dashboard/'),
  // User CRUD
  listUsers: (params) => api.get('/superuser/users/', { params }),
  createUser: (data) => api.post('/superuser/users/create/', data),
  userDetail: (userId) => api.get(`/superuser/users/${userId}/`),
  updateUser: (userId, data) => api.patch(`/superuser/users/${userId}/update/`, data),
  userDeletePreview: (userId) => api.get(`/superuser/users/${userId}/delete-preview/`),
  userDelete: (userId) => api.delete(`/superuser/users/${userId}/delete/`),
  // Organization management
  listOrgs: (params) => api.get('/superuser/organizations/', { params }),
  createOrg: (data) => api.post('/superuser/organizations/create/', data),
  updateOrg: (slug, data) => api.patch(`/superuser/organizations/${slug}/update/`, data),
  orgDetail: (slug) => api.get(`/superuser/organizations/${slug}/detail/`),
  // System health
  systemHealth: () => api.get('/superuser/system/health/'),
  // Account approval
  pendingUsers: (params) => api.get('/superuser/users/pending/', { params }),
  pendingUsersCount: () => api.get('/superuser/users/pending/count/'),
  approveUser: (userId, data) => api.patch(`/superuser/users/${userId}/approve/`, data),
}

// Services API (superuser service management)
export const servicesApi = {
  // Platform-wide service list (superuser)
  list: () => api.get('/superuser/services/'),

  // Organization service management (superuser)
  getOrgServices: (orgSlug) => api.get(`/superuser/organizations/${orgSlug}/services/`),
  updateOrgServices: (orgSlug, data) => api.post(`/superuser/organizations/${orgSlug}/services/`, data),

  // User service management (superuser, proxied to shizuha-id)
  getUserServices: (userId) => api.get(`/superuser/users/${userId}/services/`),
  updateUserServices: (userId, data) => api.post(`/superuser/users/${userId}/services/`, data),

  // Access requests (superuser, proxied to shizuha-id)
  listRequests: (params) => api.get('/superuser/requests/', { params }),
  reviewRequest: (requestId, data) => api.patch(`/superuser/requests/${requestId}/`, data),

  // Org-level service management (org admin)
  getMyOrgServices: (orgSlug) => api.get(`/organizations/${orgSlug}/services/`),
  getOrgMemberServices: (orgSlug) => api.get(`/organizations/${orgSlug}/services/members/`),
  updateMemberServices: (orgSlug, userId, data) =>
    api.post(`/organizations/${orgSlug}/services/members/${userId}/`, data),
}

export default api
