#!/usr/bin/env python3
"""
Shizuha Admin MCP Server.

Organization management, HR hierarchy, and superuser administration tools
for AI agents.

Tools (55 total):

Identity:
- admin_get_current_user: Get current user details from /me/

Organizations:
- admin_list_organizations: List user's organizations
- admin_get_organization: Get organization details
- admin_create_organization: Create new organization
- admin_update_organization: Update organization
- admin_delete_organization: Delete organization

Org Members:
- admin_list_org_members: List organization members
- admin_invite_member: Invite user to organization
- admin_remove_member: Remove member from organization
- admin_leave_organization: Leave an organization

Org Projects:
- admin_list_org_projects: List projects in an organization

Departments:
- admin_list_departments: List departments
- admin_create_department: Create department
- admin_get_department: Get department details
- admin_update_department: Update department
- admin_delete_department: Delete department
- admin_get_department_tree: Get department hierarchy tree
- admin_list_department_employees: List employees in a department

Teams:
- admin_list_teams: List teams
- admin_create_team: Create team
- admin_get_team: Get team details
- admin_update_team: Update team
- admin_delete_team: Delete team
- admin_list_team_members: List team members
- admin_add_team_member: Add member to team
- admin_remove_team_member: Remove member from team

Positions:
- admin_list_positions: List positions
- admin_create_position: Create position
- admin_get_position: Get position details

Employees:
- admin_list_employees: List employees
- admin_create_employee: Create employee record
- admin_get_employee: Get employee details
- admin_update_employee: Update employee record
- admin_get_direct_reports: Get employee's direct reports
- admin_get_management_chain: Get employee's management chain

Org Chart:
- admin_get_org_chart: Get organization chart
- admin_get_org_chart_by_department: Get org chart grouped by department
- admin_get_org_chart_stats: Get org chart statistics

Org Services:
- admin_list_org_services: List services enabled for organization
- admin_list_org_service_members: List service members
- admin_add_org_service_member: Add user to org service

Superuser - Users:
- admin_su_list_users: List all users (superuser)
- admin_su_create_user: Create user (superuser)
- admin_su_get_user: Get user details (superuser)
- admin_su_update_user: Update user (superuser)
- admin_su_delete_user: Delete user (superuser)
- admin_su_get_user_services: Get user's services (superuser)
- admin_su_set_user_services: Set user's services (superuser)

Superuser - Approvals:
- admin_su_list_pending_users: List pending user approvals
- admin_su_get_pending_count: Get pending approval count
- admin_su_approve_user: Approve a pending user

Superuser - Organizations:
- admin_su_list_organizations: List all organizations (superuser)
- admin_su_create_organization: Create organization (superuser)
- admin_su_update_organization: Update organization (superuser)
- admin_su_get_organization: Get organization detail (superuser)

Superuser - Services:
- admin_su_list_services: List all services
- admin_su_list_org_services: List services for an org (superuser)
- admin_su_assign_org_service: Assign service to org (superuser)

Superuser - Requests:
- admin_su_list_requests: List service requests
- admin_su_update_request: Update a service request

Superuser - System:
- admin_su_system_health: Get system health status
- admin_su_dashboard: Get superuser dashboard
"""

import argparse
import json
import os
import sys
from typing import Optional

from base import ShizuhaMCPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base import ShizuhaMCPBase, run_mcp_server


def parse_args():
    """Parse command-line arguments for CLI argument compatibility."""
    parser = argparse.ArgumentParser(description="Shizuha Admin MCP Server")
    parser.add_argument(
        "--jwt-token",
        help="JWT token for authentication (overrides SHIZUHA_ADMIN_JWT_TOKEN env var)",
    )
    parser.add_argument(
        "--api-url",
        help="Admin API URL (overrides SHIZUHA_ADMIN_URL env var)",
    )
    args, _ = parser.parse_known_args()
    return args


# Parse CLI args (for callers that don't pass env vars to MCP subprocesses)
_args = parse_args()

# Configuration priority: CLI args > environment > defaults
ADMIN_API_URL = (
    _args.api_url
    or os.environ.get("SHIZUHA_ADMIN_URL")
    or os.environ.get("ADMIN_API_URL")
)
ADMIN_JWT_TOKEN = (
    _args.jwt_token
    or os.environ.get("SHIZUHA_ADMIN_JWT_TOKEN")
    or os.environ.get("ADMIN_JWT_TOKEN")
    or ""
)

mcp = ShizuhaMCPServer("shizuha-admin", stateless_http=True)

# Advertise OAuth 2.0 discovery metadata so MCP clients can discover the auth server.
from base import _register_oauth_discovery_routes as _reg_oauth_routes
_reg_oauth_routes(mcp, "admin")
base = ShizuhaMCPBase("admin", 8003, api_url=ADMIN_API_URL, jwt_token=ADMIN_JWT_TOKEN)


# ============================================================================
# Identity
# ============================================================================


@mcp.tool(name="admin_get_current_user")
def get_current_user() -> str:
    """
    Get detailed information about the current authenticated user.

    Returns full user data including organization memberships.
    """
    result = base.api_request("GET", "/me/")
    if "error" in result:
        return base.format_error(result)

    user = result
    output = f"# Current User\n\n"
    output += f"**ID**: {user.get('id')}\n"
    output += f"**Username**: {user.get('username')}\n"
    output += f"**Email**: {user.get('email')}\n"
    output += f"**Name**: {user.get('first_name', '')} {user.get('last_name', '')}\n"
    output += f"**Staff**: {user.get('is_staff', False)}\n"
    output += f"**Active**: {user.get('is_active', True)}\n"

    orgs = user.get('organizations', [])
    if orgs:
        output += f"\n## Organizations ({len(orgs)})\n"
        for org in orgs:
            output += f"- **{org.get('name')}** ({org.get('slug')}) - {org.get('role', 'member')}\n"

    return output


# ============================================================================
# Organizations
# ============================================================================


@mcp.tool(name="admin_list_organizations")
def list_organizations() -> str:
    """
    List all organizations the user is a member of.

    Returns organizations with their roles and member counts.
    """
    result = base.api_request("GET", "/organizations/")
    if "error" in result:
        return base.format_error(result)

    orgs = (result if isinstance(result, list) else result.get("results", []))
    if not orgs:
        return "No organizations found."

    output = f"# Organizations ({len(orgs)})\n\n"
    for org in orgs:
        output += f"## {org.get('name')}\n"
        output += f"**Slug**: {org.get('slug')}\n"
        output += f"**Plan**: {org.get('plan', 'free')}\n"
        output += f"**Members**: {org.get('member_count', 'N/A')}\n"
        if org.get('description'):
            output += f"**Description**: {org['description']}\n"
        output += "\n"

    return output


@mcp.tool(name="admin_get_organization")
def get_organization(slug: str) -> str:
    """
    Get detailed information about an organization.

    Args:
        slug: Organization slug (URL-friendly identifier)
    """
    result = base.api_request("GET", f"/organizations/{slug}/")
    if "error" in result:
        return base.format_error(result)

    org = result
    output = f"# {org.get('name')}\n\n"
    output += f"**Slug**: {org.get('slug')}\n"
    output += f"**Plan**: {org.get('plan', 'free')}\n"
    output += f"**Owner ID**: {org.get('owner_id')}\n"
    output += f"**Members**: {org.get('member_count', 'N/A')}\n"
    if org.get('description'):
        output += f"\n## Description\n{org['description']}\n"
    if org.get('settings'):
        output += f"\n## Settings\n```json\n{json.dumps(org['settings'], indent=2)}\n```\n"

    return output


@mcp.tool(name="admin_create_organization")
def create_organization(name: str, slug: str, description: str = "") -> str:
    """
    Create a new organization.

    Args:
        name: Organization display name
        slug: URL-friendly identifier (unique)
        description: Optional description
    """
    data = {
        "name": name,
        "slug": slug,
        "description": description,
    }

    result = base.api_request("POST", "/organizations/", data=data)
    if "error" in result:
        return base.format_error(result)

    org = result
    return (
        f"Organization created!\n\n"
        f"**Name**: {org.get('name')}\n"
        f"**Slug**: {org.get('slug')}\n"
        f"**ID**: {org.get('id')}\n"
    )


@mcp.tool(name="admin_update_organization")
def update_organization(
    slug: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    plan: Optional[str] = None,
    settings: Optional[str] = None,
) -> str:
    """
    Update an organization.

    Args:
        slug: Organization slug
        name: New display name (optional)
        description: New description (optional)
        plan: New plan tier (optional)
        settings: JSON string of settings to update (optional)

    Only provided fields will be updated.
    """
    data = {}
    if name is not None:
        data["name"] = name
    if description is not None:
        data["description"] = description
    if plan is not None:
        data["plan"] = plan
    if settings is not None:
        try:
            data["settings"] = json.loads(settings)
        except json.JSONDecodeError:
            return "Error: settings must be a valid JSON string."

    if not data:
        return "Error: No fields provided to update."

    result = base.api_request("PATCH", f"/organizations/{slug}/", data=data)
    if "error" in result:
        return base.format_error(result)

    org = result
    return (
        f"Organization updated!\n\n"
        f"**Name**: {org.get('name')}\n"
        f"**Slug**: {org.get('slug')}\n"
        f"**Plan**: {org.get('plan', 'free')}\n"
    )


@mcp.tool(name="admin_delete_organization")
def delete_organization(slug: str) -> str:
    """
    Delete an organization.

    Args:
        slug: Organization slug

    Warning: This permanently deletes the organization and all associated data.
    Requires owner permissions.
    """
    result = base.api_request("DELETE", f"/organizations/{slug}/")
    if "error" in result:
        return base.format_error(result)

    return f"Organization '{slug}' deleted successfully."


# ============================================================================
# Organization Members
# ============================================================================


@mcp.tool(name="admin_list_org_members")
def list_org_members(org_slug: str) -> str:
    """
    List members of an organization.

    Args:
        org_slug: Organization slug
    """
    result = base.api_request("GET", f"/organizations/{org_slug}/members/")
    if isinstance(result, dict) and "error" in result:
        return base.format_error(result)

    members = result.get("members", (result if isinstance(result, list) else result.get("results", [])))
    if not members:
        return "No members found."

    output = f"# Organization Members ({len(members)})\n\n"
    for member in members:
        role = member.get('role', 'member')
        status = "[active]" if member.get('is_active', True) else "[inactive]"
        output += f"- {status} **{member.get('user_email', 'Unknown')}** ({role})\n"
        if member.get('user_id'):
            output += f"  User ID: {member['user_id']}\n"
        if member.get('id'):
            output += f"  Member ID: {member['id']}\n"
        if member.get('invited_at') and not member.get('accepted_at'):
            output += f"  Status: Pending invitation\n"

    return output


