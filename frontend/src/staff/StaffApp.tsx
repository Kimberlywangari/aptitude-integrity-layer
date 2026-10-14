import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import Questions from '../admin/Questions'
import Invites from '../admin/Invites'
import Sittings from '../admin/Sittings'
import { staffRecovery } from '../lib/api'
import { homeFor, LOGIN_PATH, loginPathFor } from '../lib/routes'
import { clearStaff, getStaff } from '../lib/staffSession'
import Audit from '../reviewer/Audit'
import CandidateDetail from '../reviewer/CandidateDetail'
import Queue from '../reviewer/Queue'
import SignIn from './SignIn'
import StaffLayout from './StaffLayout'
import './staff.css'

/** Signed-out (or too-low-privilege) visitors are sent to the matching sign-in, with a way back. */
function RequireStaff({ role }: { role?: 'admin' }) {
  const location = useLocation()
  const staff = getStaff()
  if (!staff) {
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`${loginPathFor(location.pathname)}?next=${next}`} replace />
  }
  if (role === 'admin' && staff.role !== 'admin') return <Navigate to={homeFor(staff.role)} replace />
  return <StaffLayout staff={staff} />
}

/** The old reviewer sign-in address keeps working, and keeps where the person was going. */
function OldLoginRedirect() {
  const { search } = useLocation()
  return <Navigate to={`${LOGIN_PATH.reviewer}${search}`} replace />
}

function ReviewRoutes() {
  return (
    <Routes>
      <Route path="login" element={<OldLoginRedirect />} />
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

function LoginRoutes() {
  return (
    <Routes>
      <Route path="reviewer" element={<SignIn area="reviewer" />} />
      <Route path="admin" element={<SignIn area="admin" />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

// Set by the mounted StaffApp: what to do when a request finds the session has expired.
let onSessionExpired: (() => void) | null = null

function createClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error) => {
        if (staffRecovery(error) === 'sign-in' && getStaff()) onSessionExpired?.()
      },
    }),
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  })
}

/**
 * Everything staff-facing (the sign-in pages, the reviewer app and the recruiter's setup screens).
 * App.tsx loads this module lazily, so none of it, nor TanStack Query, reaches a candidate's
 * browser.
 */
export default function StaffApp({ section }: { section: 'review' | 'admin' | 'login' }) {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [client] = useState(createClient)

  // A session that expired mid-use goes back to the sign-in for the part of the app it was in.
  useEffect(() => {
    onSessionExpired = () => {
      clearStaff()
      client.clear()
      navigate(loginPathFor(pathname), { replace: true })
    }
    return () => {
      onSessionExpired = null
    }
  }, [client, navigate, pathname])

  return (
    <QueryClientProvider client={client}>
      {section === 'login' ? <LoginRoutes /> : section === 'review' ? <ReviewRoutes /> : <AdminRoutes />}
    </QueryClientProvider>
  )
}
