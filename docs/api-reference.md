# API reference

Everything the backend serves, as built on 16 Oct 2026. Field names match
`frontend/src/lib/api.ts` and `reviewTypes.ts`. Errors are always `{"code": "...", ...extra}` with
a stable `code` to switch on; a malformed body gets FastAPI's own 422.

## Who is calling: three kinds of token

| Token | Where it comes from | What it opens |
|---|---|---|
| **Test token** | `POST /api/session/start` | The candidate's own session: question flow, heartbeat, pre-check, events, chunks, complaints. Sent as `Authorization: Bearer ...`. Starting again replaces it |
| **Upload token** | `POST /api/session/resume` | Only chunks, events, the manifest and complaints, for 48 hours after the test finished. It cannot read a question or change an answer |
| **Staff token** | `POST /api/review/login` | Reviewer routes (any staff) and admin routes (role `admin`). Valid 8 hours |

Reviewer video links (`...video?segment=0&t=...`) carry their own signed token in the URL, because a
`<video>` element cannot send a header. They name the session, the part and the reviewer, last 4
hours, and stop working the moment the reviewer is switched off.

## Candidate

| Route | Body → reply | Notes |
|---|---|---|
| `POST /api/session/start` | `{token}` → `{session_id, access_token, status}` | `token` is the invitation code (case, dashes and spaces ignored). Wrong codes count against a per-address limit (429 `too_many_attempts`) |
| `POST /api/precheck/result` | see below → `{passed}` | Test token. Stores the report; only camera and microphone decide `passed` |
| `GET /api/session/{id}/paper` | → `{status: pending\|ready\|failed, written, total, waited_s, can_retry}` | How far the candidate's questions have got. Always `ready` for a bank sitting. For an AI sitting it also restarts a `pending` paper nobody is writing (after a server restart). `waited_s` is the seconds waited so far (only while `pending`, else null); `can_retry` is true after a failure, or once the wait has reached `QUESTION_WAIT_LIMIT_S` (600 s by default) |
| `POST /api/session/{id}/paper/retry` | → same | Asks for the questions again: after `failed`, or once `can_retry` is true for a `pending` paper (the stuck run is abandoned and the wait starts again). Asking too early changes nothing. Whatever was written is kept |
| `POST /api/session/{id}/begin` | `{accepted}` → `{status, remaining_s}` | Starts the timer. 409 `paper_not_ready` (`paper_status`) until an AI sitting's questions exist. With `PRECHECK_GATE` on, 409 `precheck_required` (`reason`: `precheck` or `recording`) until the gate is met |
| `GET /api/session/{id}/question` | → `{position, total, section, text, options[], remaining_s, images[]}` | One question at a time, never the whole paper. `text` is plain text; a picture the question depends on is marked `[[image 1]]` in it, and `images[N-1]` is its address (a signed link, below). Empty `images` for every question that has no picture |
| `GET /api/session/{id}/image/{image_id}?t=...` | → the picture | No bearer token: an `<img>` cannot send one, so `t` is a signed token for this session and this picture (six hours). 403 `invalid_image_link` for a bad, stale or someone else's token; 404 `image_not_found` if the picture is not on the session's own paper |
| `POST /api/session/{id}/answer` · `/skip` | `{position, option_id}` / `{position}` → `{done, remaining_s}` | 409 `not_current`, 410 `time_up` |
| `POST /api/session/{id}/finish` | optional `{chunks_total}` → `{status, total, answered, skipped, unanswered}` | Say how many chunks were made; send again after the recorder's last flush if it changed. Latest value wins |
| `POST /api/session/{id}/self-report` | `{had_technical_issues, note?}` → 204 | Free text is shown to reviewers only, never put in a packet or sent to the AI |
| `POST /api/session/resume` | `{token}` → `{session_id, access_token, status: "finished", expires_at}` | Invitation code in, upload token out. 409 `nothing_to_resume`, 410 `resume_window_closed` |
| `POST /api/events` | `{events: [{client_seq, type, age_ms?, payload?}]}` (1 to 100) → `{accepted, duplicates, rejected}` | Test or upload token. Safe to resend. See event types below |
| `POST /api/heartbeat` | none → `{server_time, remaining_s, status}` | Test token only. Every 10 s while running. Stores nothing outside the running test |
| `PUT /api/chunks/{session}/{seq}` | raw bytes → `{status: "stored" \| "duplicate"}` | Headers `X-Chunk-SHA256` (required) and `X-Chunk-Segment` (default 0). See chunks below |
| `GET /api/chunks/{session}/manifest` | → `{expected, received, missing, bytes, complete}` | Counts only. `expected` is `null` until `finish` reported the total |
| `POST /api/complaints` | `{category: camera \| upload \| other, text ≤ 1000}` → 204 | 422 `invalid_complaint`, 429 `too_many_complaints` (10 per session) |
| `GET /api/health` | → `{status, db}` | |

