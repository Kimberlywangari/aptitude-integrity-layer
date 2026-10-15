import { Link } from 'react-router-dom'
import { NOT_SEB_BODY, NOT_SEB_HELP, NOT_SEB_STEPS, NOT_SEB_TITLE } from './copy'

export default function NotSeb() {
  return (
    <main className="page">
      <h1>{NOT_SEB_TITLE}</h1>
      <p>{NOT_SEB_BODY}</p>
      <ol>
        {NOT_SEB_STEPS.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <p className="muted">{NOT_SEB_HELP}</p>
      {/* A normal browser by definition, so this cannot take a candidate out of the test. */}
      <p className="muted">
        <Link to="/">I am not taking the test: choose another sign-in</Link>
      </p>
    </main>
  )
}
