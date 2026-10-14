import { useQueryClient } from '@tanstack/react-query'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { homeFor } from '../lib/routes'
import { clearStaff } from '../lib/staffSession'
import type { StaffSession } from '../lib/staffSession'
import Breadcrumbs from './Breadcrumbs'

export default function StaffLayout({ staff }: { staff: StaffSession }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  function signOut() {
    clearStaff()
    queryClient.clear()
    navigate('/', { replace: true }) // the entry page, where the three sign-ins are
  }

  return (
    <>
      <header className="staff-header">
        <Link to={homeFor(staff.role)} className="staff-brand">
          Integrity review
        </Link>
        <nav aria-label="Main">
          <NavLink to="/review" end>
            Queue
          </NavLink>
          <NavLink to="/review/audit">Audit</NavLink>
          {staff.role === 'admin' && (
            <>
              <NavLink to="/admin" end>
                Sittings
              </NavLink>
              <NavLink to="/admin/invites">Invites</NavLink>
              <NavLink to="/admin/questions">Questions</NavLink>
            </>
          )}
        </nav>
        <span className="staff-user">
          {staff.email} ({staff.role})
        </span>
        <button type="button" className="secondary" onClick={signOut}>
          Sign out
        </button>
      </header>
      <main className="page wide">
        <Breadcrumbs />
        <Outlet />
      </main>
    </>
  )
}
