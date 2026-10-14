import { Link, useLocation } from 'react-router-dom'
import { crumbsFor } from './crumbs'

/** Shown only below the top of a section, where "where am I, and how do I get back" matters. */
export default function Breadcrumbs() {
  const { pathname } = useLocation()
  const crumbs = crumbsFor(pathname)
  if (crumbs.length < 2) return null

  return (
    <nav aria-label="Breadcrumb" className="breadcrumbs">
      <ol>
        {crumbs.map((crumb, index) => (
          <li key={crumb.label}>
            {crumb.to && index < crumbs.length - 1 ? (
              <Link to={crumb.to}>{crumb.label}</Link>
            ) : (
              <span aria-current="page">{crumb.label}</span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  )
}