### Pre-check body

`camera_ok`, `mic_ok` (booleans, required); `mic_checked` (false when the microphone step was
switched off for testing: `mic_ok` then means "not checked", never "failed"),
`notifications_off_confirmed`, `fullscreen_ok`, `browser {name, version}`,
`device_labels {camera, mic}`, `mic_peak`, `video_size {width, height}`. `passed` is camera ok and
(microphone ok, or not checked). The notification box and full screen are kept for the reviewer and
are never part of the gate. Once the test has begun a late report changes nothing.

### Events

`age_ms` is how long ago the page saw it; the server stores `server_ts = its own receive time minus
age_ms`, never earlier than the session's creation. `client_seq` is unique per session. A type the
server does not know is counted in `rejected` and the rest of the batch still lands.

Each type keeps only the payload fields listed, cleaned; anything else the page sends is dropped.
**Copy and cut keep the length only, never the text.**

| Type | Payload kept |
|---|---|
| `page_load`, `reload`, `focus_lost`, `focus_returned`, `visibility_hidden`, `visibility_visible`, `paste_attempt`, `contextmenu_attempt`, `idle_start`, `connection_lost`, `connection_restored`, `mic_muted`, `mic_unmuted`, `mic_silent_start`, `fullscreen_exited`, `fullscreen_entered` | none |
| `question_opened`, `answered`, `skipped` | `position` |
| `copy_attempt`, `cut_attempt` | `length` |
| `idle_end`, `mic_silent_end`, `camera_dropped` | `duration_s` |
| `track_ended` | `kind`, `duration_s` |
| `device_info` | `camera_label`, `mic_label` (trimmed to 200) |
| `recording_started` | `segment` (the first, segment 0, anchors the video) |
| `upload_incomplete` | `missing` |

### Chunks

`seq` counts 0, 1, 2 ... through the **whole session** and does not restart when the camera drops;
`segment` says which recorder run made the chunk (a new run starts with its own container header).
"Nothing missing" is therefore one check: every number from 0 to `chunks_total` is present.

- The server recomputes the SHA-256: 422 `checksum_mismatch`. Missing header: 422 `missing_checksum`.
- Same `seq` and same bytes: 200 `duplicate`. Same `seq`, different bytes: 409 `chunk_conflict`.
- Out of order is fine. Over `CHUNK_MAX_BYTES` (5 MB): 413 `chunk_too_large`.
- After the video was deleted: 410 `video_deleted`. After the 48-hour window: 410 `upload_window_closed`.
- `CHUNK_FAIL_RATE` (dev only, ignored when `ENV=production`) refuses some uploads with 503
  `chunk_unavailable` so retries can be exercised.
- A chunk that opens a recording carries the container header; the server reads it and records
  whether it declares a video and an audio track. With `PRECHECK_GATE=recording`, `begin` needs one
  such chunk from any segment.

## Reviewer (staff token)

