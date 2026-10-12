import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import Done from './candidate/Done'
import Integrity from './candidate/Integrity'
import NotSeb from './candidate/NotSeb'
import Start from './candidate/Start'
import TestRunner from './candidate/TestRunner'
import { setSebRequiredHandler } from './lib/api'

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
      <Routes>
        <Route path="/" element={<Start />} />
        <Route path="/integrity" element={<Integrity />} />
        <Route path="/test" element={<TestRunner />} />
        <Route path="/done" element={<Done />} />
        <Route path="/not-seb" element={<NotSeb />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