@mcp.tool(name="admin_invite_member")
def invite_member(org_slug: str, email: str, role: str = "member") -> str:
    """
    Invite a user to an organization.

    Args:
        org_slug: Organization slug
        email: Email address to invite
        role: Role to assign (owner, admin, member, viewer)
    """
    # PLAT-1341: the org-members API (OrganizationMemberInviteSerializer) requires
    # `user_email`, not `email` — sending `email` always 400s
    # ("user_email: This field is required"). The MCP tool arg stays `email` for
    # callers; only the wire payload key is corrected.
    data = {"user_email": email, "role": role}

    result = base.api_request("POST", f"/organizations/{org_slug}/members/", data=data)
    if "error" in result:
        return base.format_error(result)

    return f"Invitation sent to {email} with role '{role}'."


@mcp.tool(name="admin_request_jit_elevation")
def request_jit_elevation(
    org_slug: str,
    scope: str,
    reason: str,
    task_key: str,
    requested_role: str = "admin",
    ttl_seconds: int = 3600,
    owning_team: str = "admin-platform",
    policy_slug: Optional[str] = None,
    target_team_id: Optional[str] = None,
    target_user_id: Optional[str] = None,
    target_role: Optional[str] = None,
    commit_sha: Optional[str] = None,
) -> str:
    """
    Request a scoped, time-bound elevated-access grant (PLAT-1346).

    Requests are left pending for the owning team unless a trusted internal
    policy predicate is verified by the Admin service — never escalated to the
    operator by default.

    Args:
        org_slug: Organization slug
        scope: Scoped action (e.g. org.members.add)
        reason: Why this task needs elevation
        task_key: Pulse task key driving the request
        requested_role: Temporary org role to project (admin/owner/member/viewer)
        ttl_seconds: Grant duration after approval (max 14400)
        owning_team: Team that owns approval for non-policy grants
        policy_slug: Optional trusted policy predicate slug; caller-supplied
            values are fail-closed unless Admin verifies the actor/policy
        target_team_id: Exact target team for a target-constrained action
        target_user_id: Exact target Shizuha user for a target-constrained action
        target_role: Exact team role (lead/member) for a target-constrained action
        commit_sha: Full deploy default-branch SHA for kubernetes.rbac.apply
    """
    data = {
        "org_slug": org_slug,
        "scope": scope,
        "reason": reason,
        "task_key": task_key,
        "requested_role": requested_role,
        "ttl_seconds": int(ttl_seconds),
        "owning_team": owning_team,
    }
    if policy_slug:
        data["policy_slug"] = policy_slug
    try:
        if target_team_id:
            data["target_team_id"] = int(target_team_id)
        if target_user_id:
            data["target_user_id"] = int(target_user_id)
    except (TypeError, ValueError):
        return "Error: target_team_id and target_user_id must be integers."
    if target_role:
        data["target_role"] = target_role
    if commit_sha:
        data["commit_sha"] = commit_sha
    result = base.api_request("POST", "/jit-elevations/", data=data)
    if "error" in result:
        return base.format_error(result)

    grant = result.get("grant", {})
    status = grant.get("status", "unknown")
    output = "# JIT elevation request\n\n"
    output += f"- Grant ID: {grant.get('id')}\n"
    output += f"- Status: {status}\n"
    output += f"- Auto-approved: {result.get('auto_approved', False)}\n"
    output += f"- Organization: {grant.get('organization_slug', org_slug)}\n"
    output += f"- Scope: {grant.get('scope', scope)}\n"
    output += f"- Role: {grant.get('requested_role', requested_role)}\n"
    output += f"- Owning team: {grant.get('owning_team', owning_team)}\n"
    if grant.get("approver_team"):
        output += f"- Approver team ID: {grant['approver_team']}\n"
    if grant.get("target_team"):
        output += f"- Exact target: team {grant['target_team']}, user {grant.get('target_user_id')}, role {grant.get('target_role')}\n"
    if grant.get("expires_at"):
        output += f"- Expires at: {grant['expires_at']}\n"
    if status == "pending":
        output += "\nPending owning-team approval; use this team route unless a critical-class policy exception applies.\n"
    return output


@mcp.tool(name="admin_consume_kubernetes_jit")
def consume_kubernetes_jit(
    grant_id: str,
    idempotency_key: str,
    expected_sha: str,
    action: str = "apply-origin-ci-deployer-rbac",
) -> str:
    """Consume a requester-owned Kubernetes JIT grant via the fixed Origin workflow."""
    result = base.api_request(
        "POST",
        f"/jit-elevations/{grant_id}/consume-kubernetes/",
        data={
            "idempotency_key": idempotency_key,
            "expected_sha": expected_sha,
            "action": action,
        },
    )
    if "error" in result:
        return base.format_error(result)
    output = "# Kubernetes JIT consumption\n\n"
    output += f"- Grant ID: {result.get('grant_id', grant_id)}\n"
    output += f"- Use ID: {result.get('use_id')}\n"
    output += f"- Task: {result.get('task_key')}\n"
    output += f"- Action: {result.get('action')}\n"
    output += f"- Expected SHA: {result.get('expected_sha')}\n"
    output += f"- Dispatch: {result.get('dispatch_status')}\n"
    if result.get("origin_run_id"):
        output += f"- Origin run ID: {result['origin_run_id']}\n"
    return output


@mcp.tool(name="admin_list_jit_elevations")
def list_jit_elevations(status: Optional[str] = None) -> str:
    """
    List visible JIT elevated-access requests/grants.

    Args:
        status: Optional filter (pending, approved, denied, revoked)
    """
    params = {"status": status} if status else None
    result = base.api_request("GET", "/jit-elevations/", params=params)
    if "error" in result:
        return base.format_error(result)

    grants = result.get("results", [])
    if not grants:
        return "No JIT elevation grants found."
    output = f"# JIT Elevations ({len(grants)})\n\n"
    for grant in grants:
        output += (
            f"- **#{grant.get('id')}** {grant.get('status')} "
            f"{grant.get('requested_role')} for {grant.get('scope')} "
            f"in {grant.get('organization_slug')} (task {grant.get('task_key')})\n"
        )
        # PLAT-5079: render the stored requester_user_id alongside the email so
        # an MCP seat can distinguish the id space the create path wrote.
        output += (
            f"  requester_user_id={grant.get('requester_user_id')}; "
            f"requester_email={grant.get('requester_email') or '(none)'}; "
            f"owning_team={grant.get('owning_team')}; active={grant.get('active')}\n"
        )
        if grant.get("decided_by_user_id") or grant.get("decided_by_email"):
            output += (
                f"  decided_by_user_id={grant.get('decided_by_user_id')}; "
                f"decided_by_email={grant.get('decided_by_email') or '(none)'}\n"
            )
        if grant.get("expires_at"):
            output += f"  expires_at={grant['expires_at']}\n"
    return output


@mcp.tool(name="admin_get_jit_elevation")
def get_jit_elevation(grant_id: str) -> str:
    """
    Read a single JIT elevated-access grant plus its decision-event history.

    Returns the grant (including stored requester_user_id and decided-by
    identity) and every JITElevatedAccessGrantEvent row (event_type,
    actor_user_id, actor_email, source, timestamp) for that grant. Read-only;
    scoped to grants the caller is entitled to see.

    Args:
        grant_id: JIT grant ID
    """
    result = base.api_request("GET", f"/jit-elevations/{grant_id}/")
    if "error" in result:
        return base.format_error(result)
    grant = result.get("grant", {})
    events = result.get("events", [])
    output = (
        f"# JIT Elevation #{grant.get('id', grant_id)}\n"
        f"status={grant.get('status')}; requested_role={grant.get('requested_role')}; "
        f"scope={grant.get('scope')}; org={grant.get('organization_slug')}; "
        f"task={grant.get('task_key')}\n"
        f"requester_user_id={grant.get('requester_user_id')}; "
        f"requester_email={grant.get('requester_email') or '(none)'}\n"
        f"owning_team={grant.get('owning_team')}; active={grant.get('active')}\n"
    )
    if grant.get("decided_by_user_id") or grant.get("decided_by_email"):
        output += (
            f"decided_by_user_id={grant.get('decided_by_user_id')}; "
            f"decided_by_email={grant.get('decided_by_email') or '(none)'}\n"
        )
    if grant.get("expires_at"):
        output += f"expires_at={grant['expires_at']}\n"
    output += f"\n## Decision events ({len(events)})\n"
    if not events:
        output += "No decision events recorded.\n"
    for event in events:
        output += (
            f"- **{event.get('event_type')}** at {event.get('created_at')} "
            f"actor_user_id={event.get('actor_user_id')} "
            f"actor_email={event.get('actor_email') or '(none)'} "
            f"source={event.get('source')}\n"
        )
    return output


@mcp.tool(name="admin_decide_jit_elevation")
def decide_jit_elevation(grant_id: str, action: str, note: str = "") -> str:
    """
    Approve, deny, or revoke a JIT elevated-access grant.

    Args:
        grant_id: JIT grant ID
        action: approve, deny, or revoke
        note: Decision note/audit reason
    """
    action = action.strip().lower()
    if action not in {"approve", "deny", "revoke"}:
        return "Error: action must be approve, deny, or revoke."
    result = base.api_request(
        "POST",
        f"/jit-elevations/{grant_id}/{action}/",
        data={"note": note},
    )
    if "error" in result:
        return base.format_error(result)
    grant = result.get("grant", {})
    output = f"JIT grant #{grant.get('id', grant_id)} {grant.get('status', action)}."
    if grant.get("expires_at"):
        output += f" Expires at {grant['expires_at']}."
    return output


@mcp.tool(name="admin_remove_member")
def remove_member(org_slug: str, member_id: str) -> str:
    """
    Remove a member from an organization.

    Args:
        org_slug: Organization slug
        member_id: Member ID to remove (from list_org_members)

    Note: Cannot remove yourself; use leave_organization instead.
    """
    result = base.api_request(
        "DELETE", f"/organizations/{org_slug}/members/{member_id}/"
    )
    if "error" in result:
        return base.format_error(result)

    return f"Member {member_id} removed from organization '{org_slug}'."


@mcp.tool(name="admin_leave_organization")
def leave_organization(org_slug: str) -> str:
    """
    Leave an organization (current user).

    Args:
        org_slug: Organization slug

    Note: Organization owners cannot leave without transferring ownership first.
    """
    result = base.api_request("POST", f"/organizations/{org_slug}/leave/")
    if "error" in result:
        return base.format_error(result)

    return f"Successfully left organization '{org_slug}'."


# ============================================================================
# Organization Projects
# ============================================================================


