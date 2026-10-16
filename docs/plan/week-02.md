# Week 2: Recording, resilient upload, evidence and rule-based ranking

**Dates:** Thu 15 Oct – Wed 21 Oct 2026 · **Days:** D6 Thu 15 · D7 Fri 16 · (Sat–Sun buffer) · D8 Mon 19 · D9 Tue 20 · D10 Wed 21
**Branches:** one per task (`<type>/<short-task>`, see [master plan §5](00-master-plan.md#5-working-method)), started from `main` at tag `week-1` · **Tag on `main` at end of week:** `week-2`
**Back to:** [00-master-plan.md](00-master-plan.md) · **Previous:** [week-01.md](week-01.md) · **Next:** [week-03.md](week-03.md)

## Goal

Every sitting produces a **complete video record** (webcam + microphone) that survives dropped connections, and every flagged candidate gets an **evidence packet** and a **rule-based rank**, with question data ingested (or the synthetic fallback confirmed) and cohort checks working.

## Week at a glance

| Day | Focus | You can demo at the end of the day |
|---|---|---|
| D6 Thu 15 | Pre-check page and camera/mic gate | The test won't start until camera and mic work; retry works |
| D7 Fri 16 | Recorder, local chunk queue, ordered upload, chunk endpoint | A full sitting in Chrome or Edge leaves every chunk on the server, ~80 MB/h |
| D8 Mon 19 | Resilience: retries, 48 h resume, manifest, camera drops, assembly, complaint | Offline for 2 minutes → zero chunks missing; video seeks |
| D9 Tue 20 | Question summary ingest, cohort checks, full Docker stack | Importer report; cohort flags only when the sitting is closed and ≥ 8 |
| D10 Wed 21 | Evidence packets, rule scoring and ranking, honest false-flag measurement, S1 go/no-go | Ranked list from a synthetic cohort; false-flag rate measured; tag `week-2` |

**Chase these on Monday 19 Oct at the latest:**
- [ ] The pilot date and volunteer list (≥ 10 honest, 6 for scripted cheating) from Cytonn.
- [ ] The per-question summary, or a firm "it won't come" so you can freeze the synthetic fallback on D9.
- [ ] Integrity statement, self-report and device-requirement wording, if Cytonn has it.

---

## D6: Thursday 15 Oct. Pre-check page and gate

**Goal:** a candidate sees the device requirement and data-use notice, is asked for every permission the exam needs (camera, microphone, full screen), is told to turn off notifications, proves their camera and microphone work (with retry), and only then can start. The camera and microphone gate is the proposal's one automatic outcome.

### Steps

- [ ] **1. Branch (2 min):** `git switch main`, then one branch per task, for example `git switch -c feat/precheck-gate`. Merge each into `main` with `--no-ff` when its tests pass. Suggested names: `feat/precheck-gate` (D6), `feat/video-recorder-upload` (D7), `feat/resilient-upload` (D8), `feat/question-import-cohort` (D9), `chore/docker-stack` (D9), `feat/packets-rule-ranking` (D10), `feat/blueprint-generator` (D10 stretch).
- [ ] **2. Candidate notice text (30 min):** `frontend/src/candidate/copy.ts` gets: the **device requirement** (a Windows or Mac laptop or desktop with a working webcam and microphone and a current Chrome or Edge; phones, tablets and Chromebooks cannot sit the test, and a private window is not supported), the **data-use** notice (about 80 MB per hour; use Wi-Fi), and what is recorded. Say "tested on Windows" (master plan R18). Also save the same text as `docs/candidate-notice.md` so Cytonn can show it on the registration page, as the proposal says it must be shown *before they register*. Add the `MIC_NOTICE` line (master plan §7.8) to both: the microphone must stay on for the whole test, and the warning is shown to the reviewer.
- [ ] **3. Media helper (45 min):** `lib/media.ts` owns the one `MediaStream` for the whole test: `acquire()` calls `getUserMedia({ video: { width: 320, height: 240, frameRate: 15 }, audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } })` (so a live mic keeps a noise floor and a muted one stays flat, master plan §7.8), the stream is reused by the recorder on D7 (no second permission prompt), and it exposes `onTrackEnded`, `onMute`, `onUnmute` callbacks. It records `device_info {camera_label, mic_label}`, `mic_muted`/`mic_unmuted` and `track_ended` events through the logger from D4.
- [ ] **4. `PreCheck.vue` (120 min):** a guided page that asks for everything the exam needs, one step at a time, with a step indicator.
  1. **Before you start**: device and data notice with an "I understand" checkbox.
  2. **Turn off notifications**: a warning card with how to do it (Windows Focus Assist or Do Not Disturb, macOS Focus; close Teams, Slack, WhatsApp and email; pause browser notifications from other sites) and a checkbox, "I have turned off notifications". A web page cannot read the system's notification settings, so this is the candidate's own confirmation, stored in `precheck_report.notifications_off_confirmed` for the reviewer. The page does not ask for the browser's notification permission.
  3. **Allow camera and microphone**: one button asks for both in a single prompt. The step shows the state (not asked, waiting, allowed, blocked); a blocked state explains how to unblock it from the address bar and from the operating system's privacy settings, then retries.
  4. **Camera check**: live preview, a green tick when the video track is live and `readyState === 'live'`.
  5. **Microphone check**: an `AudioContext` + `AnalyserNode` level meter; "say your name"; passes when the RMS level goes above a small threshold for 1 s within 10 s. A muted mic (`track.muted` or no signal) fails with a clear message. Retry buttons on every failure; handle `NotAllowedError` ("allow the camera in the address bar and in your system privacy settings") and `NotFoundError` ("no camera found") separately.
  6. **Full screen**: a button press asks for full screen (a browser only allows it from a click) and the step passes once `document.fullscreenElement` is set. During the test, if the candidate leaves full screen, a "Return to full screen" cover hides the question until they return (the server clock keeps running, and this is said on the cover), and `fullscreen_exited` / `fullscreen_entered` are logged as context, never as a flag.
  7. **Start** button, enabled only when every step above has passed.
  - Screen order becomes: Start → PreCheck → Integrity → Test → SelfReport.
- [ ] **5. Server side (45 min):** migration adds `sessions.precheck_passed_at` and `precheck_report`. `POST /api/precheck/result {camera_ok, mic_ok, mic_checked, notifications_off_confirmed, fullscreen_ok, device_labels, mic_peak, video_size, browser}` stores the report and sets `precheck_passed_at` only if the camera is ok and the microphone is ok (or its step is switched off for testing). The confirmation and the full-screen result are kept in the report for the reviewer and are not part of the gate: the camera and microphone are the proposal's one automatic outcome. `POST …/begin` (from D3) now returns 409 `precheck_required` until it is set. **This is client-reported for now; D7 tightens it so the server verifies a real recording.**
- [ ] ~~**6. Scripted-run rehearsal (20 min):** select the OBS Virtual Camera as the camera…~~ **Out of scope:** testing with a virtual camera is not part of this build (master plan R12). Skip. The `device_info` event still records whatever camera label the browser reports.
- [ ] **7. Mic watch and warning banner (90 min):** `lib/micWatch.ts` is layer 2 of master plan §7.8. It reads the level from the shared stream with an `AnalyserNode` every 250 ms (reuse the pre-check's level helper) and starts when the test begins and stops at `finish`. Defaults in one config object, set from the D2 check 11 numbers: `MIC_FLAT_PEAK = 0.0005`, `MIC_SILENCE_SECONDS = 60`.
  - After `MIC_SILENCE_SECONDS` (1 minute) of flat signal or mute: emit `mic_silent_start` (time back-dated to when the flat run began) and show `MicBanner.vue`. When signal is back for 1 s: emit `mic_silent_end {duration_s}` and hide it.
  - Layer 1: the helper's `onMute` / `onUnmute` emit `mic_muted` / `mic_unmuted` at once and count a mute toward the same 1-minute timer. An unmute before then shows no banner.
  - **The banner never blocks.** `role="status"`, above the question, clear of the options and Submit, no change to the countdown or to any request. Text (placeholder): "Your microphone looks muted or silent. Please unmute it and keep it on for the whole test. Your test continues."

### How to test the day
- **Vitest (mock `navigator.mediaDevices`):** success path; `NotAllowedError`; `NotFoundError`; a muted audio track; recovery on retry.
- **Vitest (fake `AnalyserNode` and fake timers):** zeros for 59 s → no banner; zeros for 60 s → banner shown and `mic_silent_start` back-dated to the start of the flat run; signal returns → banner hidden and `mic_silent_end` carries the right `duration_s`; faint noise above `MIC_FLAT_PEAK` never triggers it; a `mute` event is logged at once and shows the banner after 60 s, while an `unmute` before then shows none and a later one clears it; while the banner shows, answering, skipping and the countdown all still work.
- **pytest:** `begin` before pre-check → 409; after a passing result → 200; a result with `mic_ok=false` does not set `precheck_passed_at`.
- **Manual in Chrome and Edge:** block the camera in the address bar and in Windows privacy settings → blocked with guidance; re-enable → retry passes; mute the mic in Windows → blocked; unmute → passes; check `events` for `device_info`. Then start a test and mute the mic in Windows: `mic_muted` shows in `events` at once if the event fires, the banner appears after 1 minute, the test keeps running, and `events` shows `mic_silent_start`; unmute → the banner clears and `mic_silent_end` appears. Tune `MIC_FLAT_PEAK` from what you see, in a quiet room as well as a noisy one.

### Commits
```
git commit -m "feat(ui): device requirement and data-use notice, shared with registration copy"
git commit -m "feat(media): single MediaStream owner with device, mute and track-ended events"
git commit -m "feat(precheck): camera and microphone checks with level meter, retry and error guidance"
git commit -m "feat(precheck): record pre-check result and gate begin on it"
git commit -m "test(precheck): mocked media devices and server gate"
git commit -m "feat(media): live mic level watch and non-blocking mute warning banner"
git commit -m "test(media): mic watch with fake analyser and timers"
```

---

## D7: Friday 16 Oct. Recorder, local chunk queue, ordered upload

**Goal:** recording starts with the test, chunks are stored on the device first and uploaded in order, and the server only lets the test begin once it has received a real recording with video **and** audio.

### Steps

- [ ] **1. Chunk table and store (45 min):** migration `video_chunks` (`session_id`, `segment`, `seq`, `bytes`, `sha256`, `path`, `received_at`, `deleted_at`). `services/video/store.py`: a `VideoStore` protocol (`put`, `open`, `list`, `delete_session`) and `LocalVideoStore(root=VIDEO_ROOT)` writing `data/video/{session_id}/{segment}/{seq:06d}.chunk`. Keeping it behind an interface means cloud storage can replace it later.
- [ ] **2. `PUT /api/chunks/{session}/{seq}` (60 min):** headers `X-Chunk-SHA256`, `X-Chunk-Segment`; body = raw bytes (limit 5 MB). Verify the bearer token and that the SHA-256 of the body matches the header (422 if not). Idempotent: same `seq` and same hash → 200 `{"status":"duplicate"}`; same `seq` and a different hash → 409. Accept out-of-order arrivals (the client sends in order, but retries can overlap).
  - `CHUNK_FAIL_RATE` (dev only): randomly return 503 for that fraction of requests, for fault injection on D8.
  - **Test:** store, then re-send (duplicate), then conflicting hash (409), bad hash (422), oversized (413), wrong token (401).
- [ ] **3. Recording anchor (30 min):** when the client starts recording it sends a `recording_started {segment}` event (D4 logger, with `age_ms`). Ingesting that event sets `sessions.recording_started_at` for segment 0 and keeps per-segment start times in the event table. This server-time anchor is what makes "flag → video moment" accurate: **video offset = flag `server_ts` − segment start**. Document this formula in `docs/spikes/video-anchor.md` (one paragraph).
- [ ] **4. `lib/recorder.ts` (60 min):** `MediaRecorder` on the shared stream with `mimeType: 'video/webm;codecs=vp8,opus'`, `videoBitsPerSecond: 150000`, `audioBitsPerSecond: 24000`, `start(10000)` (use whatever bitrate D2 showed gives ≈ 80 MB/h). On each `dataavailable`: compute SHA-256 (`crypto.subtle.digest`), put `{sessionId, segment, seq, blob, sha256, status:'pending'}` into the chunk queue, then ask the uploader to wake up. Emit `recording_started` on `onstart`.
- [ ] **5. `lib/chunkQueue.ts` and `lib/uploader.ts` (90 min):** `chunkQueue` is an IndexedDB store (`idb`) with `put`, `nextPending`, `markDone` (delete the blob but keep the metadata), `counts`. The uploader loop: take the lowest pending `seq` → `PUT` → on 200/duplicate `markDone`; on failure wait `min(60 s, 1 s × 2^n)` plus jitter and retry the same chunk. Always in order. Runs during the test and keeps running on the `/uploading` screen after the test ends. Show a small, non-blocking "Uploaded 42 / 45" line.
- [ ] **6. Tighten the gate (30 min):** `POST …/begin` now requires that the server has received `seq 0` of segment 0 and that `ffprobe -show_streams` on that chunk finds **one video stream and one audio stream**. The Start button in the UI starts recording first, waits for chunk 0 to be accepted, then calls `begin`. If it doesn't arrive within 30 s, show a retry message (the candidate "may retry within the session"). Add `ffprobe` to the API container/PATH.
- [ ] **7. Wire into the flow (20 min):** `finish` stops the recorder (flushes the last chunk), tells the server the chunk total (`chunks_total` in the finish body, needed for the manifest on D8), and moves to `/uploading`, then SelfReport.

### How to test the day
- **Vitest:** `chunkQueue` returns pending chunks in `seq` order; `uploader` with a fake `fetch` that fails twice then succeeds sends each chunk once and in order; a `duplicate` reply counts as done.
- **pytest:** chunk endpoint cases above; `begin` blocked without chunk 0; blocked when chunk 0 has no audio stream (use a fixture file made with `ffmpeg -f lavfi -i testsrc -t 5 video-only.webm`).
- **Manual in Chrome and Edge:** run a 10-minute test. Then:
  ```powershell
  Get-ChildItem data\video\<session_id> -Recurse -File | Measure-Object Length -Sum
  ```
  Compute MB per hour = (sum of bytes ÷ 1,048,576) ÷ (minutes ÷ 60). Target ≈ 80. Above about 100: lower resolution or bitrate and repeat. Every `seq` from 0 to N−1 is present.

### Commits
```
git commit -m "feat(video): chunks table and VideoStore interface with local file store"
git commit -m "feat(video): idempotent checksummed chunk upload endpoint with fault injection hook"
git commit -m "feat(video): server-time recording anchor for flag-to-video mapping"
git commit -m "feat(recorder): MediaRecorder chunking with SHA-256 and IndexedDB queue"
git commit -m "feat(uploader): ordered upload with exponential backoff and duplicate handling"
git commit -m "feat(precheck): require a real video+audio chunk before the test can begin"
git commit -m "test(video): chunk endpoint, queue ordering and uploader retries"
```

---

## D8: Monday 19 Oct. Resilient upload, 48 h resume, camera drops, complaint

**Goal:** no chunk is ever lost, a dropped camera doesn't end the test, and the uploader can finish up to 48 hours after the test. Apply the resume plan you chose on D2.

### Steps

- [ ] **1. Manifest (45 min):** `GET /api/chunks/{session}/manifest` → `{segments: [{segment, received: [..], missing: [..], expected}], bytes, complete}`. `expected` comes from `chunks_total` sent with `finish` (and for in-progress sessions, from the highest `seq` seen). `complete` is true when nothing is missing and `finish` has been received.
- [ ] **2. Candidate-side completion (45 min):** `UploadStatus.vue` polls the manifest, shows progress, and
  - keeps the candidate on the page until `complete`, then says "Everything has been uploaded. You can close this window." The page asks before the tab is closed while the upload is unfinished (`beforeunload`). If the connection is bad for too long, a "Finish anyway" button logs `upload_incomplete` and explains the complaint route.
  - **Resume (from D2 check 4):** shows "if you close this tab, reopen your test link within 48 hours to finish uploading"; add `POST /api/session/resume {token}` which issues an **upload-only** bearer token if `now − finished_at ≤ 48 h` (else 410), and the `/resume` route that reopens the IndexedDB queue and uploads.
  - **If check 4 failed:** just log `upload_incomplete` and show the complaint link.
- [ ] **3. Incomplete-upload job (20 min):** `python -m scripts.jobs mark_incomplete_uploads`: for sessions finished more than 48 h ago whose manifest isn't complete, insert an `upload_incomplete` event (once). Reviewers see it as context; it never disqualifies.
- [ ] **4. Camera drop handling (75 min):** in `recorder.ts`/`media.ts`, on a video or audio `track.onended`, `MediaRecorder.onerror` or inactive stream:
  - emit `camera_dropped`/`track_ended`, show a non-blocking banner ("camera lost, reconnecting…"), keep the test running;
  - retry `getUserMedia` every 5 s; when it succeeds, start a **new recorder segment** (`segment + 1`), emit `recording_started {segment}`. The new segment's first chunk carries its own container header, which is why segments are stored separately.
  - **Test (Vitest, mocked tracks):** ending the track fires `camera_dropped`, retries, and starts segment 1 on recovery.
- [ ] **5. Assembly and seeking (75 min):** `services/video/assemble.py::ensure_assembled(session_id)`: for each segment, concatenate the chunk files in `seq` order into a `.webm`, then remux:
  ```powershell
  ffmpeg -y -i seg0.webm -c copy seg0_fixed.webm
  ```
  so it has a duration and seek index. Write a small `segments.json` (segment → file, start `server_ts`, duration from `ffprobe`). Gaps between segments are simply "no video at this moment". The reviewer app uses this on D13.
- [ ] **6. Complaint endpoint (30 min):** migration `complaints`; `POST /api/complaints {category: camera|upload|other, text ≤ 1000}` with the session token; a plain link on the `/uploading` and `/done` screens. A person reviews it (shown in the reviewer detail view on D13).
- [ ] **8. Server silence scan (45 min):** layer 3 of master plan §7.8. Migration `audio_silences`. `services/audio/silence.py`: `parse_silencedetect(text)` (pure) and `detect_silence(session_id)`, which runs `ffmpeg -i <segment>.webm -vn -af silencedetect=noise=-65dB:d=60 -f null -` on each assembled segment (call `ensure_assembled` first), turns `silence_start` / `silence_end` into rows with `start_server_ts = segment start + offset`, and replaces that session's rows so a rerun gives the same result. Job: `python -m scripts.jobs detect_silence --sitting <id>`. Defaults `MIC_SILENCE_DB = -65`, `MIC_SERVER_MIN_SILENCE_SECONDS = 60`; recheck them against a real quiet-room recording from D7.
- [ ] **9. Fault-injection and chunk-integrity script (45 min):** `eval/metrics/chunk_integrity.py <session_id>`: reads the manifest, recomputes each stored chunk's SHA-256, compares with `video_chunks.sha256`, and prints missing/mismatched counts. Pass = 0 missing, 0 mismatched.

### How to test the day (this is the "no video chunks lost" criterion)
- **Fault injection:** `CHUNK_FAIL_RATE=0.3` — run a 5-minute test; every chunk still arrives; `chunk_integrity.py` reports 0 missing, 0 mismatched.
- **Offline for 2 minutes (automated):** Playwright `context.setOffline(true)` for 120 s mid-test, then back online; manifest ends `complete`, nothing missing; the events table shows `connection_lost` and `connection_restored`; **then run it for real**: unplug Wi-Fi on your laptop for 2 minutes in Chrome.
- **Close and resume:** close the browser tab mid-upload, reopen via `/resume`, finish. Also try to close the tab before completion and confirm the warning.
- **Camera drop:** unplug the USB camera (or disable it in Device Manager) mid-test: `camera_dropped` logged, test continues, plug back: segment 1 starts. `ensure_assembled` produces two playable files; `ffprobe` durations are within ±2 s of expected.
- **Seek:** open an assembled file in a browser `<video>` and scrub to the middle; it must seek instantly.
- **pytest:** manifest with gaps and duplicates; resume token expires after 48 h (use `FakeClock`); `mark_incomplete_uploads` inserts once.
- **pytest (silence scan):** `parse_silencedetect` on a saved ffmpeg log; a fixture made with ffmpeg (10 s tone, 70 s silence, 10 s tone, as WebM/Opus) gives one stretch starting at about 10 s and lasting about 70 s, and a 40 s silence gives none; a tone-only fixture and a low-level-noise fixture (`anoisesrc` at amplitude 0.01) give none; the job run twice leaves the same rows; `start_server_ts` equals the segment start plus the offset.

### Commits
```
git commit -m "feat(video): chunk manifest with missing-chunk detection"
git commit -m "feat(upload): completion screen with resume flow per the D2 decision"
git commit -m "feat(upload): 48-hour resume token and incomplete-upload marker job"
git commit -m "feat(recorder): survive camera drops with new recorder segments and retry"
git commit -m "feat(video): assemble and remux segments so recordings are seekable"
git commit -m "feat(complaints): complaint endpoint and form for camera and upload problems"
git commit -m "feat(audio): server-side silent-stretch scan of saved audio"
git commit -m "test(video): fault injection, offline resume and chunk integrity script"
```

---

## D9: Tuesday 20 Oct. Question data, cohort checks, full Docker stack

**Goal:** real (or confirmed-synthetic) question statistics are in the database, sitting-level pace and spread checks work with a minimum group size, and the whole thing runs with `docker compose up`.

### Steps

- [ ] **1. Decide the data source (10 min):** did Cytonn send the per-question summary? **Yes** → step 2. **No** → write a line in `docs/spikes/question-data.md`: "Synthetic fallback frozen on 20 Oct; per-question check will use synthetic statistics; pilot results must say so." Then skip to step 3.
- [ ] **2. Summary importer (75 min):** `scripts/import_question_summary.py <file.csv>` with columns `question_id, section, correct_option, difficulty_tag, n_candidates, pct_correct, median_s, p25_s, p75_s`.
  - Validate: required columns present; numbers in range; `p25 ≤ median ≤ p75`; `pct_correct` accepted as 0–100 or 0–1 (normalise to 0–1).
  - Difficulty: map Cytonn's tags to `easy`/`medium`/`hard` through a small mapping in config; if the tag is missing, derive it from `pct_correct` (≥ 0.75 easy, 0.40–0.75 medium, < 0.40 hard) and mark `difficulty_source='derived'`.
  - Upsert into `questions` and `question_stats` (`source='cytonn'`). If the CSV has no question text (the summary has IDs only), join with the question-bank export on `question_id`, and report any ID missing from either side.
  - Write `data/import_report.json` (rows imported, rejected, reasons) and print it.
  - **Test:** a good file; a file with `p25 > median`; missing column; duplicate IDs; percentage given as 62 vs 0.62.
- [ ] **3. Sitting close (30 min):** `python -m scripts.jobs close_sitting --sitting <id>` sets status `closed` once the sitting's close time has passed and every session is finished (or force it with `--force`, which is logged). Cohort checks refuse to run on an open sitting.
- [ ] **4. Cohort checks (120 min):** `services/flags/cohort.py` (pure functions + a thin DB wrapper).
  - Metrics per finished session: **pace** = mean time per answered question; **spread** = MAD of answer times ÷ median (robust).
  - Baseline per metric: sitting median and MAD (× 1.4826), stored in `sitting_stats`. `z = (x − median) / (1.4826 × MAD)`.
  - Flag `PACE_OUTLIER` when |z| ≥ 3 (record "fast" or "slow"), `SPREAD_OUTLIER` when |z| ≥ 3 (record "narrow" or "wide"). Weights 1.5.
  - **Minimum group size 8:** with fewer finished sessions, store `cohort_skipped: too_small` and create no cohort flags. If MAD is 0, skip that metric and note it.
  - **Test (pure):** a fixture sitting of 10 with one uniform-times candidate → one `SPREAD_OUTLIER (narrow)`; one very fast candidate → `PACE_OUTLIER (fast)`; a very slow one → `(slow)`; a sitting of 7 → no flags and the "too small" note; MAD 0 → skipped; running twice doesn't duplicate flags.
  - Add archetype `uniform_bot` to the simulator (all answers 18–22 s) and expectations to `eval/scripted_actions.md`.
- [ ] **5. Full Docker stack (60 min):**
  - `backend/Dockerfile` (Python 3.13 slim + `ffmpeg`), `frontend/Dockerfile` (build with Node, serve with nginx), `frontend/nginx.conf` (serve the SPA, proxy `/api` to `api:8000`, pass `Host` and `X-Forwarded-*`, allow large request bodies for chunks, `proxy_request_buffering off` is optional).
  - Compose services: `db`, `api`, `web` (port 8080), `worker` (runs `python -m scripts.jobs loop`, which later runs the purge job on D14; for now it just stays up).
  - Set `PUBLIC_BASE_URL=http://localhost:8080` for this mode and check that invitation links, the API and the camera all work through nginx.
  - **Test:** `docker compose up --build`; open `http://localhost:8080`; run a short test through the proxy in Chrome.

### How to test the day
`pytest -q` green. Importer report matches a hand count on a 5-row sample file. A cohort of 10 shows exactly the expected flags; a cohort of 7 shows none. A short test through the proxy works from the invitation link to the finish page.

### If behind
Drop step 5 to the weekend buffer or D10 morning, but do it before D11; the pilot environment must be tested through nginx.

### Commits
```
git commit -m "feat(import): per-question summary importer with validation and report"
git commit -m "feat(sitting): close_sitting job and sitting_stats baselines"
git commit -m "feat(cohort): robust pace and spread outlier checks with minimum group size"
git commit -m "test(cohort): fixtures for fast, slow, narrow, tiny sittings and zero MAD"
git commit -m "chore(docker): API, web (nginx) and worker images with single-origin proxy"
```

---

## D10: Wednesday 21 Oct. Evidence packets, rule ranking, false-flag measurement

**Goal:** every flagged candidate has a packet and a rule-based rank; the honest false-flag rate on a large synthetic cohort is measured and tuned; then decide on the stretch item and tag the week.

### Steps

- [ ] **1. Rule scoring (45 min):** `services/flags/scoring.py::rule_score(flags) -> ScoreBreakdown`: sum of weights, +1 for each distinct kind beyond the first, +1 if any two flags fall within 120 s; show each term separately. `is_flagged(breakdown, flags)` → `score ≥ 1.0` or any `LOGGING_PROBLEM` (that one goes in a separate lane at the bottom of the queue). **Test:** a lone focus loss = 0.5 → not flagged; two focus losses = 1.0 → flagged; copy attempt alone = 3; copy + long-hold within 120 s = 3+3+1+1 = 8; `LOGGING_PROBLEM` only → flagged, lowest lane.
- [ ] **2. Evidence packet (120 min):** migration `packets`; `services/packets.py::build_packet(db, session_id)` and a pydantic `Packet` schema (master plan §7.5).
  - `flags[]`: id, kind, `server_ts`, `elapsed_s`, question number, detail (numbers only).
  - `questions[]`: number, section, difficulty (or null) for every question a flag refers to.
  - `vs_sitting`: pace and spread percentiles in the sitting, or `cohort_skipped: too_small`.
  - `score` (correct/total) and `pace_s_per_q`, marked as context.
  - `innocent_signals[]`: connection drops and reloads (with times, so a reviewer can see whether they sit near a flag), `camera_dropped`, device labels, upload incomplete, and the self-report answer (category plus up to 300 characters, with email addresses and phone numbers redacted).
  - `mic_silence[]` (master plan §7.8): merge `mic_muted`/`mic_unmuted`, `mic_silent_start`/`mic_silent_end` (the browser layers, i.e. what the candidate was warned about) and the `audio_silences` rows (the server scan) into stretches. Overlapping ones are joined into one entry, and each entry lists which layers saw it (`browser`, `server` or both). Run `detect_silence` first; without it only browser stretches appear. Context only: no flag and no weight in the rule score. Their times and durations go in `facts`. Stretches shorter than `MIC_SILENCE_SECONDS` (60 s) are left out.
  - `video_anchor`: segment start times.
  - `facts`: every question number, whole-second time and count in the packet (the AI and the fact checker both use this).
  - **Never include a name.** There isn't one in the database, but add a test that scans the packet JSON for the candidate's invite token and any field called `name`.
  - **Test:** snapshot test of a packet for the `tab_lookup` archetype (stable key order); `facts` contains every number in `flags`; a session with only a reload and no flags produces no packet; a session with only a mic stretch and no flags also produces no packet and no flag; with a flag present, a browser stretch and a server stretch that overlap appear as one `mic_silence[]` entry listing both layers; a server-only stretch appears listing only the server layer; a browser-only stretch (no matching `audio_silences` row) also appears, listing only the browser layer.
- [ ] **3. Rule-based ranker (60 min):** `services/ranking/base.py` (define the `Ranker` protocol now; D11 uses it) and `ranking/rules.py::RuleRanker`. For a sitting: compute flags (individual + cohort + per-question later), keep the flagged sessions, build packets, score, sort by score descending (ties: earlier first flag), and write `rankings` rows with `rule_score`, `rule_rank`, `final_rank = rule_rank`, `ai_status='not_run'`, and a templated explanation ("3 kinds of flag within 90 s: COPY_ATTEMPT, LONG_HOLD_CORRECT, FOCUS_LOSS"). Job: `python -m scripts.jobs rank --sitting <id> --provider rules` prints the ordered table.
- [ ] **4. Honest false-flag measurement (60 min):** `eval/metrics/false_flags.py`: simulate 50 sittings × 10 honest candidates (500 total, so each sitting is above the size-8 minimum), including `honest_fast`; close each sitting; run flags + cohort; count flagged (`score ≥ 1.0`). Report: overall rate, rate by flag kind, and which honest behaviours cause them.
  - **Target:** at most 1 in 10. If above, tune `FlagConfig` (for example the focus-loss cap, the idle gap, the z threshold). **Tune using honest data only**, then rerun the cheater scenarios to confirm they're still caught. Record the final values and the rate in `docs/spikes/threshold-tuning.md`.
- [ ] **5. Ranking sanity test (30 min):** a cohort of 10 with 6 honest and `tab_lookup`, `copier`, `answer_runner`, `uniform_bot` → assert every cheater is in the top third of the *queued* candidates.
- [ ] **6. Stretch S1 go/no-go (decide at 13:00):** build the blueprint generator **only if** steps 1–5 are done and green. Budget: 3 hours, hard stop.
  - `services/blueprint/generator.py::generate_paper(blueprint, bank, rng)`: a blueprint is `{section: {easy: n, medium: n, hard: n}}`; draw that many from the matching pool using a per-session seeded RNG; difficulty from Cytonn's tag, else from `pct_correct` bands. Papers differ per candidate but have the same shape. Plug it into `select_questions` (the single hook from D3).
  - `services/blueprint/validator.py::validate_paper(paper, blueprint)`: counts per section and difficulty match, no duplicate question, all IDs exist. Also `bank_can_satisfy(blueprint, bank)` so an impossible blueprint fails early with a clear message.
  - **Test:** generate 500 papers, validate each: **500 of 500 must pass**; two papers for different candidates are not identical; an impossible blueprint raises.
  - If you skip it, write "S1 not built" in `docs/spikes/threshold-tuning.md`; the proposal says the related criterion then doesn't apply.
- [ ] **7. Full real run in Chrome (30 min):** take one complete sitting yourself in Chrome through `http://localhost:8080`: pre-check → test → upload → finish; then `close_sitting`, `compute_flags`, `rank`. Confirm: recording present, flags computed, packet readable.
- [ ] **8. Merge and tag (15 min).**

### How to test the day
`pytest -q` green; `false_flags.py` prints a rate; the ranking sanity test passes; the real run produces a packet you can read start to finish.

### Definition of done for Week 2
- [ ] Pre-check gate blocks without camera/mic; the server only begins the test after a real audio+video chunk arrives.
- [ ] A muted or silent mic mid-test shows the non-blocking banner and is logged; the server scan records silent stretches in `audio_silences`; the packet lists the stretches from both the browser and the server scan, as context, noting which layers saw each.
- [ ] Zero chunks missing under fault injection and a 2-minute offline test.
- [ ] Camera drop doesn't stop the test; segments assemble into seekable video.
- [ ] Question statistics imported (or synthetic frozen and documented).
- [ ] Cohort flags only when the sitting is closed and ≥ 8 candidates.
- [ ] Packets and rule-based ranking work; honest false-flag rate measured and recorded.
- [ ] Whole stack runs from `docker compose up` through nginx.
- [ ] S1 either done (500/500) or explicitly skipped.
- [ ] Tagged `week-2`.

### Commits
```
git commit -m "feat(ranking): rule score with kinds and proximity bonuses and queue-entry rule"
git commit -m "feat(packets): evidence packet builder with innocent signals and fact block"
git commit -m "feat(ranking): Ranker protocol and rule-based ranker with templated explanations"
git commit -m "test(packets): snapshot, no-name and facts-completeness tests"
git commit -m "feat(eval): synthetic honest cohort false-flag measurement and threshold tuning notes"
git commit -m "test(ranking): cheater archetypes land in top third of queue"
# only if S1 is built
git commit -m "feat(blueprint): per-candidate paper generator and validator (500/500)"
# all task branches are now merged into main
git switch main
git tag week-2
```
