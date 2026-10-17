# DESIGN.md - Shizuha Admin

Current architecture and implementation of the Admin (Organization Management) service with HR hierarchy support.

## Tech Stack

- **Backend**: Django 4.2+ + DRF 3.14+ + PostgreSQL + Redis
- **Frontend**: React 18 + Vite 5 + TanStack Query + Tailwind CSS
- **Authentication**: Federated JWT via Shizuha ID
- **Org Chart**: react-organizational-chart for hierarchy visualization

## Project Structure

```
shizuha-admin/
├── shizuha_admin/         # Django project settings
├── organizations/         # Main Django app
│   ├── models.py          # Organization, Membership, Department, Team, etc.
│   ├── views.py           # REST API endpoints
│   ├── serializers.py     # DRF serializers
│   ├── permissions.py     # Permission checking
│   └── services/          # Business logic
├── frontend/              # React frontend (NEW)
│   ├── src/
│   │   ├── pages/         # Dashboard, Departments, Teams, Employees, OrgChart
│   │   ├── components/    # Reusable UI components
│   │   └── contexts/      # AdminContext for state
│   └── package.json
└── docker-compose.yml
```

## Data Models

### Organization

- **Organization**: Multi-tenant top-level container
  - `name`: Organization name
  - `slug`: URL-friendly identifier
  - `owner`: Primary owner (User FK)
  - `plan`: Billing plan (free, team, business, enterprise)
  - `logo`: Branding image
  - `settings`: JSON field for configuration

### Membership

- **OrganizationMembership**: User-Organization relationship
  - `user`: User FK
  - `organization`: Organization FK
  - `role`: owner, admin, member, viewer
  - `is_pending`: Invitation not yet accepted
  - `invited_by`: User who sent invitation
  - `invited_at`: Invitation timestamp
  - `accepted_at`: Acceptance timestamp

### HR Hierarchy Models (NEW)

- **Department**: Hierarchical org units
  - `name`, `code`: Identity
  - `parent`: Self-referential FK for nested hierarchy
  - `head_id`, `head_email`: Department head
  - `cost_center_code`, `budget`: Financial tracking
  - Methods: `get_ancestors()`, `get_descendants()`, `get_full_path()`

- **Team**: Cross-functional groups
  - `name`, `description`, `team_type`: permanent/project/task_force/committee
  - `lead_id`, `lead_email`: Team lead
  - `department`: Optional department association
  - `project`: Optional project linkage
  - `start_date`, `end_date`: For project-based teams

- **Position**: Job title catalog (stub for future)
  - `title`, `code`, `description`
  - `level`: Job grade (1=entry, higher=senior)
  - `pay_grade`: Pay band
  - `required_skills`, `qualifications`: JSON fields

- **EmployeeProfile**: Extended employee info (OneToOne with Membership)
  - `position`, `job_title`, `department`: Role info (department + manager required)
  - `employment_status`: active/on_leave/probation/suspended/terminated/resigned
  - `employment_type`: full_time/part_time/contractor/intern/consultant/temporary
  - `manager_id`, `manager_email`: Direct manager (required)
  - `dotted_line_manager_id`: For matrix organizations
  - `work_phone`, `work_email`, `office_location`, `timezone`: Contact
  - `employee_id`, `bio`, `avatar_url`: Profile
  - Methods: `get_direct_reports()`, `get_management_chain()`

- **TeamMembership**: Many-to-many team members
  - `team`, `employee_profile`: Relationship
  - `role`: lead/member/advisor

## API Endpoints

### Core Organization Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET/POST /api/organizations/` | Organization list/create |
| `GET/PATCH /api/organizations/{slug}/` | Organization detail/update |
| `GET/POST /api/organizations/{slug}/members/` | Member management |
| `GET/POST /api/projects/` | Project list/create |
| `GET/PATCH /api/projects/{id}/` | Project detail/update |

### HR Hierarchy Endpoints (NEW)

| Endpoint | Description |
|----------|-------------|
| `GET/POST /api/organizations/{slug}/departments/` | Department list/create |
| `GET/PUT/DELETE /api/organizations/{slug}/departments/{id}/` | Department CRUD |
| `GET /api/organizations/{slug}/departments/tree/` | Hierarchical tree |
| `GET /api/organizations/{slug}/departments/{id}/employees/` | Dept employees |
| `GET/POST /api/organizations/{slug}/teams/` | Team list/create |
| `GET/PUT/DELETE /api/organizations/{slug}/teams/{id}/` | Team CRUD |
| `GET/POST /api/organizations/{slug}/teams/{id}/members/` | Team members |
| `GET/POST /api/organizations/{slug}/positions/` | Position catalog |
| `GET /api/organizations/{slug}/employees/` | Employee directory (filterable) |
| `GET/PUT /api/organizations/{slug}/employees/{id}/` | Employee profile |
| `GET /api/organizations/{slug}/employees/{id}/direct-reports/` | Direct reports |
| `GET /api/organizations/{slug}/employees/{id}/management-chain/` | Manager chain |
| `GET /api/organizations/{slug}/org-chart/` | Full org chart data |
| `GET /api/organizations/{slug}/org-chart/stats/` | Organization stats |

## Role Permissions

| Role | Create | Read | Update | Delete | Manage Members |
|------|--------|------|--------|--------|----------------|
| Owner | ✓ | ✓ | ✓ | ✓ | ✓ |
| Admin | - | ✓ | ✓ | - | ✓ |
| Member | - | ✓ | - | - | - |
| Viewer | - | ✓ | - | - | - |

## Billing Plans

| Plan | Features |
|------|----------|
| Free | 1 org, 5 members, basic features |
| Team | 3 orgs, 25 members, all features |
| Business | 10 orgs, 100 members, priority support |
| Enterprise | Unlimited, custom SLA |

## Platform Integration

- Organizations referenced by shizuha-pulse for project hierarchy
- Membership checked for access control across services
- User identity from shizuha-id via JWT
- HR data available to all services via internal API

## Frontend Routes

| Route | Component | Description |
|-------|-----------|-------------|
| `/admin/` | Dashboard | Org overview with stats |
| `/admin/departments` | Departments | Department tree view & CRUD |
| `/admin/teams` | Teams | Team grid with member management |
| `/admin/employees` | Employees | Employee directory with filters |
| `/admin/employees/:id` | EmployeeDetail | Full employee profile |
| `/admin/positions` | Positions | Job title catalog (stub) |
| `/admin/org-chart` | OrgChart | Visual hierarchy |
| `/admin/settings` | Settings | Organization configuration |

## Architecture Decisions

1. **Separate EmployeeProfile model**: OneToOne with OrganizationMembership keeps core membership lightweight while allowing rich HR data when needed.

2. **Manager stored as user_id**: Not a self-referential FK to EmployeeProfile, consistent with existing `lead_id` pattern, allows managers without full profiles.

3. **Dedicated admin frontend**: Separate from shizuha-id for clear separation of user profile vs org admin concerns. Lives at `/admin/` route.

4. **Server-rendered org chart tree**: Backend returns nested structure for efficient rendering, reduces client computation.