| Route | Notes |
|---|---|
| `POST /api/review/login` → `{token, email, role}` · `GET /api/review/me` | |
| `GET /api/review/queue?sitting=` | Items in order: `candidate_id, rank, rule_score, ai_strength, ai_status, strength, band, flag_count, flag_kinds, decision, shortlisted, logging_only`. The order is the stored ranking when it still matches the flags, otherwise the rules. Only **flagged** candidates are in it: a rule score of 1.0 or more, or a gap in the record (`flagged_score` in `flags/config.py`). `strength` is 1 to 5, the AI's when it answered and otherwise the rules' (`strength_bucket`); `band` is `high` (4 to 5), `moderate` (3) or `low` (1 to 2, and always for a gap in the record). The band is a label for where to look first; nobody is set aside |
| `GET /api/review/overview?sitting=` | The overview page: `tiles {sat, finished, flagged, reviewed, videos_uploaded, videos_expected, videos_decided_not_deleted}`, `flags_by_kind[]` (the whole sitting, most common first), `pending` (queue candidates with no decision), `next_up[]` (the first three of them), `sitting_status`, and `checks[]` (`key, label, state ok\|warn\|off\|note, detail`). The checks say whether the AI provider answers (one 1 s request, only when it is `ollama`), the fact check and fallback, the camera and microphone gate, ffmpeg, and the count of heartbeat gaps. A recording counts as uploaded when every chunk the page said it made has arrived |
| `GET /api/review/candidates?sitting=` | Everyone who opened the test in the sitting, flagged or not, in invitation order: `candidate_id, status (created\|in_progress\|finished), resolved, total, flag_count, flag_kinds, in_queue, decision, shortlisted`. `in_queue` is the same test the queue uses, so the two lists agree. The queue is the work list; this is how to reach anyone else |
| `GET /api/review/candidates/{id}/events?sitting=` | The action log: `events[] {type, at_s, question, detail}` in server time (`at_s` is negative before the timer ran; `detail` is the allowed payload fields only, so a copy keeps its length and never its text), `questions[] {position, section, difficulty, opened_s, answered_s, time_s, result}` (no question text), `total_events`, `truncated` (capped at 2000), `heartbeats`, `status`. Works for anyone in the sitting, in the queue or not |
| `GET /api/review/candidates/{id}?sitting=` | The whole page. `video_available` is false for anyone the queue would not show unless shortlisted: then `segments` is empty and nothing is assembled. Flags carry `video_seek {segment, seek_s}` (5 s before the moment) or `null` when nothing was recorded then; `segments[]` carry signed `url`s; `explanation` is the AI's when it passed the fact check, otherwise the rules' with the reason in `status` (`fallback`, `not_run`). First open assembles the video (needs ffmpeg) |
| `GET /api/review/candidates/{id}/video?segment=&t=` | The recording with range support. `t` is the signed link; the staff token also works. 403 `video_not_available` unless queued or shortlisted, 410 `video_deleted`, 404 `no_such_segment`, 503 `ffmpeg_missing`. Audited once per part per 5 minutes |
| `POST /api/review/candidates/{id}/video-view` | `{flag_id?}` → 204. Audit entry when the reviewer jumps to a flag |
| `POST /api/review/candidates/{id}/shortlist` | Toggles. `{shortlisted}` |
| `POST /api/review/decisions` | `{session_id, outcome, reason}`. Outcomes `no_concern`, `concern_noted`, `refer_for_follow_up`; reason 20 to 2000 characters. The 30 days to deletion run from the **latest** decision |
| `GET /api/review/audit` | Newest first, up to 500 |

## Admin (role `admin`)

`GET/POST /api/admin/sittings`, `GET /api/admin/sittings/{id}`, `POST /api/admin/sittings/{id}/close`,
`POST /api/admin/sittings/{id}/delete`, `GET/POST /api/admin/invites`,
`POST /api/admin/invites/{candidate_id}/reissue`, `GET /api/admin/questions`,
`GET /api/admin/questions/summary`, `POST /api/admin/questions/import`,
`POST /api/admin/questions/retire-synthetic`. Every change is audited.

