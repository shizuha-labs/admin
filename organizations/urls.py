"""
URL configuration for organizations app.

Note: Project routes have been removed. Projects are now managed by shizuha-pulse.
Use /pulse/api/projects/ for project management.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers as nested_routers
from .views import (
    OrganizationViewSet,
    DepartmentViewSet, TeamViewSet, PositionViewSet,
    EmployeeProfileViewSet, OrgChartViewSet,
    CurrentUserView, SuperuserDashboardView, SuperuserUserDetailView,
    SuperuserUserDeletePreviewView, SuperuserUserDeleteView,
    # User CRUD proxy views
    SuperuserUserListView, SuperuserUserCreateView, SuperuserUserUpdateView,
    # Organization management views
    SuperuserOrgListView, SuperuserOrgCreateView, SuperuserOrgUpdateView, SuperuserOrgDetailView,
    # System health
    SuperuserSystemHealthView,
    # Service access management
    SuperuserServiceListView, SuperuserOrgServicesView,
    SuperuserUserServicesProxyView, SuperuserAccessRequestsProxyView,
    SuperuserAccessRequestReviewProxyView,
    # Account approval
    SuperuserPendingUsersProxyView, SuperuserPendingUsersCountProxyView,
    SuperuserUserApprovalProxyView,
    OrgServiceListView, OrgMemberServicesView, AuditorRoleGrantView,
    JITElevatedAccessGrantView, JITElevatedAccessGrantDetailView,
    JITElevatedAccessGrantDecisionView, KubernetesJITConsumeView,
)

# Main router
router = DefaultRouter()
router.register('organizations', OrganizationViewSet, basename='organizations')

# Additional non-viewset URLs
extra_patterns = [
    path('me/', CurrentUserView.as_view(), name='current-user'),
    path('superuser/dashboard/', SuperuserDashboardView.as_view(), name='superuser-dashboard'),
    # User CRUD
    path('superuser/users/', SuperuserUserListView.as_view(), name='superuser-user-list'),
    path('superuser/users/create/', SuperuserUserCreateView.as_view(), name='superuser-user-create'),
    path('superuser/users/<int:user_id>/', SuperuserUserDetailView.as_view(), name='superuser-user-detail'),
    path('superuser/users/<int:user_id>/update/', SuperuserUserUpdateView.as_view(), name='superuser-user-update'),
    path('superuser/users/<int:user_id>/delete-preview/', SuperuserUserDeletePreviewView.as_view(), name='superuser-user-delete-preview'),
    path('superuser/users/<int:user_id>/delete/', SuperuserUserDeleteView.as_view(), name='superuser-user-delete'),
    # Organization management
    path('superuser/organizations/', SuperuserOrgListView.as_view(), name='superuser-org-list'),
    path('superuser/organizations/create/', SuperuserOrgCreateView.as_view(), name='superuser-org-create'),
    path('superuser/organizations/<slug:slug>/update/', SuperuserOrgUpdateView.as_view(), name='superuser-org-update'),
    path('superuser/organizations/<slug:slug>/detail/', SuperuserOrgDetailView.as_view(), name='superuser-org-detail'),
    # System health
    path('superuser/system/health/', SuperuserSystemHealthView.as_view(), name='superuser-system-health'),
    # Service access management (superuser)
    path('superuser/services/', SuperuserServiceListView.as_view(), name='superuser-services'),
    path('superuser/organizations/<slug:slug>/services/', SuperuserOrgServicesView.as_view(), name='superuser-org-services'),
    path('superuser/users/<int:user_id>/services/', SuperuserUserServicesProxyView.as_view(), name='superuser-user-services'),
    path('superuser/requests/', SuperuserAccessRequestsProxyView.as_view(), name='superuser-access-requests'),
    path('superuser/requests/<int:pk>/', SuperuserAccessRequestReviewProxyView.as_view(), name='superuser-access-request-review'),
    # Account approval management (proxied to shizuha-id)
    path('superuser/users/pending/', SuperuserPendingUsersProxyView.as_view(), name='superuser-pending-users'),
    path('superuser/users/pending/count/', SuperuserPendingUsersCountProxyView.as_view(), name='superuser-pending-users-count'),
    path('superuser/users/<int:user_id>/approve/', SuperuserUserApprovalProxyView.as_view(), name='superuser-user-approve'),
    # JIT elevated access (PLAT-1346)
    path('jit-elevations/', JITElevatedAccessGrantView.as_view(), name='jit-elevation-list-create'),
    path('jit-elevations/<int:pk>/',
         JITElevatedAccessGrantDetailView.as_view(),
         name='jit-elevation-detail'),
    path('jit-elevations/<int:pk>/consume-kubernetes/',
         KubernetesJITConsumeView.as_view(),
         name='jit-elevation-consume-kubernetes'),
    path('jit-elevations/<int:pk>/<str:action_name>/',
         JITElevatedAccessGrantDecisionView.as_view(),
         name='jit-elevation-decision'),
    # Organization service management (org admin)
    path('organizations/<slug:slug>/services/', OrgServiceListView.as_view(), name='org-services'),
    path('organizations/<slug:slug>/services/members/', OrgMemberServicesView.as_view(), name='org-member-services'),
    path('organizations/<slug:slug>/services/members/<int:user_id>/', OrgMemberServicesView.as_view(), name='org-member-service-toggle'),
    # Organization member management (explicit routes for actions with URL parameters)
    path('organizations/<slug:slug>/members/<int:member_id>/',
         OrganizationViewSet.as_view({'delete': 'remove_member'}),
         name='organization-remove-member'),
    path('organizations/<slug:slug>/members/<int:user_id>/auditor-role/',
         AuditorRoleGrantView.as_view(), name='organization-auditor-role-grant'),
    path('organizations/<slug:slug>/leave/',
         OrganizationViewSet.as_view({'post': 'leave'}),
         name='organization-leave'),
]

# Nested router for HR hierarchy under organizations
# Creates routes like: /api/organizations/{organization_slug}/departments/
try:
    organizations_router = nested_routers.NestedDefaultRouter(
        router, 'organizations', lookup='organization'
    )
    organizations_router.register('departments', DepartmentViewSet, basename='organization-departments')
    organizations_router.register('teams', TeamViewSet, basename='organization-teams')
    organizations_router.register('positions', PositionViewSet, basename='organization-positions')
    organizations_router.register('employees', EmployeeProfileViewSet, basename='organization-employees')
    organizations_router.register('org-chart', OrgChartViewSet, basename='organization-org-chart')

    urlpatterns = extra_patterns + router.urls + organizations_router.urls
except ImportError:
    # Fallback if drf-nested-routers not installed - use flat routes
    urlpatterns = router.urls + [
        # Departments
        path('organizations/<slug:organization_slug>/departments/',
             DepartmentViewSet.as_view({'get': 'list', 'post': 'create'}),
             name='organization-departments-list'),
        path('organizations/<slug:organization_slug>/departments/<int:pk>/',
             DepartmentViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}),
             name='organization-departments-detail'),
        path('organizations/<slug:organization_slug>/departments/tree/',
             DepartmentViewSet.as_view({'get': 'tree'}),
             name='organization-departments-tree'),
        path('organizations/<slug:organization_slug>/departments/<int:pk>/employees/',
             DepartmentViewSet.as_view({'get': 'employees'}),
             name='organization-departments-employees'),

        # Teams
        path('organizations/<slug:organization_slug>/teams/',
             TeamViewSet.as_view({'get': 'list', 'post': 'create'}),
             name='organization-teams-list'),
        path('organizations/<slug:organization_slug>/teams/<int:pk>/',
             TeamViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}),
             name='organization-teams-detail'),
        path('organizations/<slug:organization_slug>/teams/<int:pk>/members/',
             TeamViewSet.as_view({'get': 'members', 'post': 'members'}),
             name='organization-teams-members'),
        path('organizations/<slug:organization_slug>/teams/<int:pk>/members/<int:member_id>/',
             TeamViewSet.as_view({'delete': 'remove_member'}),
             name='organization-teams-remove-member'),

        # Positions
        path('organizations/<slug:organization_slug>/positions/',
             PositionViewSet.as_view({'get': 'list', 'post': 'create'}),
             name='organization-positions-list'),
        path('organizations/<slug:organization_slug>/positions/<int:pk>/',
             PositionViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}),
             name='organization-positions-detail'),

        # Employees
        path('organizations/<slug:organization_slug>/employees/',
             EmployeeProfileViewSet.as_view({'get': 'list', 'post': 'create'}),
             name='organization-employees-list'),
        path('organizations/<slug:organization_slug>/employees/<int:pk>/',
             EmployeeProfileViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update'}),
             name='organization-employees-detail'),
        path('organizations/<slug:organization_slug>/employees/<int:pk>/direct-reports/',
             EmployeeProfileViewSet.as_view({'get': 'direct_reports'}),
             name='organization-employees-direct-reports'),
        path('organizations/<slug:organization_slug>/employees/<int:pk>/management-chain/',
             EmployeeProfileViewSet.as_view({'get': 'management_chain'}),
             name='organization-employees-management-chain'),

        # Org Chart
        path('organizations/<slug:organization_slug>/org-chart/',
             OrgChartViewSet.as_view({'get': 'list'}),
             name='organization-org-chart'),
        path('organizations/<slug:organization_slug>/org-chart/by-department/',
             OrgChartViewSet.as_view({'get': 'by_department'}),
             name='organization-org-chart-by-department'),
        path('organizations/<slug:organization_slug>/org-chart/stats/',
             OrgChartViewSet.as_view({'get': 'stats'}),
             name='organization-org-chart-stats'),
    ] + extra_patterns