@mcp.tool(name="admin_list_org_projects")
def list_org_projects(org_slug: str) -> str:
    """
    List projects belonging to an organization.

    Args:
        org_slug: Organization slug
    """
    result = base.api_request("GET", f"/organizations/{org_slug}/projects/")
    if "error" in result:
        return base.format_error(result)

    projects = (result if isinstance(result, list) else result.get("results", []))
    if not projects:
        return "No projects found for this organization."

    output = f"# Organization Projects ({len(projects)})\n\n"
    for proj in projects:
        archived = " [archived]" if proj.get('is_archived') else ""
        output += f"## {proj.get('name')} ({proj.get('key', 'N/A')}){archived}\n"
        output += f"**ID**: {proj.get('id')}\n"
        output += f"**Type**: {proj.get('project_type', 'N/A')}\n"
        output += f"**Access**: {proj.get('access_level', 'N/A')}\n"
        if proj.get('description'):
            output += f"**Description**: {proj['description'][:100]}\n"
        output += "\n"

    return output


# ============================================================================
# Departments
# ============================================================================


@mcp.tool(name="admin_list_departments")
def list_departments(org_slug: str) -> str:
    """
    List departments in an organization.

    Args:
        org_slug: Organization slug
    """
    result = base.api_request("GET", f"/organizations/{org_slug}/departments/")
    if "error" in result:
        return base.format_error(result)

    depts = (result if isinstance(result, list) else result.get("results", []))
    if not depts:
        return "No departments found."

    output = f"# Departments ({len(depts)})\n\n"
    for dept in depts:
        output += f"- **{dept.get('name')}**\n"
        output += f"  ID: {dept.get('id')}\n"
        if dept.get('parent'):
            output += f"  Parent: {dept.get('parent_name', dept['parent'])}\n"
        if dept.get('manager_id'):
            output += f"  Manager ID: {dept['manager_id']}\n"
        if dept.get('employee_count') is not None:
            output += f"  Employees: {dept['employee_count']}\n"

    return output


@mcp.tool(name="admin_create_department")
def create_department(
    org_slug: str,
    name: str,
    description: str = "",
    parent_id: Optional[str] = None,
    manager_id: Optional[str] = None,
) -> str:
    """
    Create a department in an organization.

    Args:
        org_slug: Organization slug
        name: Department name
        description: Department description (optional)
        parent_id: Parent department ID for hierarchy (optional)
        manager_id: Employee ID of department manager (optional)
    """
    data = {"name": name}
    if description:
        data["description"] = description
    if parent_id:
        data["parent"] = parent_id
    if manager_id:
        data["manager"] = manager_id

    result = base.api_request(
        "POST", f"/organizations/{org_slug}/departments/", data=data
    )
    if "error" in result:
        return base.format_error(result)

    dept = result
    return (
        f"Department created!\n\n"
        f"**Name**: {dept.get('name')}\n"
        f"**ID**: {dept.get('id')}\n"
    )


@mcp.tool(name="admin_get_department")
def get_department(org_slug: str, department_id: str) -> str:
    """
    Get detailed information about a department.

    Args:
        org_slug: Organization slug
        department_id: Department ID
    """
    result = base.api_request(
        "GET", f"/organizations/{org_slug}/departments/{department_id}/"
    )
    if "error" in result:
        return base.format_error(result)

    dept = result
    output = f"# {dept.get('name')}\n\n"
    output += f"**ID**: {dept.get('id')}\n"
    if dept.get('description'):
        output += f"**Description**: {dept['description']}\n"
    output += f"**Parent**: {dept.get('parent_name', dept.get('parent', 'None'))}\n"
    output += f"**Manager**: {dept.get('manager_name', dept.get('manager', 'None'))}\n"
    if dept.get('employee_count') is not None:
        output += f"**Employees**: {dept['employee_count']}\n"
    if dept.get('children'):
        output += f"\n## Sub-departments\n"
        for child in dept['children']:
            output += f"- {child.get('name')} (ID: {child.get('id')})\n"

    return output


@mcp.tool(name="admin_update_department")
def update_department(
    org_slug: str,
    department_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    parent_id: Optional[str] = None,
    manager_id: Optional[str] = None,
) -> str:
    """
    Update a department.

    Args:
        org_slug: Organization slug
        department_id: Department ID
        name: New name (optional)
        description: New description (optional)
        parent_id: New parent department ID (optional)
        manager_id: New manager employee ID (optional)

    Only provided fields will be updated.
    """
    data = {}
    if name is not None:
        data["name"] = name
    if description is not None:
        data["description"] = description
    if parent_id is not None:
        data["parent"] = parent_id
    if manager_id is not None:
        data["manager"] = manager_id

    if not data:
        return "Error: No fields provided to update."

    result = base.api_request(
        "PATCH", f"/organizations/{org_slug}/departments/{department_id}/", data=data
    )
    if "error" in result:
        return base.format_error(result)

    dept = result
    return (
        f"Department updated!\n\n"
        f"**Name**: {dept.get('name')}\n"
        f"**ID**: {dept.get('id')}\n"
    )


@mcp.tool(name="admin_delete_department")
def delete_department(org_slug: str, department_id: str) -> str:
    """
    Delete a department.

    Args:
        org_slug: Organization slug
        department_id: Department ID

    Warning: This deletes the department. Employees in this department
    may need to be reassigned.
    """
    result = base.api_request(
        "DELETE", f"/organizations/{org_slug}/departments/{department_id}/"
    )
    if "error" in result:
        return base.format_error(result)

    return f"Department {department_id} deleted successfully."


@mcp.tool(name="admin_get_department_tree")
def get_department_tree(org_slug: str) -> str:
    """
    Get the full department hierarchy tree for an organization.

    Args:
        org_slug: Organization slug

    Returns a nested tree structure of all departments.
    """
    result = base.api_request(
        "GET", f"/organizations/{org_slug}/departments/tree/"
    )
    if "error" in result:
        return base.format_error(result)

    tree = result if isinstance(result, list) else result.get("results", [result])

    def render_tree(nodes, indent=0):
        output = ""
        for node in nodes:
            prefix = "  " * indent + "- "
            output += f"{prefix}**{node.get('name')}** (ID: {node.get('id')})\n"
            children = node.get('children', [])
            if children:
                output += render_tree(children, indent + 1)
        return output

    output = f"# Department Tree\n\n"
    output += render_tree(tree)
    return output


@mcp.tool(name="admin_list_department_employees")
def list_department_employees(org_slug: str, department_id: str) -> str:
    """
    List employees in a specific department.

    Args:
        org_slug: Organization slug
        department_id: Department ID
    """
    result = base.api_request(
        "GET", f"/organizations/{org_slug}/departments/{department_id}/employees/"
    )
    if "error" in result:
        return base.format_error(result)

    employees = (result if isinstance(result, list) else result.get("results", []))
    if not employees:
        return "No employees found in this department."

    output = f"# Department Employees ({len(employees)})\n\n"
    for emp in employees:
        name = f"{emp.get('first_name', '')} {emp.get('last_name', '')}".strip()
        output += f"- **{name or 'Unknown'}**\n"
        output += f"  ID: {emp.get('id')}\n"
        output += f"  Position: {emp.get('position_name', emp.get('position', 'N/A'))}\n"
        output += f"  Email: {emp.get('email', 'N/A')}\n"

    return output


# ============================================================================
# Teams
# ============================================================================


def _collect_team_pages(org_slug: str) -> tuple:
    """PLAT-1207: follow DRF pagination on the teams list.

    AdminPublicPageNumberPagination serves PAGE_SIZE=20 per page and ignores
    a page_size query param, so a single GET only ever sees page 1 (the
    "# Teams (20)" vs 35-in-DB failure). Walk ``page`` until ``next`` is
    empty, and report the server's ``count`` as the authoritative total.
    Returns (teams, total_count) or (error_dict, None).
    """
    teams = []
    total = None
    page = 1
    while page <= 100:  # defensive cap; 100 pages = 2000 teams
        result = base.api_request(
            "GET", f"/organizations/{org_slug}/teams/",
            params={"page": page} if page > 1 else None,
        )
        if isinstance(result, dict) and "error" in result:
            return (result, None) if page == 1 else (teams, total)
        if isinstance(result, list):
            return result, len(result)
        teams.extend(result.get("results", []))
        if total is None:
            total = result.get("count")
        if not result.get("next"):
            break
        page += 1
    return teams, (total if total is not None else len(teams))


@mcp.tool(name="admin_list_teams")
def list_teams(org_slug: str) -> str:
    """
    List teams in an organization.

    Args:
        org_slug: Organization slug
    """
    result, total = _collect_team_pages(org_slug)
    if isinstance(result, dict) and "error" in result:
        return base.format_error(result)

    teams = result
    if not teams:
        return "No teams found."

    output = f"# Teams ({total})\n\n"
    for team in teams:
        output += f"- **{team.get('name')}**\n"
        output += f"  ID: {team.get('id')}\n"
        if team.get('description'):
            output += f"  Description: {team['description'][:100]}\n"
        if team.get('member_count') is not None:
            output += f"  Members: {team['member_count']}\n"
        if team.get('lead_name') or team.get('lead'):
            output += f"  Lead: {team.get('lead_name', team.get('lead', 'N/A'))}\n"

    return output


@mcp.tool(name="admin_create_team")
def create_team(
    org_slug: str,
    name: str,
    description: str = "",
    lead_id: Optional[str] = None,
    department_id: Optional[str] = None,
    lead_email: Optional[str] = None,
) -> str:
    """
    Create a team in an organization.

    Args:
        org_slug: Organization slug
        name: Team name
        description: Team description (optional)
        lead_id: User ID of team lead (optional)
        department_id: Department ID this team belongs to (optional)
        lead_email: Email of team lead; backend resolves it to lead_id (optional)
    """
    data = {"name": name}
    if description:
        data["description"] = description
    # PLAT-1207: TeamCreateSerializer accepts lead_id/lead_email; the old
    # "lead" key was silently dropped by DRF and left Lead: None.
    if lead_id:
        data["lead_id"] = lead_id
    if lead_email:
        data["lead_email"] = lead_email
    if department_id:
        data["department"] = department_id

    result = base.api_request(
        "POST", f"/organizations/{org_slug}/teams/", data=data
    )
    if "error" in result:
        return base.format_error(result)

    team = result
    return (
        f"Team created!\n\n"
        f"**Name**: {team.get('name')}\n"
        f"**ID**: {team.get('id')}\n"
        f"**Lead**: {team.get('lead_name') or team.get('lead_email') or team.get('lead_id') or 'None'}\n"
    )


