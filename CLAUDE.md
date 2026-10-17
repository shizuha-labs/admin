# CLAUDE.md - Shizuha Admin

## Overview

**Shizuha Admin** is the organization and project management service for the platform. It handles multi-tenancy, teams, and billing.

| Setting | Value |
|---------|-------|
| Backend Port | 8003 |
| Database | shizuha_admin |
| Redis DB | 1 |
| URL Path | `/admin/` |

## Access

| URL | Description |
|-----|-------------|
| `/admin/api/` | REST API |
| `/admin/admin/` | Django Admin |

## API Endpoints

### Organizations
```
GET/POST   /admin/api/organizations/              # List/create orgs
GET/PATCH  /admin/api/organizations/{id}/         # Org details
GET        /admin/api/organizations/{id}/members/ # Org members
POST       /admin/api/organizations/{id}/invite/  # Invite member
```

### Teams
```
GET/POST   /admin/api/teams/                      # List/create teams
GET/PATCH  /admin/api/teams/{id}/                 # Team details
GET        /admin/api/teams/{id}/members/         # Team members
```

### Membership
```
GET /admin/api/memberships/                       # User's memberships
GET /admin/api/memberships/current/               # Current org context
```

### Billing
```
GET  /admin/api/billing/subscription/             # Current subscription
POST /admin/api/billing/checkout/                 # Create checkout session
POST /admin/api/billing/portal/                   # Customer portal
```

## Key Models

- **Organization** - Top-level tenant
- **Team** - Group within organization
- **Membership** - User-org relationship with role
- **Subscription** - Billing plan and status
- **Invoice** - Payment history

## Multi-Tenancy Pattern

All other services use org context via:
1. JWT token contains `organization_id` claim
2. API requests include `X-Organization-ID` header
3. Services filter data by organization

## Commands

All development commands run from the `compose/` directory using the master docker-compose.yaml:

```bash
# Start service
cd compose && docker compose up -d shizuha-admin

# Run migrations
cd compose && docker compose exec shizuha-admin python manage.py migrate

# Run tests
cd compose && docker compose exec shizuha-admin python manage.py test

# View logs
cd compose && docker compose logs -f shizuha-admin

```

## Project Structure

```
shizuha-admin/
├── shizuha_admin/        # Django project settings
├── organizations/        # Org/team management
│   ├── models.py         # Organization, Team, Membership
│   └── views.py          # DRF ViewSets
└── billing/              # Subscription management
    ├── models.py         # Subscription, Invoice
    └── stripe_webhooks.py # Stripe integration
```

Also reference [../CLAUDE.md](../CLAUDE.md) for platform-wide rules.
