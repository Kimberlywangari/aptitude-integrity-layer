# The browser side of logging, recording and upload

> **Status (19 Oct 2026): built and verified in Chromium; the parts that need a person are listed at
> the end.** Builds what the backend already serves and tests (see
> [api-reference.md](../api-reference.md)): the action logger, the heartbeat, the recorder with its
> on-device queue and uploader, the resume page, and the switch from fixtures to the real server.
> Specs come from [week-01 D4](week-01.md), [week-02 D6 to D8](week-02.md) and
> [master plan 7.8](00-master-plan.md). This file records the choices made while building them.

## What stays for a person

Nothing below can be settled by code. See "Left for you" at the end.

## Design

Everything runs in the main bundle (a chunk fetched mid-test is a chunk that can fail), adds no
runtime dependency (`idb` was already installed and unused) and logs, never blocks: the proposal says
"nothing is blocked".

| Piece | File | What it does |
|---|---|---|
| Device store | `lib/store.ts` | IndexedDB (`idb`) with three stores: `events`, `chunks`, `meta`. If IndexedDB is unavailable (private window, blocked site data) it falls back to memory and says so, so the test still runs |
| Event log | `lib/eventLog.ts` | `logEvent(type, payload, {at})`. Persisted queue, `client_seq` counted across reloads, `age_ms` worked out at send time (monotonic clock inside one page life, wall clock across a reload). Flushes every 2 s or at 20 events, in batches of 100, retries with backoff, and flushes with `keepalive` when the page hides |
| Connection | `lib/connection.ts` | Two failed network calls in a row, or the browser's `offline`, emit `connection_lost`; the next success or `online` emits `connection_restored` |
| Action logger | `lib/actionLogger.ts` | Focus, visibility, copy and cut (length only), paste, right-click, idle (30 s, back-dated), full screen, page load or reload |
| Heartbeat | `lib/heartbeat.ts` | `POST /api/heartbeat` every 10 s. The tick comes from a Web Worker built from a Blob (no extra file to fetch mid-test) so a hidden tab's timer throttling does not slow it; `setInterval` if a worker cannot start |
| Recorder | `lib/recorder.ts` | One `MediaRecorder` run (one segment). VP8 and Opus, 150 + 24 kbit/s. The first chunk is cut after 2 s so the server's gate opens quickly; the rest every 10 s |
| Chunk queue | `lib/chunkQueue.ts` | Each chunk is hashed (SHA-256), stored with its `seq`, `segment` and bytes, and kept until the server confirms it. `seq` counts through the whole session |
| Uploader | `lib/uploader.ts` | One chunk at a time, lowest `seq` first. Waits `min(60 s, 1 s x 2^n)` plus jitter after a failure. Treats `duplicate` as done. Stops for good on 401, 410 or 413 |
| Recording controller | `lib/recording.ts` | Starts segment 0, logs `device_info` and `recording_started`, survives a camera drop (new segment, retry every 5 s), stops with a last flush and reports `chunks_total` |
| Microphone watch | `lib/micWatch.ts` | Layer 2 of master plan 7.8: peak level every 250 ms; 60 s flat or muted turns the banner on and logs `mic_silent_start` (back-dated) and, on return, `mic_silent_end` |
| Shared devices | `lib/media.ts` | Holds the one camera and microphone stream from the pre-check through the test, so there is no second prompt and nothing to re-acquire |

## What each screen does after this

- **Pre-check:** hands the stream on instead of switching the camera off.
- **I agree, start the test:** starts the event log and the recorder, waits for the server to accept
  chunk 0 (up to 30 s, with a retry message), then begins the test. When the server's gate is
  `recording` (required in production) that wait is what the server demands anyway. A refusal with
  `reason: "recording"` stays on this page; it no longer sends the candidate back to the pre-check.
- **Test:** starts the heartbeat, the action logger and the microphone watch, logs `question_opened`,
  `answered` and `skipped`, and shows a non-blocking banner when the camera is lost. After a reload it
  reacquires the camera and starts the next segment.
- **Finish:** stops the recorder with a last flush, then calls finish with `chunks_total` and stops
  the logger.