@mcp.tool(name="admin_get_team")
def get_team(org_slug: str, team_id: str) -> str:
    """
    Get detailed information about a team.

    Args:
        org_slug: Organization slug
        team_id: Team ID
    """
    result = base.api_request(
        "GET", f"/organizations/{org_slug}/teams/{team_id}/"
    )
    if "error" in result:
        return base.format_error(result)

    team = result
    output = f"# {team.get('name')}\n\n"
    output += f"**ID**: {team.get('id')}\n"
    if team.get('description'):
        output += f"**Description**: {team['description']}\n"
    output += f"**Lead**: {team.get('lead_name', team.get('lead', 'None'))}\n"
    output += f"**Department**: {team.get('department_name', team.get('department', 'None'))}\n"
    if team.get('member_count') is not None:
        output += f"**Members**: {team['member_count']}\n"
    output += f"**Created**: {team.get('created_at', 'N/A')}\n"

    return output


@mcp.tool(name="admin_update_team")
def update_team(
    org_slug: str,
    team_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    lead_id: Optional[str] = None,
    department_id: Optional[str] = None,
    lead_email: Optional[str] = None,
) -> str:
    """
    Update a team.

    Args:
        org_slug: Organization slug
        team_id: Team ID
        name: New name (optional)
        description: New description (optional)
        lead_id: New lead user ID (optional)
        department_id: New department ID (optional)
        lead_email: New lead email; backend resolves it to lead_id (optional)

    Only provided fields will be updated.
    """
    data = {}
    if name is not None:
        data["name"] = name
    if description is not None:
        data["description"] = description
    # PLAT-1207: TeamSerializer accepts lead_id/lead_email; the old "lead"
    # key was silently dropped by DRF and left Lead: None.
    if lead_id is not None:
        data["lead_id"] = lead_id
    if lead_email is not None:
        data["lead_email"] = lead_email
    if department_id is not None:
        data["department"] = department_id

    if not data:
        return "Error: No fields provided to update."

    result = base.api_request(
        "PATCH", f"/organizations/{org_slug}/teams/{team_id}/", data=data
    )
    if "error" in result:
        return base.format_error(result)

    team = result
    return (
        f"Team updated!\n\n"
        f"**Name**: {team.get('name')}\n"
        f"**ID**: {team.get('id')}\n"
        f"**Lead**: {team.get('lead_name') or team.get('lead_email') or team.get('lead_id') or 'None'}\n"
    )


@mcp.tool(name="admin_delete_team")
def delete_team(org_slug: str, team_id: str) -> str:
    """
    Delete a team.

    Args:
        org_slug: Organization slug
        team_id: Team ID

    Warning: This permanently deletes the team.
    """
    result = base.api_request(
        "DELETE", f"/organizations/{org_slug}/teams/{team_id}/"
    )
    if "error" in result:
        return base.format_error(result)

    return f"Team {team_id} deleted successfully."


@mcp.tool(name="admin_list_team_members")
def list_team_members(org_slug: str, team_id: str) -> str:
    """
    List members of a team.

    Args:
        org_slug: Organization slug
        team_id: Team ID
    """
    result = base.api_request(
        "GET", f"/organizations/{org_slug}/teams/{team_id}/members/"
    )
    if "error" in result:
        return base.format_error(result)

    # HIVE-292: TeamViewSet.members returns {"team", "count", "members": [...]}
    # (TeamMembershipSerializer rows), not a bare list or DRF "results" page.
    if isinstance(result, list):
        members = result
    else:
        members = result.get("members", result.get("results", []))
    if not members:
        return "No team members found."

    # PLS-770: dedupe by identity so one person is not presented twice when a
    # directory lead edge coexists with a routing edge. Routing (Pulse roster)
    # rows are authoritative; prefer them and annotate the source of each row.
    seen_emails = set()
    unique_members = []
    for member in members:
        email = (
            member.get("employee_email")
            or member.get("user_email")
            or member.get("email")
            or ""
        ).strip().lower()
        if not email:
            unique_members.append(member)
            continue
        if email in seen_emails:
            # A routing row for the same identity supersedes the directory one.
            if member.get("routing_member"):
                unique_members = [
                    m for m in unique_members
                    if (m.get("employee_email") or m.get("user_email")
                        or m.get("email") or "").strip().lower() != email
                ]
                unique_members.append(member)
            continue
        seen_emails.add(email)
        unique_members.append(member)

    output = f"# Team Members ({len(unique_members)})\n\n"
    for member in unique_members:
        # TeamMembershipSerializer fields: employee_name / employee_email /
        # employee_title / employee_profile / role. Older shapes kept as
        # fallbacks.
        name = (member.get('employee_name') or member.get('user_name')
                or member.get('username') or member.get('employee_email')
                or member.get('email') or 'Unknown')
        role = member.get('role', 'member')
        source = member.get('source')
        routing = member.get('routing_member')
        output += f"- **{name}** ({role})"
        if source or routing is not None:
            output += f" [source={source or 'directory'}"
            output += f", routing={str(bool(routing)).lower()}]"
        output += "\n"
        if member.get('employee_email'):
            output += f"  Email: {member['employee_email']}\n"
        if member.get('employee_title'):
            output += f"  Title: {member['employee_title']}\n"
        if member.get('id'):
            output += f"  Member ID: {member['id']}\n"
        if member.get('employee_profile'):
            output += f"  Employee Profile ID: {member['employee_profile']}\n"
        if member.get('user_id'):
            output += f"  User ID: {member['user_id']}\n"

    return output


def _resolve_employee_profile_id(org_slug: str, user_id: str) -> Optional[int]:
    """PLAT-1171: map a Shizuha user id to the org's EmployeeProfile id.

    TeamMemberAddSerializer requires ``employee_profile_id``; EmployeeProfile
    rows expose ``user_id`` via their membership, so scan the org's employees.
    """
    page = 1
    while True:
        result = base.api_request(
            "GET", f"/organizations/{org_slug}/employees/",
            params={"page_size": 100, "page": page},
        )
        if isinstance(result, dict) and "error" in result:
            return None
        rows = result if isinstance(result, list) else result.get("results", [])
        for emp in rows:
            if str(emp.get("user_id")) == str(user_id):
                return emp.get("id")
        if isinstance(result, list) or not result.get("next"):
            return None
        page += 1


@mcp.tool(name="admin_add_team_member")
def add_team_member(
    org_slug: str,
    team_id: str,
    user_id: str = "",
    role: str = "member",
    employee_profile_id: str = "",
    jit_grant_id: str = "",
    jit_idempotency_key: str = "",
) -> str:
    """
    Add a member to a team.

    Args:
        org_slug: Organization slug
        team_id: Team ID
        user_id: Shizuha user ID to add (resolved to the org's employee
            profile automatically)
        role: Role in team (lead, member)
        employee_profile_id: EmployeeProfile ID (skips user_id resolution
            when you already have it)
        jit_grant_id: Exact approved JIT grant ID when persistent HR admin
            authority is unavailable
        jit_idempotency_key: Stable retry key required with jit_grant_id
    """
    # PLAT-1171: the backend's TeamMemberAddSerializer requires
    # employee_profile_id — a raw user_id payload always 400s. Accept either
    # reference and resolve user_id -> employee profile ourselves.
    if not employee_profile_id and not user_id:
        return "Error: pass user_id or employee_profile_id."
    if not employee_profile_id:
        resolved = _resolve_employee_profile_id(org_slug, user_id)
        if resolved is None:
            return (
                f"Error: no employee profile found for user_id {user_id!r} in "
                f"org '{org_slug}'. The user needs an employee record first "
                f"(admin_create_employee)."
            )
        employee_profile_id = str(resolved)

    data = {"employee_profile_id": int(employee_profile_id), "role": role}
    if jit_grant_id:
        if not jit_idempotency_key:
            return "Error: jit_idempotency_key is required with jit_grant_id."
        data["jit_grant_id"] = int(jit_grant_id)
        data["jit_idempotency_key"] = jit_idempotency_key

    result = base.api_request(
        "POST", f"/organizations/{org_slug}/teams/{team_id}/members/", data=data
    )
    if "error" in result:
        return base.format_error(result)

    member_name = result.get("employee_name") if isinstance(result, dict) else None
    who = member_name or (f"user {user_id}" if user_id else f"employee profile {employee_profile_id}")
    return f"{who} added to team with role '{role}' (employee_profile_id={employee_profile_id})."


@mcp.tool(name="admin_remove_team_member")
def remove_team_member(org_slug: str, team_id: str, member_id: str) -> str:
    """
    Remove a member from a team.

    Args:
        org_slug: Organization slug
        team_id: Team ID
        member_id: Team member ID to remove
    """
    result = base.api_request(
        "DELETE",
        f"/organizations/{org_slug}/teams/{team_id}/members/{member_id}/",
    )
    if "error" in result:
        return base.format_error(result)

    return f"Member {member_id} removed from team."


# ============================================================================
# Positions
# ============================================================================


@mcp.tool(name="admin_list_positions")
def list_positions(org_slug: str) -> str:
    """
    List positions in an organization.

    Args:
        org_slug: Organization slug
    """
    result = base.api_request("GET", f"/organizations/{org_slug}/positions/")
    if "error" in result:
        return base.format_error(result)

    positions = (result if isinstance(result, list) else result.get("results", []))
    if not positions:
        return "No positions found."

    output = f"# Positions ({len(positions)})\n\n"
    for pos in positions:
        output += f"- **{pos.get('title', pos.get('name'))}**\n"
        output += f"  ID: {pos.get('id')}\n"
        if pos.get('department_name') or pos.get('department'):
            output += f"  Department: {pos.get('department_name', pos.get('department'))}\n"
        if pos.get('level') is not None:
            output += f"  Level: {pos['level']}\n"
        if pos.get('description'):
            output += f"  Description: {pos['description'][:80]}\n"

    return output


@mcp.tool(name="admin_create_position")
def create_position(
    org_slug: str,
    title: str,
    description: str = "",
    department_id: Optional[str] = None,
    level: Optional[int] = None,
) -> str:
    """
    Create a position in an organization.

    Args:
        org_slug: Organization slug
        title: Position title
        description: Position description (optional)
        department_id: Department ID this position belongs to (optional)
        level: Position level/rank (optional)
    """
    data = {"title": title}
    if description:
        data["description"] = description
    if department_id:
        data["department"] = department_id
    if level is not None:
        data["level"] = level

    result = base.api_request(
        "POST", f"/organizations/{org_slug}/positions/", data=data
    )
    if "error" in result:
        return base.format_error(result)

    pos = result
    return (
        f"Position created!\n\n"
        f"**Title**: {pos.get('title', pos.get('name'))}\n"
        f"**ID**: {pos.get('id')}\n"
    )


