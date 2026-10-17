import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Tree, TreeNode } from 'react-organizational-chart'
import {
  ZoomIn, ZoomOut, Maximize2, Download, User, Users, Building2,
  ChevronDown, ChevronRight, ChevronUp, Bot,
} from 'lucide-react'
import { useAdmin } from '../contexts/AdminContext'
import { orgChartApi } from '../services/api'
import AgentAvatar from '../components/shared/AgentAvatar'
import StatusBadge from '../components/shared/StatusBadge'
import AgentTierBadge from '../components/shared/AgentTierBadge'
import clsx from 'clsx'

// Map employee model_tier + is_agent flag → AgentTierBadge tier value.
function tierFor(employee) {
  return employee.model_tier || (employee.is_agent ? 'shizuha' : 'human')
}

// Map availability_status (snapshot or StatusBadge-native values) → StatusBadge status.
function toStatus(availability_status) {
  if (!availability_status) return 'unknown'
  if (availability_status === 'available')   return 'active'
  if (availability_status === 'unavailable') return 'stopped'
  // Pass through StatusBadge-native values directly.
  const native = ['active', 'idle', 'wedged', 'stopped', 'unknown']
  return native.includes(availability_status) ? availability_status : 'unknown'
}

// Compact badge row rendered on every node (PLAT-526 F3).
function NodeBadgeRow({ employee }) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap mt-1.5">
      <StatusBadge status={toStatus(employee.availability_status)} size="sm" />
      {employee.is_agent
        ? <span className="inline-flex items-center gap-0.5 text-[10px] text-blue-600 dark:text-blue-400"><Bot className="h-2.5 w-2.5" /> agent</span>
        : <span className="inline-flex items-center gap-0.5 text-[10px] text-amber-600 dark:text-amber-400"><User className="h-2.5 w-2.5" /> human</span>
      }
      <AgentTierBadge tier={tierFor(employee)} size="sm" />
    </div>
  )
}

// Expanded detail card shown on click (PLAT-526 F3 full card + PLAT-527 F4 progress strip).
function NodeFullCard({ employee, workload }) {
  const wl = workload || {}
  const total = (wl.open ?? 0) + (wl.in_progress ?? 0) + (wl.blocked ?? 0) + (wl.in_review ?? 0)
  return (
    <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-700 space-y-2 text-xs text-left">
      <div className="flex items-center gap-2 flex-wrap">
        <StatusBadge status={toStatus(employee.availability_status)} size="sm" show_label />
        <AgentTierBadge tier={tierFor(employee)} size="sm" show_label />
      </div>
      {employee.email && (
        <div className="text-gray-400 font-mono text-[10px] truncate">{employee.email}</div>
      )}
      {employee.last_active && (
        <div className="text-gray-400 text-[10px]">
          Last active: {new Date(employee.last_active).toLocaleString()}
        </div>
      )}
      {/* PLAT-527 (F4): progress at-a-glance — total tasks / in-progress / done-30d / overdue */}
      <div className="flex items-center gap-1.5 text-[10px] text-gray-500 dark:text-gray-400 pt-0.5 flex-wrap">
        <span><span className="font-bold text-gray-700 dark:text-gray-300">{total}</span> tasks</span>
        <span>·</span>
        <span><span className="font-bold text-amber-600 dark:text-amber-400">{wl.in_progress ?? 0}</span> in prog</span>
        <span>·</span>
        <span><span className="font-bold text-green-600 dark:text-green-400">{wl.completed ?? 0}</span> done·30d</span>
        <span>·</span>
        <span className={clsx((wl.overdue ?? 0) > 0 && 'text-red-600 dark:text-red-400 font-semibold')}>
          {wl.overdue ?? 0} overdue
        </span>
      </div>
    </div>
  )
}

