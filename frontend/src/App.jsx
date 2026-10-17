import { Routes, Route, Navigate } from 'react-router-dom'
import { AdminProvider } from './contexts/AdminContext'
import Layout from './components/common/Layout'
import Dashboard from './pages/Dashboard'
import Members from './pages/Members'
import Departments from './pages/Departments'
import Teams from './pages/Teams'
import Employees from './pages/Employees'
import EmployeeDetail from './pages/EmployeeDetail'
import Positions from './pages/Positions'
import OrgChart from './pages/OrgChart'
import Settings from './pages/Settings'
import CreateOrganization from './pages/CreateOrganization'
import SuperuserLayout from './pages/superuser/SuperuserLayout'
import SuperuserOverview from './pages/superuser/SuperuserOverview'
import SuperuserUsers from './pages/superuser/SuperuserUsers'
import SuperuserUserDetail from './pages/superuser/SuperuserUserDetail'
import SuperuserOrganizations from './pages/superuser/SuperuserOrganizations'
import SuperuserOrgDetail from './pages/superuser/SuperuserOrgDetail'
import SuperuserServices from './pages/superuser/SuperuserServices'
import SuperuserSystem from './pages/superuser/SuperuserSystem'
import { ShizuhaChatWidget } from './components/chat'

function App() {
  return (
    <AdminProvider>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="members" element={<Members />} />
          <Route path="departments" element={<Departments />} />
          <Route path="teams" element={<Teams />} />
          <Route path="employees" element={<Employees />} />
          <Route path="employees/:id" element={<EmployeeDetail />} />
          <Route path="positions" element={<Positions />} />
          <Route path="org-chart" element={<OrgChart />} />
          <Route path="settings" element={<Settings />} />
          <Route path="superuser" element={<SuperuserLayout />}>
            <Route index element={<SuperuserOverview />} />
            <Route path="users" element={<SuperuserUsers />} />
            <Route path="users/:userId" element={<SuperuserUserDetail />} />
            <Route path="organizations" element={<SuperuserOrganizations />} />
            <Route path="organizations/:slug" element={<SuperuserOrgDetail />} />
            <Route path="services" element={<SuperuserServices />} />
            <Route path="system" element={<SuperuserSystem />} />
          </Route>
        </Route>
        {/* Create Organization - outside Layout since no org selected yet */}
        <Route path="create-organization" element={<CreateOrganization />} />
      </Routes>
      <ShizuhaChatWidget
        sourceService="admin"
        welcomeMessage="Hello! I can help you manage organizations, teams, and settings."
        showToolCalls={true}
      />
    </AdminProvider>
  )
}

export default App