@mcp.tool(name="admin_get_position")
def get_position(org_slug: str, position_id: str) -> str:
    """
    Get detailed information about a position.

    Args:
        org_slug: Organization slug
        position_id: Position ID
    """
    result = base.api_request(
        "GET", f"/organizations/{org_slug}/positions/{position_id}/"
    )
    if "error" in result:
        return base.format_error(result)

    pos = result
    output = f"# {pos.get('title', pos.get('name'))}\n\n"
    output += f"**ID**: {pos.get('id')}\n"
    if pos.get('description'):
        output += f"**Description**: {pos['description']}\n"
    output += f"**Department**: {pos.get('department_name', pos.get('department', 'N/A'))}\n"
    if pos.get('level') is not None:
        output += f"**Level**: {pos['level']}\n"
    if pos.get('employee_count') is not None:
        output += f"**Employees in Position**: {pos['employee_count']}\n"

    return output


# ============================================================================
# Employees
# ============================================================================


@mcp.tool(name="admin_list_employees")
def list_employees(
    org_slug: str,
    department_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
) -> str:
    """
    List employees in an organization.

    Args:
        org_slug: Organization slug
        department_id: Filter by department ID (optional)
        status: Filter by status (active, inactive, terminated) (optional)
        limit: Maximum employees to return (default: 20)
    """
    params = {"page_size": min(limit, 100)}
    if department_id:
        params["department"] = department_id
    if status:
        params["status"] = status

    result = base.api_request(
        "GET", f"/organizations/{org_slug}/employees/", params=params
    )
    if "error" in result:
        return base.format_error(result)

    employees = (result if isinstance(result, list) else result.get("results", []))
    if not employees:
        return "No employees found."

    # The backend paginator ignores page_size, so enforce the limit here.
    employees = employees[:max(limit, 1)]

    output = f"# Employees ({len(employees)})\n\n"
    for emp in employees:
        # PLAT-1204: employee rows expose display_name/user_email/user_id plus
        # job_title (list serializer) or position_title/department_name (full
        # serializer) — not first_name/last_name/email. Values may be present
        # but null, so chain with `or`; keep old keys for legacy shapes.
        name = (emp.get('display_name')
                or f"{emp.get('first_name', '')} {emp.get('last_name', '')}".strip())
        output += f"- **{name or 'Unknown'}**\n"
        output += f"  ID: {emp.get('id')}\n"
        if emp.get('user_id') is not None:
            output += f"  User ID: {emp.get('user_id')}\n"
        output += f"  Email: {emp.get('user_email') or emp.get('email') or 'N/A'}\n"
        output += f"  Department: {emp.get('department_name') or emp.get('department') or 'N/A'}\n"
        position = (emp.get('job_title') or emp.get('position_title')
                    or emp.get('position_name') or emp.get('position') or 'N/A')
        output += f"  Position: {position}\n"
        output += f"  Status: {emp.get('employment_status') or emp.get('status') or 'active'}\n\n"

    return output


@mcp.tool(name="admin_create_employee")
def create_employee(
    org_slug: str,
    user_id: str,
    employee_id: Optional[str] = None,
    department_id: Optional[str] = None,
    position_id: Optional[str] = None,
    manager_id: Optional[str] = None,
    join_date: Optional[str] = None,
    employment_type: str = "full_time",
) -> str:
    """
    Create an employee record in an organization.

    Args:
        org_slug: Organization slug
        user_id: User ID to link employee to
        employee_id: Custom employee ID/code (optional)
        department_id: Department ID (optional)
        position_id: Position ID (optional)
        manager_id: Manager's employee ID (optional)
        join_date: Join date in YYYY-MM-DD format (optional)
        employment_type: Type (full_time, part_time, contract, intern)
    """
    data = {"user": user_id, "employment_type": employment_type}
    if employee_id:
        data["employee_id"] = employee_id
    if department_id:
        data["department"] = department_id
    if position_id:
        data["position"] = position_id
    if manager_id:
        data["manager"] = manager_id
    if join_date:
        data["join_date"] = join_date

    result = base.api_request(
        "POST", f"/organizations/{org_slug}/employees/", data=data
    )
    if "error" in result:
        return base.format_error(result)

    emp = result
    name = f"{emp.get('first_name', '')} {emp.get('last_name', '')}".strip()
    return (
        f"Employee created!\n\n"
        f"**Name**: {name or 'N/A'}\n"
        f"**ID**: {emp.get('id')}\n"
        f"**Employee ID**: {emp.get('employee_id', 'N/A')}\n"
    )


@mcp.tool(name="admin_get_employee")
def get_employee(org_slug: str, employee_id: str) -> str:
    """
    Get detailed employee information.

    Args:
        org_slug: Organization slug
        employee_id: Employee ID
    """
    result = base.api_request(
        "GET", f"/organizations/{org_slug}/employees/{employee_id}/"
    )
    if "error" in result:
        return base.format_error(result)

    emp = result
    output = f"# {emp.get('first_name', '')} {emp.get('last_name', '')}\n\n"
    output += f"**ID**: {emp.get('id')}\n"
    output += f"**Employee ID**: {emp.get('employee_id', 'N/A')}\n"
    output += f"**Email**: {emp.get('email', 'N/A')}\n"
    output += f"**Phone**: {emp.get('phone', 'N/A')}\n"
    output += f"**Department**: {emp.get('department_name', emp.get('department', 'N/A'))}\n"
    output += f"**Position**: {emp.get('position_name', emp.get('position', 'N/A'))}\n"
    output += f"**Manager**: {emp.get('manager_name', emp.get('manager', 'N/A'))}\n"
    output += f"**Join Date**: {emp.get('join_date', 'N/A')}\n"
    output += f"**Employment Type**: {emp.get('employment_type', 'N/A')}\n"
    output += f"**Status**: {emp.get('employment_status', emp.get('status', 'active'))}\n"
    if emp.get('user_id'):
        output += f"**User ID**: {emp['user_id']}\n"

    return output


@mcp.tool(name="admin_update_employee")
def update_employee(
    org_slug: str,
    employee_id: str,
    department_id: Optional[str] = None,
    position_id: Optional[str] = None,
    manager_id: Optional[str] = None,
    employment_type: Optional[str] = None,
    employment_status: Optional[str] = None,
) -> str:
    """
    Update an employee record.

    Args:
        org_slug: Organization slug
        employee_id: Employee ID
        department_id: New department ID (optional)
        position_id: New position ID (optional)
        manager_id: New manager's employee ID (optional)
        employment_type: New type (full_time, part_time, contract, intern) (optional)
        employment_status: New status (active, inactive, terminated) (optional)

    Only provided fields will be updated.
    """
    data = {}
    if department_id is not None:
        data["department"] = department_id
    if position_id is not None:
        data["position"] = position_id
    if manager_id is not None:
        data["manager"] = manager_id
    if employment_type is not None:
        data["employment_type"] = employment_type
    if employment_status is not None:
        data["employment_status"] = employment_status

    if not data:
        return "Error: No fields provided to update."

    result = base.api_request(
        "PATCH", f"/organizations/{org_slug}/employees/{employee_id}/", data=data
    )
    if "error" in result:
        return base.format_error(result)

    emp = result
    name = f"{emp.get('first_name', '')} {emp.get('last_name', '')}".strip()
    return (
        f"Employee updated!\n\n"
        f"**Name**: {name or 'N/A'}\n"
        f"**ID**: {emp.get('id')}\n"
        f"**Status**: {emp.get('employment_status', emp.get('status', 'active'))}\n"
    )


@mcp.tool(name="admin_get_direct_reports")
def get_direct_reports(org_slug: str, employee_id: str) -> str:
    """
    Get an employee's direct reports.

    Args:
        org_slug: Organization slug
        employee_id: Employee ID (manager)
    """
    result = base.api_request(
        "GET", f"/organizations/{org_slug}/employees/{employee_id}/direct-reports/"
    )
    if "error" in result:
        return base.format_error(result)

    reports = (result if isinstance(result, list) else result.get("results", []))
    if not reports:
        return "No direct reports found."

    output = f"# Direct Reports ({len(reports)})\n\n"
    for emp in reports:
        name = f"{emp.get('first_name', '')} {emp.get('last_name', '')}".strip()
        output += f"- **{name or 'Unknown'}**\n"
        output += f"  ID: {emp.get('id')}\n"
        output += f"  Position: {emp.get('position_name', emp.get('position', 'N/A'))}\n"
        output += f"  Department: {emp.get('department_name', emp.get('department', 'N/A'))}\n"

    return output


@mcp.tool(name="admin_get_management_chain")
def get_management_chain(org_slug: str, employee_id: str) -> str:
    """
    Get an employee's management chain (upward hierarchy).

    Args:
        org_slug: Organization slug
        employee_id: Employee ID

    Returns the chain from the employee up to the top-level manager.
    """
    result = base.api_request(
        "GET", f"/organizations/{org_slug}/employees/{employee_id}/management-chain/"
    )
    if "error" in result:
        return base.format_error(result)

    chain = (result if isinstance(result, list) else result.get("results", []))
    if not chain:
        return "No management chain found (top-level employee)."

    output = f"# Management Chain ({len(chain)} levels)\n\n"
    for i, mgr in enumerate(chain):
        name = f"{mgr.get('first_name', '')} {mgr.get('last_name', '')}".strip()
        indent = "  " * i
        output += f"{indent}{'-> ' if i > 0 else ''} **{name or 'Unknown'}**\n"
        output += f"{indent}   ID: {mgr.get('id')}, Position: {mgr.get('position_name', 'N/A')}\n"

    return output


# ============================================================================
# Org Chart
# ============================================================================


@mcp.tool(name="admin_get_org_chart")
def get_org_chart(org_slug: str) -> str:
    """
    Get the organization chart (hierarchy visualization).

    Args:
        org_slug: Organization slug
    """
    result = base.api_request("GET", f"/organizations/{org_slug}/org-chart/")
    if "error" in result:
        return base.format_error(result)

    return f"# Organization Chart\n\n```json\n{json.dumps(result, indent=2)}\n```"


@mcp.tool(name="admin_get_org_chart_by_department")
def get_org_chart_by_department(org_slug: str, department_id: Optional[int] = None) -> str:
    """
    Get the organization chart for a specific department.

    Args:
        org_slug: Organization slug
        department_id: Department ID to drill into

    Returns org-chart data for the selected department.
    """
    if department_id is None:
        return (
            "department_id is required for the by-department org-chart lens. "
            "Use admin_list_departments or admin_get_department_tree first to pick one."
        )

    result = base.api_request(
        "GET",
        f"/organizations/{org_slug}/org-chart/by-department/",
        params={"department_id": department_id},
    )
    if "error" in result:
        return base.format_error(result)

    return f"# Organization Chart (Department {department_id})\n\n```json\n{json.dumps(result, indent=2)}\n```"