// PLAT-684 (F4): data-driven activity beacon. Pulses ONLY when there is live
// in-progress work; escalates to red when the node carries overdue tasks; renders
// nothing when idle, so motion === active work at a glance. `motion-safe:` so
// prefers-reduced-motion users get a static dot (a11y).
function ActivityBeacon({ workload, size = 'sm' }) {
  const wl = workload || {}
  const inProg = wl.in_progress ?? 0
  const overdue = wl.overdue ?? 0
  if (inProg <= 0 && overdue <= 0) return null
  const danger = overdue > 0
  const dot = danger ? 'bg-red-500' : 'bg-amber-500'
  const dim = size === 'lg' ? 'h-2.5 w-2.5' : 'h-2 w-2'
  const label = `${inProg} in progress${overdue ? `, ${overdue} overdue` : ''}`
  return (
    <span className="relative inline-flex items-center shrink-0" title={label} aria-label={label}>
      <span className="relative inline-flex">
        {inProg > 0 && (
          <span className={clsx('absolute inline-flex rounded-full motion-safe:animate-activity-ring', dot, dim)} />
        )}
        <span className={clsx('relative inline-flex rounded-full', dot, dim)} />
      </span>
      <span className={clsx('ml-1 text-[10px] font-semibold tabular-nums', danger ? 'text-red-600 dark:text-red-400' : 'text-amber-600 dark:text-amber-400')}>
        {inProg || overdue}
      </span>
    </span>
  )
}

