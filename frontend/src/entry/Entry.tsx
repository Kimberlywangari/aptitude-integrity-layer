import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { CANDIDATE_PATH, LOGIN_PATH } from '../lib/routes'

// Three doors, one per kind of person. This is part of the main chunk, which a candidate on a weak
// connection downloads, so it stays plain: no data, no staff code.

const CHOICES = [
  {
    to: CANDIDATE_PATH,
    title: 'Candidate',
    text: 'I am taking the aptitude test and have an invitation code.',
  },
  {
    to: LOGIN_PATH.reviewer,
    title: 'Reviewer',
    text: 'I look at flagged candidates and record what I find.',
  },
  {
    to: LOGIN_PATH.admin,
    title: 'Admin',
    text: 'I set up sittings, questions and invitations.',
  },
]

export default function Entry() {
  const [params] = useSearchParams()

  // Invitation links written before this page existed (/?t=CODE) still work.
  const code = params.get('t')
  if (code) return <Navigate to={`${CANDIDATE_PATH}?t=${encodeURIComponent(code)}`} replace />

  return (
    <main className="page entry">
      <h1>Aptitude test</h1>
      <p className="muted">Choose who you are to continue.</p>
      <ul className="entry-cards">
        {CHOICES.map((choice) => (
          <li key={choice.to}>
            <Link to={choice.to} className="entry-card">
              <strong>{choice.title}</strong>
              <span>{choice.text}</span>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  )
}