| Route | Notes |
|---|---|
| `POST /api/admin/sittings` | `{name, opens_at?, closes_at?, duration_s, per_section, question_mode?}` (`question_mode` is `cytonn`, `practice`, `ai`, or `bank`, the default and the original meaning, any stored question: see below) where `per_section` is `{section: how many questions}` (the **blueprint**), or `question_count` instead to spread a total evenly. Replies with `blueprint` and `question_count` (their sum). 422 `unknown_section` (`sections`), 422 `invalid_question_count`, 409 `section_too_small` (`sections[]` of `{section, available, needed}`, plus `needed` when spreading evenly), 409 `question_bank_too_small` (`available`). A candidate's paper then takes exactly that many from each section, in random order and a different draw per candidate |
| `POST /api/admin/sittings` with `question_mode: "ai"` | `per_section` is `{category: count}` over the seven categories (`numerical`, `verbal`, `logical`, `critical thinking`, `error checking`, `ai competence`, `office assistant`), at most 30 each and 100 in all | No bank needed. Each candidate's questions are written for them when they open their link. 503 `question_writer_unavailable` (`detail`) if the writer cannot be reached, 422 `unknown_section`, 422 `too_many_questions` (`max_per_category` or `max_total`) |
| `GET /api/admin/ai-questions/status` | → `{provider, model, available, detail, max_per_category, max_total, categories[]}` | Which model writes, whether it looks reachable, and the seven categories with what each is |
| `POST /api/admin/ai-questions/sample` | `{category, difficulty?}` → `{text, options[], correct_index, explanation, written_by, seconds, rounds, rejected[]}` | Writes one real question with every check, stores nothing. Slow on a slow computer. 502 `question_writer_failed` (`detail`, `rejected[]`) |
| `POST /api/admin/sittings/{id}/retry-papers` | → `{restarted}` | Starts writing again for candidates whose paper failed, or has been pending longer than the wait limit (stuck). A paper still being written inside the limit is left alone. 409 `not_an_ai_sitting` |
| `GET /api/admin/sittings/{id}` | → `{sitting, candidates[]}` | One sitting and everyone invited to it, oldest code first. Each candidate: `{candidate_id, state: not_opened\|opened\|started\|finished, answered, paper_status (null until the link is opened), paper_error, waited_s, opened_at, started_at, finished_at}`. No names, no codes. 404 `sitting_not_found` |
| `POST /api/admin/sittings/{id}/delete` | `{confirm_name}` → `{sessions, candidates, questions}` | Removes the sitting with its candidates and codes, every session (answers, events, flags, decisions, recording records), the questions written for them, and the video files. `confirm_name` must be the sitting's name exactly: 422 `name_does_not_match`. 409 `sessions_in_progress` (`in_progress`) while a test is running. Audit entries stay, with the session link cleared. A code left over from a candidate who also sat another sitting is kept. Cannot be undone |

Sittings in the list carry `question_mode` and `counts.papers_pending` / `counts.papers_failed`.
Questions an AI wrote are rows in `questions` with `source = ai`; they are left out of every bank count and list, and never drawn for another candidate.

**Question modes.** `cytonn` draws only Cytonn's questions (its seven sections, `per_section` checked against what Cytonn has: 409 `section_too_small` with `sections[]`, 409 `cytonn_not_loaded` when none are loaded), `practice` only the made-up bank, `bank` any stored question, `ai` writes them. A paper takes at most two questions from one reading passage. A sitting's `duration_s` is the candidate's time, whatever the mode.

| `POST /api/admin/invites` | `{count, sitting_id?}` → `{invites[{candidate_id, code}], sitting_id, sitting_name}` | Makes `count` (1 to 500) codes **for one sitting**: each opens that sitting's paper, for its time, whichever other sittings are open. `sitting_id` may be left out only while exactly one sitting is open; 409 `no_open_sitting`, 422 `sitting_required` (`sittings[]`), 409 `sitting_closed`, 404 `sitting_not_found`. Codes are shown once (`Cache-Control: no-store`) |
| `GET /api/admin/invites?sitting=` | The newest 500 candidates (of one sitting, if named) with `sitting_id`, `sitting_name` (null for a code made before invitations had a sitting: it opens the newest) and `status`: `not_opened` (no session yet), `opened` (a session exists, the timer has not started), `started`, `finished`, read off their newest session; and `total`. Codes are never listed: only a hash is stored |
| `POST /api/admin/invites/{candidate_id}/reissue` | A new code for one candidate, shown once (`Cache-Control: no-store`); the old code stops working at once. The code is never written to the audit log. 404 `candidate_not_found` |
| `GET /api/admin/questions?section=&limit=&offset=` | One page (limit up to 500, default 100) of `id, section, difficulty, source, preview (the first 200 characters), pct_correct, n`, and `total`. `pct_correct` and `n` are Cytonn's own figures and are `null` until a past-sitting summary has been imported; the made-up estimates are never shown |

## Batch jobs

`python -m scripts.jobs <name>` from `backend/`. Each is safe to repeat.

