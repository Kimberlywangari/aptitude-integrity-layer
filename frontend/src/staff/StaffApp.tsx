import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import Questions from '../admin/Questions'
import Invites from '../admin/Invites'
import Sittings from '../admin/Sittings'
import { staffPathForError } from '../lib/api'
import { clearStaff, getStaff } from '../lib/staffSession'
import Audit from '../reviewer/Audit'
import CandidateDetail from '../reviewer/CandidateDetail'
import Login from '../reviewer/Login'
import Queue from '../reviewer/Queue'
import StaffLayout from './StaffLayout'
import './staff.css'

/** Signed-out (or too-low-privilege) visitors are sent to the login page with a way back. */
function RequireStaff({ role }: { role?: 'admin' }) {
  const location = useLocation()
  const staff = getStaff()
  if (!staff) {
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/review/login?next=${next}`} replace />
  }
  if (role === 'admin' && staff.role !== 'admin') return <Navigate to="/review" replace />
  return <StaffLayout staff={staff} />
}

function ReviewRoutes() {
  return (
    <Routes>
      <Route path="login" element={<Login />} />
      <Route element={<RequireStaff />}>
        <Route index element={<Queue />} />
        <Route path="candidates/:id" element={<CandidateDetail />} />
        <Route path="audit" element={<Audit />} />
      </Route>
      <Route path="*" element={<Navigate to="/review" replace />} />
    </Routes>
  )
}

function AdminRoutes() {
  return (
    <Routes>
      <Route element={<RequireStaff role="admin" />}>
        <Route index element={<Sittings />} />
        <Route path="invites" element={<Invites />} />
        <Route path="questions" element={<Questions />} />
      </Route>
      <Route path="*" element={<Navigate to="/admin" replace />} />
    </Routes>
  )
}

// Set by the mounted StaffApp: where to go when a request finds the session has expired.
let onSessionExpired: (() => void) | null = null

function createClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error) => {
        if (staffPathForError(error) === '/review/login' && getStaff()) onSessionExpired?.()
      },
    }),
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  })
}

/**
 * Everything staff-facing (the reviewer app and the recruiter's setup screens). App.tsx loads
 * this module lazily, so none of it, nor TanStack Query, reaches a candidate's browser.
 */
export default function StaffApp({ section }: { section: 'review' | 'admin' }) {
  const navigate = useNavigate()
  const [client] = useState(createClient)

  // A session that expired mid-use goes back to the login page.
  useEffect(() => {
    onSessionExpired = () => {
      clearStaff()
      client.clear()
      navigate('/review/login', { replace: true })
    }
    return () => {
      onSessionExpired = null
    }
  }, [client, navigate])

  return (
    <QueryClientProvider client={client}>
      {section === 'review' ? <ReviewRoutes /> : <AdminRoutes />}
    </QueryClientProvider>
  )
}