- **Uploading:** drives the uploader from the queue on this computer, and shows the server's count
  (what counts) with what is still on this computer. "Finish anyway" logs `upload_incomplete`.
- **Resume:** `/resume` takes the invitation code, swaps it for the 48-hour upload token and goes to
  the uploading screen, which finishes the queue. The start page tries it by itself when the sitting
  has closed (`no_open_sitting`), which is the case that was a dead end.

## Fixtures

`/api/precheck`, `/api/complaints` and `/api/chunks` leave `MOCKED_PREFIXES`; `VITE_MOCK_API` leaves
`.env.development`. The fixtures stay in `src/lib/mock/` because the screen tests run on them.

## Order of work

1. [x] Store, event log, connection tracker, `api()` raw upload
2. [x] Action logger, heartbeat, microphone watch
3. [x] Chunk queue, recorder, uploader, recording controller, shared devices
4. [x] Wire the screens: pre-check, begin, test, finish, uploading, resume, start
5. [x] Switch off the fixtures
6. [x] Tests for each, then lint, type-check, build and bundle size
7. [x] One full journey in Chromium (fake camera) against the real API with `PRECHECK_GATE=recording`

## What was verified, and how

- **Frontend suite:** 441 tests (230 before), lint and type-check clean.
- **A whole journey in a real browser** (`npm run e2e`, `frontend/e2e/journey.spec.ts`): invitation
  link, every permission, the recording starting before the clock, 12 questions with one skipped, a
  reload mid-test, 20 s with no network, the finish and the upload to the last chunk. Run against a
  scratch database with the strict gate on. In the database afterwards: every event type expected, a
  copy event holding `{"length": 46}` and nothing else, chunks 0 to 6 with no gap and
  `chunks_total` equal to them, two segments (the reload started the second), the clock started in
  the same second the first chunk arrived, `connection_lost` back-dated to the moment the network went
  although it only reached the server 20 s later, and `chunk_integrity` re-hashing every chunk as ok.
  The recording joins into VP8 video at 320x240 plus Opus audio per segment.
- **Fault injection:** the same journey with the server refusing 30% of chunk uploads on purpose
  (`CHUNK_FAIL_RATE`; it refused 7 of 15 attempts that run): 8 of 8 chunks arrived and re-hashed ok.
- **Size:** what a candidate downloads grew from about 61 to about 67 KB gzipped (HTML, script and
  CSS). The extra is the logger, store, recorder and uploader; no runtime dependency was added
  (`idb` was already there). `fake-indexeddb` is a dev dependency for the tests only.

## Known limits found while building

- **A reload or closed tab loses the last few seconds of video.** The recorder hands over a piece
  every 10 s, and a page being torn down cannot flush the one it is holding (it measured about 5 s
  lost at the reload in the journey). A flag inside that window shows "no video at that moment" in the
  reviewer app, not a wrong frame. A shorter piece length would shrink the loss at the price of more
  requests.
- **A reload leaves full screen** and a page may only re-enter it on a click, so the question stays
  covered until the candidate presses "Return to full screen". The clock keeps running, and the cover
  says so. This is the design, not a fault.
- **Without IndexedDB** (a private window, site data blocked) the test still runs and uploads while the
  page lives, but nothing survives a reload and the resume page has nothing to send. The numbering of
  events and chunks is kept in `sessionStorage` so the server does not mistake new ones for repeats.
- The recorder, uploader and logger are in the main bundle on purpose; the heartbeat's worker is
  built from a string, so nothing has to be fetched in the middle of a test.

## Left for you

These need a person at a real machine, or a decision:

- Real **Edge**, a **Mac**, and a **physically muted microphone**.
- Filling in [browser-findings.md](../spikes/browser-findings.md), which is still blank. The code assumes
  IndexedDB survives closing the tab (check 4); if it does not, the resume page is of no use and the
  fallback is `upload_incomplete` plus the complaint route.
- Tuning `MIC_FLAT_PEAK` (0.0005) and the 60 s against a real quiet room and a muted microphone.
- Two minutes offline on a real network, and the video-seek accuracy check.
- Removing `VITE_MIC_CHECK=off` from `.env.development.local` before the pilot.
- Every commit and merge (CLAUDE.md: ask first).
