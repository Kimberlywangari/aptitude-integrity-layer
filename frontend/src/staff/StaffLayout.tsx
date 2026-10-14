import { useQueryClient } from '@tanstack/react-query'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { clearStaff } from '../lib/staffSession'
import type { StaffSession } from '../lib/staffSession'

export default function StaffLayout({ staff }: { staff: StaffSession }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  function signOut() {
    clearStaff()
    queryClient.clear()
    navigate('/review/login', { replace: true })
  }

  return (
    <>
      <header className="staff-header">
        <strong>Integrity review</strong>
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
        <Outlet />
      </main>
    </>
  )
}