@mcp.tool(name="admin_get_org_chart_stats")
def get_org_chart_stats(org_slug: str) -> str:
    """
    Get organization chart statistics.

    Args:
        org_slug: Organization slug

    Returns statistics like total employees, department counts, reporting depth, etc.
    """
    result = base.api_request(
        "GET", f"/organizations/{org_slug}/org-chart/stats/"
    )
    if "error" in result:
        return base.format_error(result)

    stats = result
    output = f"# Organization Statistics\n\n"
    output += f"**Total Employees**: {stats.get('total_employees', 'N/A')}\n"
    output += f"**Total Departments**: {stats.get('total_departments', 'N/A')}\n"
    output += f"**Total Teams**: {stats.get('total_teams', 'N/A')}\n"
    output += f"**Total Positions**: {stats.get('total_positions', 'N/A')}\n"
    if stats.get('max_depth') is not None:
        output += f"**Max Reporting Depth**: {stats['max_depth']}\n"
    if stats.get('avg_span') is not None:
        output += f"**Average Span of Control**: {stats['avg_span']:.1f}\n"

    # Include any additional stats as JSON
    known_keys = {
        'total_employees', 'total_departments', 'total_teams',
        'total_positions', 'max_depth', 'avg_span',
    }
    extra = {k: v for k, v in stats.items() if k not in known_keys}
    if extra:
        output += f"\n## Additional Stats\n```json\n{json.dumps(extra, indent=2)}\n```\n"

    return output


# ============================================================================
# Organization Services
# ============================================================================


@mcp.tool(name="admin_list_org_services")
def list_org_services(org_slug: str) -> str:
    """
    List services enabled for an organization.

    Args:
        org_slug: Organization slug (use the slug, not the ID)
    """
    result = base.api_request("GET", f"/organizations/{org_slug}/services/")
    if "error" in result:
        return base.format_error(result)

    raw = result if isinstance(result, list) else result.get("services", result.get("results", []))
    services = []
    for svc in raw or []:
        if isinstance(svc, str):
            slug = svc.strip()
            if slug:
                services.append({
                    "name": slug,
                    "slug": slug,
                    "service_slug": slug,
                    "is_enabled": True,
                })
        elif isinstance(svc, dict):
            services.append(svc)
    if not services:
        return "No services enabled for this organization."

    output = f"# Organization Services ({len(services)})\n\n"
    for svc in services:
        status = "[enabled]" if svc.get('is_enabled', True) else "[disabled]"
        name = svc.get('name') or svc.get('service_name') or svc.get('slug') or svc.get('service_slug') or 'Unknown'
        output += f"- {status} **{name}**\n"
        if svc.get('slug') or svc.get('service_slug'):
            output += f"  Slug: {svc.get('slug', svc.get('service_slug'))}\n"
        if svc.get('url'):
            output += f"  URL: {svc['url']}\n"

    return output


@mcp.tool(name="admin_list_org_service_members")
def list_org_service_members(
    org_slug: str,
    limit: int = 32,
    offset: int = 0,
) -> str:
    """
    List members with service access in an organization.

    Args:
        org_slug: Organization slug
        limit: Members to return (1-32; default 32)
        offset: Zero-based member offset for the next page
    """
    if not 1 <= limit <= 32:
        return "Error: limit must be between 1 and 32."
    if offset < 0:
        return "Error: offset must be zero or greater."

    result = base.api_request(
        "GET", f"/organizations/{org_slug}/services/members/",
        params={"limit": limit, "offset": offset},
    )
    if "error" in result:
        return base.format_error(result)

    # PLAT-4927: the backend returns {organization, org_services, members};
    # members carry per-member `services` (grants observed from shizuha-id) or
    # services=null + services_error when the identity lookup failed.
    if isinstance(result, dict) and "members" in result:
        members = result.get("members") or []
        org_services = result.get("org_services") or []
        count = result.get("count")
        next_offset = result.get("next_offset")
    else:
        members = (result if isinstance(result, list) else result.get("results", []))
        org_services = []
        count = None
        next_offset = None

    output = f"# Service Members — {org_slug} ({len(members)})\n\n"
    if org_services:
        output += f"Org services enabled: {', '.join(org_services)}\n\n"
    if not members:
        return output + "No members found in this organization."

    for member in members:
        label = (
            member.get('user_email')
            or member.get('username')
            or member.get('email')
            or 'Unknown'
        )
        output += f"- **{label}**\n"
        if member.get('user_id') is not None:
            output += f"  User ID: {member['user_id']}\n"
        if member.get('role'):
            output += f"  Role: {member['role']}\n"
        services = member.get('services', [])
        if services is None:
            reason = member.get('services_error', 'unavailable')
            output += f"  Services: (unknown — {reason})\n"
        else:
            svc_names = ", ".join(
                s.get('name', s.get('slug', str(s))) if isinstance(s, dict) else str(s)
                for s in services
            ) or "(none)"
            output += f"  Services: {svc_names}\n"

    if next_offset is not None:
        total = f" of {count}" if count is not None else ""
        output += (
            f"\nShowing {len(members)} member(s){total} from offset {offset}. "
            f"Call again with offset={next_offset} for the next page.\n"
        )

    return output


@mcp.tool(name="admin_add_org_service_member")
def add_org_service_member(
    org_slug: str,
    user_id: str,
    service_slugs: Optional[str] = None,
    action: str = "grant",
) -> str:
    """
    Grant (or revoke) organization service access for a member.

    Args:
        org_slug: Organization slug
        user_id: User ID to grant service access
        service_slugs: Comma-separated service slugs (optional; grants all of
            the organization's enabled services if not provided)
        action: 'grant' (default) or 'revoke'
    """
    # PLAT-4927: the backend contract is
    # MemberServiceAccessSerializer(service_slugs=[...], action='grant'|'revoke')
    # — the old body sent {"services": [...]} with no action, so every call
    # 400'd and org service membership could never be provisioned via MCP.
    if action not in ("grant", "revoke"):
        return "Error: action must be 'grant' or 'revoke'."
    if service_slugs:
        slugs = [s.strip() for s in service_slugs.split(",") if s.strip()]
    else:
        # The backend requires explicit slugs; resolve the documented
        # "all services" default to the org's currently-enabled set.
        listing = base.api_request(
            "GET", f"/organizations/{org_slug}/services/members/"
        )
        if "error" in listing:
            return base.format_error(listing)
        slugs = sorted(listing.get("org_services") or [])
        if not slugs:
            return f"Organization {org_slug} has no enabled services to {action}."

    result = base.api_request(
        "POST",
        f"/organizations/{org_slug}/services/members/{user_id}/",
        data={"service_slugs": slugs, "action": action},
    )
    if "error" in result:
        return base.format_error(result)

    verb = "granted" if action == "grant" else "revoked"
    return (
        f"User {user_id} {verb} organization service access: {', '.join(slugs)}."
    )


# ============================================================================
# Superuser - Users
# ============================================================================