| Job | What it does |
|---|---|
| `seed_synthetic`, `load_question_bank`, `simulate_cohort [--purge]` | The made-up data: invitations, the 60 placeholder questions, a closed sitting of 16 |
| `import_question_summary SUMMARY.csv [--bank BANK.csv]` | Cytonn's per-question statistics (and, if sent, the bank export). Reports rejected rows; refuses while a sitting is open |
| `close_sitting --sitting X [--force]` | Closes it (so the cohort checks run); a forced close is audited |
| `compute_flags --sitting X` | Rule flags per session, plus pace and spread across a closed sitting of 8 or more. Keeps the baselines in `sitting_stats` |
| `assemble_videos`, `detect_silence --sitting X` | Join chunks into video that seeks; scan the audio for muted stretches. Need ffmpeg |
| `build_packets --sitting X` | An evidence packet for everyone in the queue |
| `rank --sitting X [--provider rules\|ollama\|claude]` | Rule order, or an AI assessment per packet with a fact check, one retry and a rule-order fallback. Nobody is dropped |
| `process_sitting --sitting X [--provider ...] [--skip-video]` | The pilot's order in one go, timing each step |
| `mark_incomplete_uploads`, `purge_videos [--report]` | Note uploads still incomplete after 48 h; delete video 30 days after the latest decision |
| `loop [--once]` | The worker: the two jobs above, hourly |
| `chunk_integrity --sitting X \| --session ID` | Proves no chunk was lost (exit 1 if one was) |
| `ai_explanations --sitting X [--csv PATH]` | Re-checks every stored AI explanation and writes the hand-check sheet |
| `pilot_metrics --sitting X --truth FILE` | Honest flagged, planted cheaters caught and in the top third, AI seconds |
| `video_offset --sheet FILE` | Seek accuracy: where the cue really is against where the jump lands |
| `create_reviewer`, `deactivate_reviewer` | Staff accounts |

## Settings that matter

| Setting | Default | |
|---|---|---|
| `PRECHECK_GATE` | `off` | `off`, `precheck` or `recording`. **A server with `ENV=production` refuses to start unless it is `recording`** |
| `VIDEO_ROOT` | `./data/video` | Relative paths are read from the repository root |
| `RETENTION_DAYS` | 30 | Days after the latest decision |
| `RESUME_WINDOW_S` | 172800 | The upload window after finishing |
| `AI_PROVIDER` | `rules` | `rules`, `ollama` or `claude` |
| `FFMPEG_BIN` | on PATH | |

The score that enters the queue is not an environment setting: it is `flagged_score` (1.0) in
`backend/app/services/flags/config.py`, with the other flag thresholds (plan A10, to confirm with
Cytonn).

## Tables

`candidates`, `sittings`, `sessions`, `questions`, `options`, `question_stats`, `session_questions`,
`events`, `heartbeats`, `flags`, `decisions`, `complaints`, `reviewers`, `audit_log` (earlier), and
from migration `0006`: `video_chunks`, `video_segments`, `audio_silences`, `sitting_stats`,
`packets`, `rankings`. Also `sessions.chunks_total`, `sessions.upload_token_hash` and an index on
`sessions.sitting_id`. Migration `0007` adds `questions.source` (`cytonn` or `synthetic`: where a
question came from, so a real question needs no statistics row to count as real),
`questions.cytonn_id` and `options.cytonn_id` (unique within a question). Migration `0008` adds
`sittings.blueprint`.

`video_segments` is not in the original plan: it keeps each assembled part's start time (the
`recording_started` event), length and file, so a flag's place in the video is a query rather than
a file to read, and it survives the video being deleted.

## Not built

The blueprint paper generator and validator (stretch item S1, which also mixed easy, medium and hard)
were removed from the project on 21 October 2026. What exists is narrower: a sitting may say how
many questions each section contributes (`sittings.blueprint`, from the console redesign of 22
October), and a candidate's paper is a random sample of exactly that. Difficulty is not part of it.
With no blueprint, papers are a random sample balanced by section.

The frontend side of everything above is built: the event logger, heartbeat, recorder with its
on-device queue, uploader, resume page and the screens that use them. It has been run end to end in Chromium against this
server, with the strict gate on and with uploads failing on purpose. It has not been run in real
Edge, on a Mac, with a physically muted microphone or on a real poor connection.

The Claude adapter has never run against the live API (no key yet). It is tested with a stand-in
client, and through the real `anthropic` SDK with the network mocked
(`tests/unit/test_claude_real_sdk.py`, which needs `pip install -e ".[claude]"` and is skipped
without it). That proves the call shape the SDK sends and how every failure comes back; it does not
prove that a key, the model or the schema are accepted by the live service.

nginx and the `web` image are built (`frontend/Dockerfile`, `frontend/nginx.conf`); HTTPS in front
of them is Cytonn's to provide.