// PLAT-684 (F4): task-flow strip — visualises the in-flight pipeline
// (in-progress → in-review → blocked) for a team/dept. The connector animates
// ONLY while work is actually in flight (sum > 0); steady when the lane is quiet.
const FLOW_STAGES = [
  { key: 'in_progress', label: 'in prog', cls: 'bg-amber-500' },
  { key: 'in_review',   label: 'review',  cls: 'bg-sky-500' },
  { key: 'blocked',     label: 'blocked', cls: 'bg-red-500' },
]
function StageFlow({ workload }) {
  const wl = workload || {}
  const inFlight = FLOW_STAGES.reduce((n, s) => n + (wl[s.key] ?? 0), 0)
  if (inFlight <= 0) return null
  return (
    <div className="flex items-center gap-1 mt-1.5" title="work in flight: in-progress → review → blocked">
      {FLOW_STAGES.map((s, i) => {
        const n = wl[s.key] ?? 0
        return (
          <div key={s.key} className="flex items-center gap-1">
            <span className={clsx('inline-flex items-center justify-center min-w-[1rem] h-4 px-1 rounded text-[9px] font-bold text-white tabular-nums',
              n > 0 ? s.cls : 'bg-gray-300 dark:bg-gray-600')}>{n}</span>
            {i < FLOW_STAGES.length - 1 && (
              <span
                className="h-[3px] w-5 rounded-full bg-[length:8px_3px] bg-repeat-x motion-safe:animate-flow-dash"
                style={{ backgroundImage: 'linear-gradient(90deg, currentColor 50%, transparent 50%)' }}
                aria-hidden
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

function EmployeeNode({ employee, expanded, onToggle, workload }) {
  const [detailsOpen, setDetailsOpen] = useState(false)
  const hasReports = employee.direct_reports?.length > 0
  const name = employee.name || employee.email?.split('@')[0] || 'Unknown'
  const wl = workload?.[employee.email] || null

  return (
    <div className="inline-block">
      <div
        className={clsx(
          'bg-white dark:bg-gray-800 rounded-xl shadow-md border-2 min-w-[200px] transition-all hover:shadow-lg overflow-hidden',
          hasReports ? 'border-primary-300 dark:border-primary-700' : 'border-gray-200 dark:border-gray-700'
        )}
      >
        {/* Main card — click toggles detail expansion */}
        <button
          type="button"
          className="w-full text-left p-4"
          onClick={() => setDetailsOpen((o) => !o)}
        >
          <div className="flex items-center gap-3">
            <AgentAvatar display_name={name} src={employee.avatar_url} size="lg" />
            <div className="text-left min-w-0 flex-1">
              <div className="flex items-center justify-between gap-1">
                <div className="font-semibold text-sm truncate">{name}</div>
                <div className="flex items-center gap-1 shrink-0">
                  <ActivityBeacon workload={wl} size="lg" />
                  {detailsOpen
                    ? <ChevronUp className="h-3.5 w-3.5 text-gray-400" />
                    : <ChevronDown className="h-3.5 w-3.5 text-gray-400" />
                  }
                </div>
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{employee.title || 'No title'}</div>
              {employee.department && (
                <div className="text-xs text-gray-400 dark:text-gray-500 flex items-center gap-1 mt-1">
                  <Building2 className="h-3 w-3" />
                  {employee.department}
                </div>
              )}
              <NodeBadgeRow employee={employee} />
            </div>
          </div>
          {detailsOpen && <NodeFullCard employee={employee} workload={wl} />}
        </button>

        {/* Reports toggle — separate click target so it doesn't interfere with detail expand */}
        {hasReports && (
          <div
            className="flex items-center justify-center px-4 py-2 border-t border-gray-100 dark:border-gray-700 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50"
            onClick={onToggle}
          >
            <span className="text-xs text-gray-500 flex items-center gap-1">
              <Users className="h-3 w-3" />
              {employee.direct_reports.length} reports
              {expanded ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

function OrgTreeNode({ employee, expandedNodes, toggleNode, workload }) {
  const isExpanded = expandedNodes.has(employee.id)
  const hasReports = employee.direct_reports?.length > 0

  return (
    <TreeNode
      label={
        <EmployeeNode
          employee={employee}
          expanded={isExpanded}
          onToggle={() => toggleNode(employee.id)}
          workload={workload}
        />
      }
    >
      {isExpanded && hasReports && employee.direct_reports.map((report) => (
        <OrgTreeNode
          key={report.id}
          employee={report}
          expandedNodes={expandedNodes}
          toggleNode={toggleNode}
          workload={workload}
        />
      ))}
    </TreeNode>
  )
}

// PLAT-684 (F4): nested child row (compact indented list inside an expanded card).
function DeptChildRow({ dept, deptWorkload, level }) {
  const wl = deptWorkload[String(dept.id)] || {}
  const active = (wl.open ?? 0) + (wl.in_progress ?? 0) + (wl.in_review ?? 0) + (wl.blocked ?? 0)
  return (
    <div>
      <div className="flex items-center gap-1.5 py-0.5 text-xs" style={{ marginLeft: level * 12 }}>
        <Building2 className="h-3 w-3 text-primary-400 shrink-0" />
        <span className="truncate">{dept.name}</span>
        <span className="ml-auto flex items-center gap-1.5 text-gray-500">
          <span>{dept.member_count || 0}m</span>
          {active > 0 && <span className="text-gray-600 dark:text-gray-300 font-medium">{active}t</span>}
          <ActivityBeacon workload={wl} />
        </span>
      </div>
      {dept.children?.map((c) => (
        <DeptChildRow key={c.id} dept={c} deptWorkload={deptWorkload} level={level + 1} />
      ))}
    </div>
  )
}

// PLAT-684 (F4): compact team card for the density grid.
function TeamCard({ dept, deptWorkload }) {
  const [open, setOpen] = useState(false)
  const wl = deptWorkload[String(dept.id)] || {}
  const hasChildren = dept.children?.length > 0
  const active = (wl.open ?? 0) + (wl.in_progress ?? 0) + (wl.in_review ?? 0) + (wl.blocked ?? 0)
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-3 flex flex-col min-w-0 hover:shadow-md transition-shadow">
      <div className="flex items-center gap-1.5 min-w-0">
        <Building2 className="h-4 w-4 text-primary-500 shrink-0" />
        <span className="font-semibold text-sm truncate">{dept.name}</span>
        {dept.code && <span className="text-[10px] text-gray-400 shrink-0">({dept.code})</span>}
        <span className="ml-auto"><ActivityBeacon workload={wl} size="lg" /></span>
      </div>
      <div className="flex items-center gap-2 mt-1.5 text-[11px] text-gray-500 dark:text-gray-400 flex-wrap">
        <span>{dept.member_count || 0} members</span>
        <span>·</span>
        <span><span className="font-bold text-gray-700 dark:text-gray-300">{active}</span> active</span>
        <span className="text-green-600">{wl.completed ?? 0} done·30d</span>
      </div>
      <StageFlow workload={wl} />
      {hasChildren && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="mt-2 pt-2 border-t border-gray-100 dark:border-gray-700 flex items-center gap-1 text-[11px] text-gray-500 hover:text-primary-600"
        >
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          {dept.children.length} sub-team{dept.children.length === 1 ? '' : 's'}
        </button>
      )}
      {open && hasChildren && (
        <div className="mt-1.5 space-y-0.5">
          {dept.children.map((c) => (
            <DeptChildRow key={c.id} dept={c} deptWorkload={deptWorkload} level={0} />
          ))}
        </div>
      )}
    </div>
  )
}

function DepartmentView({ departments, deptWorkload = {} }) {
  if (!departments?.length) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
        <p className="text-gray-500 text-center py-4">No departments yet</p>
      </div>
    )
  }
  // Responsive density grid: auto-fills as many compact team cards per row as fit,
  // so 10+ teams are legible on one screen and the layout scales as teams grow.
  return (
    <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(230px,1fr))]">
      {departments.map((dept) => (
        <TeamCard key={dept.id} dept={dept} deptWorkload={deptWorkload} />
      ))}
    </div>
  )
}

export default function OrgChart() {
  const { currentOrganization, organizations, loading: orgsLoading, error: orgsError, isStaff } = useAdmin()
  const [viewMode, setViewMode] = useState('hierarchy') // hierarchy, departments
  const [zoom, setZoom] = useState(1)
  const [expandedNodes, setExpandedNodes] = useState(new Set())

  const chartOrganization = useMemo(() => {
    if (currentOrganization?.slug) return currentOrganization
    const shizuhaOrg = organizations.find((org) => org.slug === 'shizuha')
    if (shizuhaOrg) return shizuhaOrg
    if (isStaff) return { slug: 'shizuha', name: 'Shizuha' }
    if (organizations.length === 1) return organizations[0]
    return null
  }, [currentOrganization, organizations, isStaff])

  const needsOrganizationSelection = !orgsLoading && !chartOrganization

  const { data: chartData, isLoading, error: chartError } = useQuery({
    queryKey: ['org-chart', chartOrganization?.slug],
    queryFn: () => orgChartApi.get(chartOrganization.slug).then(res => res.data),
    enabled: !!chartOrganization?.slug,
  })

  const showStats = !!chartData && !orgsLoading && !orgsError && !needsOrganizationSelection
  // PLAT-527 (F4): per-member workload from Pulse, keyed by email.
  const workload = chartData?.workload ?? {}
  // PLAT-527 (F4): per-department workload rollup, keyed by dept ID (as string).
  const deptWorkload = chartData?.department_workload ?? {}
  // PLAT-3192: chartData.departments is the ROOT tree — its length is the root
  // count (1 for a single-root org), not the department total. Prefer the API's
  // flat total; fall back to counting the tree for older backend responses.
  const countDepartmentTree = (nodes) =>
    (nodes ?? []).reduce((sum, node) => sum + 1 + countDepartmentTree(node.children), 0)
  const totalDepartments = chartData?.total_departments ?? countDepartmentTree(chartData?.departments)

  const toggleNode = (id) => {
    setExpandedNodes((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const expandAll = () => {
    const allIds = new Set()
    const collectIds = (employees) => {
      employees.forEach((e) => {
        allIds.add(e.id)
        if (e.direct_reports) collectIds(e.direct_reports)
      })
    }
    if (chartData?.root_employees) collectIds(chartData.root_employees)
    setExpandedNodes(allIds)
  }

  const collapseAll = () => {
    setExpandedNodes(new Set())
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold">Organization Chart</h1>
          <p className="text-gray-500 dark:text-gray-400">
            {chartOrganization
              ? `Visual hierarchy of ${chartOrganization.name}`
              : 'Select an organization to view its hierarchy'}
          </p>
        </div>

        <div className="flex items-center gap-4">
          {/* View Mode Toggle */}
          <div className="flex rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
            <button
              onClick={() => setViewMode('hierarchy')}
              className={clsx(
                'px-4 py-2 text-sm',
                viewMode === 'hierarchy'
                  ? 'bg-primary-500 text-white'
                  : 'bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700'
              )}
            >
              Hierarchy
            </button>
            <button
              onClick={() => setViewMode('departments')}
              className={clsx(
                'px-4 py-2 text-sm border-l border-gray-200 dark:border-gray-700',
                viewMode === 'departments'
                  ? 'bg-primary-500 text-white'
                  : 'bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700'
              )}
            >
              Departments
            </button>
          </div>

          {/* Zoom Controls */}
          {viewMode === 'hierarchy' && (
            <div className="flex items-center gap-2">
              <button
                onClick={() => setZoom(Math.max(0.5, zoom - 0.1))}
                className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
                title="Zoom Out"
              >
                <ZoomOut className="h-4 w-4" />
              </button>
              <span className="text-sm w-12 text-center">{Math.round(zoom * 100)}%</span>
              <button
                onClick={() => setZoom(Math.min(1.5, zoom + 0.1))}
                className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
                title="Zoom In"
              >
                <ZoomIn className="h-4 w-4" />
              </button>
              <button
                onClick={() => setZoom(1)}
                className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
                title="Reset Zoom"
              >
                <Maximize2 className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>
      </div>

      {showStats && (
        <div className="flex items-center gap-6 text-sm text-gray-500">
          <span>Total Employees: <strong className="text-gray-900 dark:text-gray-100">{chartData?.total_employees || 0}</strong></span>
          <span>Departments: <strong className="text-gray-900 dark:text-gray-100">{totalDepartments || 0}</strong></span>
          {viewMode === 'hierarchy' && (
            <>
              <button onClick={expandAll} className="text-primary-600 hover:underline">
                Expand All
              </button>
              <button onClick={collapseAll} className="text-primary-600 hover:underline">
                Collapse All
              </button>
            </>
          )}
        </div>
      )}

      {/* Chart Content */}
      {orgsError ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-red-200 dark:border-red-800 p-12 text-center">
          <p className="text-red-600 dark:text-red-400">Unable to load organizations: {orgsError}</p>
        </div>
      ) : chartError ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-red-200 dark:border-red-800 p-12 text-center">
          <p className="text-red-600 dark:text-red-400">Unable to load organization chart: {chartError.message || 'request failed'}</p>
        </div>
      ) : needsOrganizationSelection ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-amber-200 dark:border-amber-800 p-12 text-center">
          <Building2 className="h-12 w-12 text-amber-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium">No organization selected</h3>
          <p className="text-gray-500 mt-1">
            Select an organization from the admin organization switcher to view its org chart.
          </p>
        </div>
      ) : orgsLoading || isLoading ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-12 text-center">
          <p className="text-gray-500">Loading organization chart...</p>
        </div>
      ) : viewMode === 'hierarchy' ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6 overflow-x-auto">
          {chartData?.root_employees?.length > 0 ? (
            <div
              className="org-chart-container"
              style={{
                transform: `scale(${zoom})`,
                transformOrigin: 'top center',
                transition: 'transform 0.2s ease',
              }}
            >
              <Tree
                lineWidth="2px"
                lineColor="#cbd5e1"
                lineBorderRadius="8px"
                label={
                  <div className="inline-block p-3 bg-primary-100 dark:bg-primary-900/30 rounded-xl border-2 border-primary-500">
                    <Building2 className="h-6 w-6 text-primary-600 mx-auto mb-1" />
                    <div className="font-bold text-sm">{chartOrganization?.name}</div>
                  </div>
                }
              >
                {chartData.root_employees.map((employee) => (
                  <OrgTreeNode
                    key={employee.id}
                    employee={employee}
                    expandedNodes={expandedNodes}
                    toggleNode={toggleNode}
                    workload={workload}
                  />
                ))}
              </Tree>
            </div>
          ) : (
            <div className="text-center py-12">
              <Users className="h-12 w-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
              <h3 className="text-lg font-medium">No hierarchy data</h3>
              <p className="text-gray-500 mt-1">
                Add employees with manager relationships to see the org chart
              </p>
            </div>
          )}
        </div>
      ) : (
        <DepartmentView departments={chartData?.departments} deptWorkload={deptWorkload} />
      )}

      {/* Legend */}
      <div className="flex items-center justify-center gap-6 text-sm text-gray-500">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded border-2 border-primary-300 bg-white" />
          <span>Has direct reports</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded border-2 border-gray-200 bg-white" />
          <span>No direct reports</span>
        </div>
      </div>
    </div>
  )
}
