# ROADMAP.md - Shizuha Admin

Planned features and technical debt for the Admin service.

## Current Focus

<!-- Update as priorities change -->

- HR hierarchy frontend refinements
- Employee profile creation workflow

## Planned Features

### High Priority

- [ ] Billing integration (Stripe)
- [ ] Usage tracking and limits
- [ ] Bulk employee import/export

### Medium Priority

- [ ] Audit log for organization actions
- [ ] Custom roles beyond preset 4
- [ ] Advanced Position management (pay grades, skills)
- [ ] Employment contracts and documents
- [ ] Performance tracking features

### Future Considerations

- [ ] Organization templates
- [ ] Cross-organization collaboration
- [ ] White-labeling support
- [ ] Compliance reporting
- [ ] Org chart PDF/PNG export

## Technical Debt

<!-- Track items needing refactoring -->

- [ ] Add invitation expiry
- [ ] Email notifications for invitations
- [ ] Improve permission caching
- [ ] Add employee profile validation for manager circular references
- [ ] Optimize org chart query for large organizations

## Recently Completed

<!-- Move items here when done, with date -->

- [x] Organization CRUD
- [x] Role-based membership
- [x] Pending invitation tracking
- [x] Plan-based organization structure
- [x] **HR Hierarchy Implementation (2026-01-31)**
  - [x] Department model with hierarchical structure
  - [x] Team model with cross-functional support
  - [x] Position model (stubbed for future)
  - [x] EmployeeProfile model with manager/department
  - [x] TeamMembership for team member management
  - [x] Full REST API for all HR entities
  - [x] Admin frontend with React + Vite
  - [x] Dashboard with org statistics
  - [x] Departments page with tree view
  - [x] Teams page with member management
  - [x] Employees directory with filtering
  - [x] Org Chart visualization
  - [x] Organization settings page

## Notes

<!-- Context about priorities or decisions -->

- Modeled after Jira/Atlassian organization structure for familiarity
- HR features follow phased approach: core hierarchy now, advanced features later
- Employee profiles require department + manager (per user decision for minimal required fields)
- Position management is stubbed for future phases
- Frontend lives at `/admin/` route, separate from `/id/account`