@mcp.tool(name="admin_su_list_users")
def su_list_users(
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    is_staff: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """
    List all users (superuser only).

    Args:
        search: Search in username, email, name (optional)
        is_active: Filter by active status (optional)
        is_staff: Filter by staff status (optional)
        limit: Max results per page (1-100, default: 50)
        offset: Pagination offset (default: 0)

    Requires: Superuser authentication.
    """
    params = {
        "limit": min(max(limit, 1), 100),
        "offset": max(offset, 0),
    }
    if search:
        params["search"] = search
    if is_active is not None:
        params["is_active"] = "true" if is_active else "false"
    if is_staff is not None:
        params["is_staff"] = "true" if is_staff else "false"

    result = base.api_request("GET", "/superuser/users/", params=params)
    if "error" in result:
        return base.format_error(result)

    count = result.get("count", 0)
    users = (result if isinstance(result, list) else result.get("results", []))

    output = f"# Users ({len(users)} of {count})\n\n"
    if not users:
        output += "No users found.\n"
        return output

    for user in users:
        flags = []
        if user.get("is_superuser"):
            flags.append("superuser")
        if user.get("is_staff"):
            flags.append("staff")
        if not user.get("is_active", True):
            flags.append("inactive")

        flag_str = f" [{', '.join(flags)}]" if flags else ""
        output += f"- **{user.get('username')}** ({user.get('email')}){flag_str}\n"
        output += f"  UID: {user.get('uid', user.get('id'))}\n"
        name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
        if name:
            output += f"  Name: {name}\n"
        if user.get("date_joined"):
            output += f"  Joined: {user['date_joined']}\n"
        output += "\n"

    return output


@mcp.tool(name="admin_su_create_user")
def su_create_user(
    username: str,
    email: str,
    password: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    is_staff: bool = False,
    is_superuser: bool = False,
    is_active: bool = True,
) -> str:
    """
    Create a new user (superuser only).

    Args:
        username: Unique username
        email: Email address (must be unique)
        password: Password
        first_name: First name (optional)
        last_name: Last name (optional)
        is_staff: Staff access (default: False)
        is_superuser: Superuser access (default: False)
        is_active: Account active (default: True)

    Requires: Superuser authentication.
    """
    data = {
        "username": username,
        "email": email,
        "password": password,
        "is_staff": is_staff,
        "is_superuser": is_superuser,
        "is_active": is_active,
    }
    if first_name:
        data["first_name"] = first_name
    if last_name:
        data["last_name"] = last_name

    result = base.api_request("POST", "/superuser/users/create/", data=data)
    if "error" in result:
        return base.format_error(result)

    user = result
    return (
        f"User created!\n\n"
        f"**UID**: {user.get('uid', user.get('id'))}\n"
        f"**Username**: {user.get('username')}\n"
        f"**Email**: {user.get('email')}\n"
        f"**Staff**: {user.get('is_staff', False)}\n"
        f"**Superuser**: {user.get('is_superuser', False)}\n"
        f"**Active**: {user.get('is_active', True)}\n"
    )


@mcp.tool(name="admin_su_get_user")
def su_get_user(uid: str) -> str:
    """
    Get detailed user information (superuser only).

    Args:
        uid: User UID

    Requires: Superuser authentication.
    """
    result = base.api_request("GET", f"/superuser/users/{uid}/")
    if "error" in result:
        return base.format_error(result)

    user = result
    output = f"# User: {user.get('username')}\n\n"
    output += f"**UID**: {user.get('uid', user.get('id'))}\n"
    output += f"**Email**: {user.get('email')}\n"
    output += f"**Name**: {user.get('first_name', '')} {user.get('last_name', '')}\n"
    output += f"**Staff**: {user.get('is_staff', False)}\n"
    output += f"**Superuser**: {user.get('is_superuser', False)}\n"
    output += f"**Active**: {user.get('is_active', True)}\n"
    output += f"**Joined**: {user.get('date_joined', 'N/A')}\n"
    output += f"**Last Login**: {user.get('last_login', 'N/A')}\n"

    orgs = user.get('organizations', [])
    if orgs:
        output += f"\n## Organizations\n"
        for org in orgs:
            output += f"- {org.get('name', org.get('slug', str(org)))}\n"

    return output


@mcp.tool(name="admin_su_update_user")
def su_update_user(
    uid: str,
    username: Optional[str] = None,
    email: Optional[str] = None,
    password: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    is_staff: Optional[bool] = None,
    is_superuser: Optional[bool] = None,
    is_active: Optional[bool] = None,
) -> str:
    """
    Update a user (superuser only).

    Args:
        uid: User UID
        username: New username (optional)
        email: New email (optional)
        password: New password (optional)
        first_name: New first name (optional)
        last_name: New last name (optional)
        is_staff: New staff status (optional)
        is_superuser: New superuser status (optional)
        is_active: New active status (optional)

    Only provided fields will be updated.
    Requires: Superuser authentication.
    """
    data = {}
    if username is not None:
        data["username"] = username
    if email is not None:
        data["email"] = email
    if password is not None:
        data["password"] = password
    if first_name is not None:
        data["first_name"] = first_name
    if last_name is not None:
        data["last_name"] = last_name
    if is_staff is not None:
        data["is_staff"] = is_staff
    if is_superuser is not None:
        data["is_superuser"] = is_superuser
    if is_active is not None:
        data["is_active"] = is_active

    if not data:
        return "Error: No fields provided to update."

    result = base.api_request("PATCH", f"/superuser/users/{uid}/update/", data=data)
    if "error" in result:
        return base.format_error(result)

    user = result
    return (
        f"User updated!\n\n"
        f"**UID**: {user.get('uid', user.get('id'))}\n"
        f"**Username**: {user.get('username')}\n"
        f"**Email**: {user.get('email')}\n"
        f"**Active**: {user.get('is_active', True)}\n"
    )


@mcp.tool(name="admin_su_delete_user")
def su_delete_user(uid: str) -> str:
    """
    Delete a user (superuser only).

    Args:
        uid: User UID

    Warning: This permanently deletes the user account and all associated data.
    Requires: Superuser authentication.
    """
    result = base.api_request("DELETE", f"/superuser/users/{uid}/delete/")
    if "error" in result:
        return base.format_error(result)

    return f"User {uid} deleted successfully."


@mcp.tool(name="admin_su_get_user_services")
def su_get_user_services(uid: str) -> str:
    """
    Get services available to a user (superuser only).

    Args:
        uid: User UID

    Requires: Superuser authentication.
    """
    result = base.api_request("GET", f"/superuser/users/{uid}/services/")
    if "error" in result:
        return base.format_error(result)

    services = (result if isinstance(result, list) else result.get("results", []))
    if not services:
        return "No services found for this user."

    output = f"# User Services ({len(services)})\n\n"
    for svc in services:
        status = "[enabled]" if svc.get('is_enabled', True) else "[disabled]"
        output += f"- {status} **{svc.get('name', svc.get('service_name', 'Unknown'))}**\n"
        if svc.get('slug') or svc.get('service_slug'):
            output += f"  Slug: {svc.get('slug', svc.get('service_slug'))}\n"

    return output


@mcp.tool(name="admin_su_set_user_services")
def su_set_user_services(
    uid: str,
    service_slugs: str,
    action: str = "grant",
) -> str:
    """
    Set services for a user (superuser only).

    Args:
        uid: User UID
        service_slugs: Comma-separated service slugs to grant/revoke
        action: 'grant' (default) or 'revoke'

    Requires: Superuser authentication.
    """
    # PLAT-5096: the backend AdminUserServiceGrantSerializer expects
    # {"service_slugs": [...], "action": 'grant'|'revoke'} — the legacy
    # {"services": [...]} body (no action) 400'd every call, so superuser
    # service-set via MCP silently no-opped. Mirror the PLAT-4927 org-member fix.
    if action not in ("grant", "revoke"):
        return "Error: action must be 'grant' or 'revoke'."
    slugs = [s.strip() for s in service_slugs.split(",") if s.strip()]
    if not slugs:
        return "Error: at least one service slug is required."

    data = {"service_slugs": slugs, "action": action}

    result = base.api_request("POST", f"/superuser/users/{uid}/services/", data=data)
    if "error" in result:
        return base.format_error(result)

    verb = "granted" if action == "grant" else "revoked"
    return f"Services {verb} for user {uid}: {', '.join(slugs)}."


# ============================================================================
# Superuser - Approvals
# ============================================================================


@mcp.tool(name="admin_su_list_pending_users")
def su_list_pending_users() -> str:
    """
    List users pending approval (superuser only).

    Returns users who have registered but not yet been approved.
    Requires: Superuser authentication.
    """
    result = base.api_request("GET", "/superuser/users/pending/")
    if "error" in result:
        return base.format_error(result)

    users = (result if isinstance(result, list) else result.get("results", []))
    if not users:
        return "No pending users."

    output = f"# Pending Users ({len(users)})\n\n"
    for user in users:
        output += f"- **{user.get('username')}** ({user.get('email')})\n"
        output += f"  UID: {user.get('uid', user.get('id'))}\n"
        name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
        if name:
            output += f"  Name: {name}\n"
        output += f"  Registered: {user.get('date_joined', 'N/A')}\n\n"

    return output


@mcp.tool(name="admin_su_get_pending_count")
def su_get_pending_count() -> str:
    """
    Get the count of users pending approval (superuser only).

    Requires: Superuser authentication.
    """
    result = base.api_request("GET", "/superuser/users/pending/count/")
    if "error" in result:
        return base.format_error(result)

    count = result.get("count", 0)
    return f"**Pending Approvals**: {count}"


@mcp.tool(name="admin_su_approve_user")
def su_approve_user(uid: str, approved: bool = True, reason: Optional[str] = None) -> str:
    """
    Approve (or deny) a pending user (superuser only).

    Args:
        uid: User UID to approve/deny
        approved: True to approve (default), False to deny
        reason: Optional review note for the decision

    Requires: Superuser authentication.
    """
    # ID-38: this endpoint proxies straight to the id-service approve endpoint,
    # whose UserApprovalReviewSerializer requires `status` ('approved'|'denied')
    # + optional `review_note`. Sending no body 400'd ("status: This field is
    # required"), so no superuser could approve a pending registration via MCP.
    data = {"status": "approved" if approved else "denied"}
    if reason:
        data["review_note"] = reason

    result = base.api_request("PATCH", f"/superuser/users/{uid}/approve/", data=data)
    if "error" in result:
        return base.format_error(result)

    action = "approved" if approved else "denied"
    return f"User {uid} {action} successfully."


# ============================================================================
# Superuser - Organizations
# ============================================================================


@mcp.tool(name="admin_su_list_organizations")
def su_list_organizations(
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """
    List all organizations (superuser only).

    Args:
        search: Search in name, slug (optional)
        limit: Max results per page (default: 50)
        offset: Pagination offset (default: 0)

    Requires: Superuser authentication.
    """
    params = {
        "limit": min(max(limit, 1), 100),
        "offset": max(offset, 0),
    }
    if search:
        params["search"] = search

    result = base.api_request("GET", "/superuser/organizations/", params=params)
    if "error" in result:
        return base.format_error(result)

    count = result.get("count", 0)
    orgs = (result if isinstance(result, list) else result.get("results", []))

    output = f"# All Organizations ({len(orgs)} of {count})\n\n"
    if not orgs:
        output += "No organizations found.\n"
        return output

    for org in orgs:
        output += f"- **{org.get('name')}** ({org.get('slug')})\n"
        output += f"  Plan: {org.get('plan', 'free')}\n"
        output += f"  Members: {org.get('member_count', 'N/A')}\n"
        if org.get('owner_email') or org.get('owner'):
            output += f"  Owner: {org.get('owner_email', org.get('owner'))}\n"
        output += "\n"

    return output


@mcp.tool(name="admin_su_create_organization")
def su_create_organization(
    name: str,
    slug: str,
    owner_id: Optional[str] = None,
    plan: str = "free",
    description: str = "",
) -> str:
    """
    Create an organization (superuser only).

    Args:
        name: Organization name
        slug: URL-friendly slug (unique)
        owner_id: User ID of owner (optional)
        plan: Plan tier (free, pro, enterprise) (default: free)
        description: Description (optional)

    Requires: Superuser authentication.
    """
    data = {
        "name": name,
        "slug": slug,
        "plan": plan,
    }
    if owner_id:
        data["owner"] = owner_id
    if description:
        data["description"] = description

    result = base.api_request("POST", "/superuser/organizations/create/", data=data)
    if "error" in result:
        return base.format_error(result)

    org = result
    return (
        f"Organization created!\n\n"
        f"**Name**: {org.get('name')}\n"
        f"**Slug**: {org.get('slug')}\n"
        f"**Plan**: {org.get('plan', 'free')}\n"
    )


@mcp.tool(name="admin_su_update_organization")
def su_update_organization(
    slug: str,
    name: Optional[str] = None,
    plan: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> str:
    """
    Update an organization (superuser only).

    Args:
        slug: Organization slug
        name: New name (optional)
        plan: New plan tier (optional)
        description: New description (optional)
        is_active: New active status (optional)

    Only provided fields will be updated.
    Requires: Superuser authentication.
    """
    data = {}
    if name is not None:
        data["name"] = name
    if plan is not None:
        data["plan"] = plan
    if description is not None:
        data["description"] = description
    if is_active is not None:
        data["is_active"] = is_active

    if not data:
        return "Error: No fields provided to update."

    result = base.api_request(
        "PATCH", f"/superuser/organizations/{slug}/update/", data=data
    )
    if "error" in result:
        return base.format_error(result)

    org = result
    return (
        f"Organization updated!\n\n"
        f"**Name**: {org.get('name')}\n"
        f"**Slug**: {org.get('slug')}\n"
        f"**Plan**: {org.get('plan', 'free')}\n"
    )


@mcp.tool(name="admin_su_get_organization")
def su_get_organization(slug: str) -> str:
    """
    Get detailed organization information (superuser only).

    Args:
        slug: Organization slug

    Requires: Superuser authentication.
    """
    result = base.api_request(
        "GET", f"/superuser/organizations/{slug}/detail/"
    )
    if "error" in result:
        return base.format_error(result)

    org = result
    output = f"# {org.get('name')}\n\n"
    output += f"**Slug**: {org.get('slug')}\n"
    output += f"**Plan**: {org.get('plan', 'free')}\n"
    output += f"**Owner**: {org.get('owner_email', org.get('owner', 'N/A'))}\n"
    output += f"**Members**: {org.get('member_count', 'N/A')}\n"
    output += f"**Active**: {org.get('is_active', True)}\n"
    output += f"**Created**: {org.get('created_at', 'N/A')}\n"
    if org.get('description'):
        output += f"\n## Description\n{org['description']}\n"
    if org.get('settings'):
        output += f"\n## Settings\n```json\n{json.dumps(org['settings'], indent=2)}\n```\n"

    services = org.get('services', [])
    if services:
        output += f"\n## Services ({len(services)})\n"
        for svc in services:
            svc_name = svc.get('name', svc.get('slug', str(svc))) if isinstance(svc, dict) else str(svc)
            output += f"- {svc_name}\n"

    return output


# ============================================================================
# Superuser - Services
# ============================================================================


@mcp.tool(name="admin_su_list_services")
def su_list_services() -> str:
    """
    List all available services (superuser only).

    Returns the complete list of services that can be assigned to organizations.
    Requires: Superuser authentication.
    """
    result = base.api_request("GET", "/superuser/services/")
    if "error" in result:
        return base.format_error(result)

    services = (result if isinstance(result, list) else result.get("results", []))
    if not services:
        return "No services found."

    output = f"# Services ({len(services)})\n\n"
    for svc in services:
        output += f"- **{svc.get('name', 'Unknown')}**\n"
        output += f"  Slug: {svc.get('slug', 'N/A')}\n"
        if svc.get('description'):
            output += f"  Description: {svc['description'][:100]}\n"
        if svc.get('url'):
            output += f"  URL: {svc['url']}\n"
        output += "\n"

    return output


@mcp.tool(name="admin_su_list_org_services")
def su_list_org_services(slug: str) -> str:
    """
    List services assigned to an organization (superuser only).

    Args:
        slug: Organization slug

    Requires: Superuser authentication.
    """
    result = base.api_request(
        "GET", f"/superuser/organizations/{slug}/services/"
    )
    if "error" in result:
        return base.format_error(result)

    services = (result if isinstance(result, list) else result.get("results", []))
    if not services:
        return "No services assigned to this organization."

    output = f"# Organization Services ({len(services)})\n\n"
    for svc in services:
        status = "[enabled]" if svc.get('is_enabled', True) else "[disabled]"
        output += f"- {status} **{svc.get('name', svc.get('service_name', 'Unknown'))}**\n"
        if svc.get('slug') or svc.get('service_slug'):
            output += f"  Slug: {svc.get('slug', svc.get('service_slug'))}\n"

    return output


@mcp.tool(name="admin_su_assign_org_service")
def su_assign_org_service(
    slug: str,
    service_slug: str,
    is_enabled: bool = True,
) -> str:
    """
    Assign a service to an organization (superuser only).

    Args:
        slug: Organization slug
        service_slug: Service slug to assign
        is_enabled: Whether to enable the service (default: True)

    Requires: Superuser authentication.
    """
    data = {"service": service_slug, "is_enabled": is_enabled}

    result = base.api_request(
        "POST", f"/superuser/organizations/{slug}/services/", data=data
    )
    if "error" in result:
        return base.format_error(result)

    action = "assigned and enabled" if is_enabled else "assigned (disabled)"
    return f"Service '{service_slug}' {action} for organization '{slug}'."


# ============================================================================
# Superuser - Requests
# ============================================================================


@mcp.tool(name="admin_su_list_requests")
def su_list_requests(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """
    List service requests (superuser only).

    Args:
        status: Filter by status (pending, approved, rejected) (optional)
        limit: Max results per page (default: 50)
        offset: Pagination offset (default: 0)

    Requires: Superuser authentication.
    """
    params = {
        "limit": min(max(limit, 1), 100),
        "offset": max(offset, 0),
    }
    if status:
        params["status"] = status

    result = base.api_request("GET", "/superuser/requests/", params=params)
    if "error" in result:
        return base.format_error(result)

    count = result.get("count", 0)
    requests_list = (result if isinstance(result, list) else result.get("results", []))

    output = f"# Service Requests ({len(requests_list)} of {count})\n\n"
    if not requests_list:
        output += "No requests found.\n"
        return output

    for req in requests_list:
        status_badge = f"[{req.get('status', 'unknown')}]"
        output += f"- {status_badge} **{req.get('service_name', req.get('service', 'Unknown'))}**\n"
        output += f"  ID: {req.get('id')}\n"
        output += f"  Requested by: {req.get('user_email', req.get('user', 'Unknown'))}\n"
        output += f"  Organization: {req.get('organization_name', req.get('organization', 'N/A'))}\n"
        if req.get('reason'):
            output += f"  Reason: {req['reason'][:100]}\n"
        output += f"  Created: {req.get('created_at', 'N/A')}\n\n"

    return output


@mcp.tool(name="admin_su_update_request")
def su_update_request(
    request_id: str,
    status: str,
    notes: Optional[str] = None,
) -> str:
    """
    Update a service request (approve/reject) (superuser only).

    Args:
        request_id: Request ID
        status: New status (approved, rejected)
        notes: Optional notes for the decision

    Requires: Superuser authentication.
    """
    data = {"status": status}
    if notes:
        data["notes"] = notes

    result = base.api_request(
        "PATCH", f"/superuser/requests/{request_id}/", data=data
    )
    if "error" in result:
        return base.format_error(result)

    return f"Request {request_id} updated to '{status}'."


# ============================================================================
# Superuser - System
# ============================================================================


@mcp.tool(name="admin_su_system_health")
def su_system_health() -> str:
    """
    Get system health status (superuser only).

    Returns health check results for all services and infrastructure.
    Requires: Superuser authentication.
    """
    result = base.api_request("GET", "/superuser/system/health/")
    if "error" in result:
        return base.format_error(result)

    output = f"# System Health\n\n"
    output += f"**Status**: {result.get('status', 'unknown')}\n"
    output += f"**Timestamp**: {result.get('timestamp', 'N/A')}\n"

    services = result.get('services', result.get('checks', {}))
    if isinstance(services, dict):
        output += f"\n## Service Status\n"
        for svc_name, svc_status in services.items():
            if isinstance(svc_status, dict):
                status_str = svc_status.get('status', 'unknown')
                output += f"- **{svc_name}**: {status_str}\n"
                if svc_status.get('latency'):
                    output += f"  Latency: {svc_status['latency']}ms\n"
                if svc_status.get('error'):
                    output += f"  Error: {svc_status['error']}\n"
            else:
                output += f"- **{svc_name}**: {svc_status}\n"
    elif isinstance(services, list):
        output += f"\n## Service Status\n"
        for svc in services:
            output += f"- **{svc.get('name', 'Unknown')}**: {svc.get('status', 'unknown')}\n"

    # Include any extra top-level keys
    known_keys = {'status', 'timestamp', 'services', 'checks'}
    extra = {k: v for k, v in result.items() if k not in known_keys}
    if extra:
        output += f"\n## Additional Info\n```json\n{json.dumps(extra, indent=2)}\n```\n"

    return output


@mcp.tool(name="admin_su_dashboard")
def su_dashboard() -> str:
    """
    Get the superuser dashboard overview (superuser only).

    Returns key metrics: user counts, organization counts, service usage, etc.
    Requires: Superuser authentication.
    """
    result = base.api_request("GET", "/superuser/dashboard/")
    if "error" in result:
        return base.format_error(result)

    output = f"# Admin Dashboard\n\n"

    # User metrics
    output += f"## Users\n"
    output += f"**Total Users**: {result.get('total_users', 'N/A')}\n"
    output += f"**Active Users**: {result.get('active_users', 'N/A')}\n"
    output += f"**Pending Approvals**: {result.get('pending_users', result.get('pending_approvals', 'N/A'))}\n"
    output += f"**Staff Users**: {result.get('staff_users', 'N/A')}\n\n"

    # Organization metrics
    output += f"## Organizations\n"
    output += f"**Total**: {result.get('total_organizations', result.get('total_orgs', 'N/A'))}\n"
    output += f"**Active**: {result.get('active_organizations', result.get('active_orgs', 'N/A'))}\n\n"

    # Service metrics
    if result.get('services') or result.get('total_services'):
        output += f"## Services\n"
        output += f"**Total Services**: {result.get('total_services', 'N/A')}\n"

    # Recent activity
    recent = result.get('recent_activity', result.get('recent_users', []))
    if recent and isinstance(recent, list):
        output += f"\n## Recent Activity\n"
        for item in recent[:10]:
            if isinstance(item, dict):
                output += f"- {item.get('description', item.get('username', json.dumps(item)))}\n"
            else:
                output += f"- {item}\n"

    # Include any extra data not covered
    known_keys = {
        'total_users', 'active_users', 'pending_users', 'pending_approvals',
        'staff_users', 'total_organizations', 'total_orgs',
        'active_organizations', 'active_orgs', 'services', 'total_services',
        'recent_activity', 'recent_users',
    }
    extra = {k: v for k, v in result.items() if k not in known_keys}
    if extra:
        output += f"\n## Additional Metrics\n```json\n{json.dumps(extra, indent=2)}\n```\n"

    return output


@mcp.tool(name="company_os")
def company_os(org: str = "") -> str:
    """Read-only Company OS for an organization: mission, vision, strategic bets,
    values summary, and a link to the long-form wiki handbook. Available to all
    agents (PLAT-434).

    Args:
        org: Organization slug. Defaults to the org-wide Global Company OS,
            whose slug is resolved from the GLOBAL_ORG_SLUG env var (fallback
            "global") so deployments where Global's slug differs still resolve.
    """
    org = org or os.environ.get("GLOBAL_ORG_SLUG", "global")
    result = base.api_request("GET", f"/organizations/{org}/company-os/")
    if "error" in result:
        return base.format_error(result)

    output = f"# Company OS — {result.get('name', org)}\n\n"
    if result.get('mission'):
        output += f"## Mission\n{result['mission']}\n\n"
    if result.get('vision'):
        output += f"## Vision\n{result['vision']}\n\n"
    bets = result.get('strategic_bets') or []
    if bets:
        output += "## Strategic bets\n"
        for b in bets:
            output += (f"- {b}\n" if isinstance(b, str) else f"- {json.dumps(b)}\n")
        output += "\n"
    if result.get('values_summary'):
        output += f"## Values\n{result['values_summary']}\n\n"
    if result.get('handbook_url'):
        output += f"**Handbook (long-form):** {result['handbook_url']}\n"
    if not any(result.get(k) for k in ('mission', 'vision', 'strategic_bets', 'values_summary', 'handbook_url')):
        output += "_No Company OS data set for this organization yet._\n"
    return output


def main():
    """Run the MCP server."""
    run_mcp_server(mcp, base)


if __name__ == "__main__":
    main()
