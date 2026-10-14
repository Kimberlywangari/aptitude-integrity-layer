import { useEffect, useRef, useState } from 'react'
import { formatDateTime, formatElapsed } from '../lib/format'
import type { VideoSegment } from '../lib/reviewTypes'

/** What the reviewer asked for. `nonce` changes on every click so the same flag can be re-played. */
export type JumpTarget =
  | { kind: 'seek'; segment: number; seekS: number; label: string; nonce: number }
  | { kind: 'none'; label: string; nonce: number }

interface Props {
  segments: VideoSegment[]
  target: JumpTarget | null
  deletedAt: string | null
}

export default function VideoPlayer({ segments, target, deletedAt }: Props) {
  const video = useRef<HTMLVideoElement>(null)
  const pendingSeek = useRef<number | null>(null)
  const [active, setActive] = useState(0)
  const [seenNonce, setSeenNonce] = useState<number | null>(null)

  // A new jump to another part switches to it while rendering (the element below is keyed on the
  // part, so it is a fresh <video> that has to load before it can seek).
  if (target && target.nonce !== seenNonce) {
    setSeenNonce(target.nonce)
    if (target.kind === 'seek') setActive(target.segment)
  }

  // Seek at once when the right part is already loaded; otherwise onLoadedMetadata does it.
  useEffect(() => {
    if (target?.kind !== 'seek') return
    pendingSeek.current = target.seekS
    const element = video.current
    if (element && element.readyState >= 1) {
      element.currentTime = target.seekS
      pendingSeek.current = null
    }
  }, [target])

  function onLoadedMetadata() {
    if (pendingSeek.current !== null && video.current) {
      video.current.currentTime = pendingSeek.current
      pendingSeek.current = null
    }
  }

  if (deletedAt) {
    return (
      <div className="panel">
        <h2>Video</h2>
        <p>
          The video was deleted on {formatDateTime(deletedAt)}, 30 days after the decision. The
          flags and the packet above are kept.
        </p>
      </div>
    )
  }

  if (segments.length === 0) {
    return (
      <div className="panel">
        <h2>Video</h2>
        <p>No video was recorded for this candidate.</p>
      </div>
    )
  }

  const segment = segments.find((s) => s.segment === active) ?? segments[0]

  return (
    <div className="panel">
      <h2>Video</h2>
      {segments.length > 1 && (
        <div className="actions" role="group" aria-label="Recording part">
          {segments.map((s) => (
            <button
              key={s.segment}
              type="button"
              className={s.segment === segment.segment ? undefined : 'secondary'}
              onClick={() => setActive(s.segment)}
            >
              Part {s.segment + 1}
            </button>
          ))}
        </div>
      )}

      {segment.url ? (
        <video
          key={segment.segment}
          ref={video}
          src={segment.url}
          controls
          preload="metadata"
          onLoadedMetadata={onLoadedMetadata}
        />
      ) : (
        <div className="video-placeholder">
          The video file is not available here (sample data). Jumps still show where the player
          would land.
        </div>
      )}

      <p role="status" className="muted">
        {target?.kind === 'seek' &&
          `${target.label}: part ${target.segment + 1} at ${formatElapsed(target.seekS)}, starting 5 s before the moment.`}
        {target?.kind === 'none' &&
          `${target.label}: no video was recorded at this moment (a camera drop or an incomplete upload).`}
        {!target && 'Choose a flag to jump to the moment, starting 5 s before it.'}
      </p>
    </div>
  )
}
