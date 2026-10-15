import { QUIT_PATH } from '../lib/routes'
import { HELP_CONTACT, QUIT_BODY, QUIT_LEAVE, QUIT_STILL_OPEN, QUIT_TITLE } from './copy'

interface Props {
  /** A full page load. Replaceable so a test can see the call. */
  assign?: (url: string) => void
}

/**
 * The page SEB's Quit URL points at. SEB offers to quit as soon as this address is requested, so
 * a candidate usually never reads it. If they answer No, or the config's Quit URL does not match,
 * this is what they are left with: it says what to do and has a Leave button that asks again.
 * The request must be a real page load, not a router link, or SEB never sees it.
 */
export default function Quit({ assign = (url) => window.location.assign(url) }: Props) {
  return (
    <main className="page">
      <h1>{QUIT_TITLE}</h1>
      <p>{QUIT_BODY}</p>
      <div className="actions">
        <button type="button" onClick={() => assign(QUIT_PATH)}>
          {QUIT_LEAVE}
        </button>
      </div>
      <p className="muted">
        {QUIT_STILL_OPEN} {HELP_CONTACT}
      </p>
    </main>
  )
}
