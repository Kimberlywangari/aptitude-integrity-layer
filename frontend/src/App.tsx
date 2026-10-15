import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import Complaint from './candidate/Complaint'
import Done from './candidate/Done'
import Entry from './entry/Entry'
import Integrity from './candidate/Integrity'
import NotSeb from './candidate/NotSeb'
import PreCheck from './candidate/PreCheck'
import Start from './candidate/Start'
import TestRunner from './candidate/TestRunner'
import UploadStatus from './candidate/UploadStatus'
import { setSebRequiredHandler } from './lib/api'
import { CANDIDATE_PATH } from './lib/routes'
import ThemeToggle from './ThemeToggle'

// Sign-in, reviewer and recruiter screens are a separate chunk: a candidate on a weak connection
// never downloads them.
const StaffApp = lazy(() => import('./staff/StaffApp'))

/** Any request the server refuses with 403 seb_required sends the candidate to /not-seb. */
function SebRedirect() {
  const navigate = useNavigate()
  useEffect(() => {
    setSebRequiredHandler(() => navigate('/not-seb', { replace: true }))
    return () => setSebRequiredHandler(null)
  }, [navigate])
  return null
}

export default function App() {
  return (
    <BrowserRouter>
      <SebRedirect />
      <ThemeToggle />
      <Suspense
        fallback={
          <main className="page">
            <p role="status">Loading...</p>
          </main>
        }
      >
        <Routes>
          <Route path="/" element={<Entry />} />
          <Route path={CANDIDATE_PATH} element={<Start />} />
          <Route path="/precheck" element={<PreCheck />} />
          <Route path="/integrity" element={<Integrity />} />
          <Route path="/test" element={<TestRunner />} />
          <Route path="/done" element={<Done />} />
          <Route path="/uploading" element={<UploadStatus />} />
          <Route path="/complaint" element={<Complaint />} />
          <Route path="/not-seb" element={<NotSeb />} />
          <Route path="/login/*" element={<StaffApp section="login" />} />
          <Route path="/review/*" element={<StaffApp section="review" />} />
          <Route path="/admin/*" element={<StaffApp section="admin" />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
