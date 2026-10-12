# Week 1: Foundations to rule-based flags


**Branches:** one per task, named `<type>/<short-task>` (see [master plan §5](00-master-plan.md#5-working-method)); each is merged into `main` when its tests pass · **Tag on `main` at end of week:** `week-1`
**Back to:** [00-master-plan.md](00-master-plan.md) (section 7 has the table, endpoint, event and flag names used below)

## Goal

By the end of the week a candidate can take a short test **inside Safe Exam Browser** with a **server-side timer**, every action is **logged with server timestamps and a heartbeat**, and **scripted cheating is flagged by rules**, all provable by automated tests.

## Week at a glance

| Day | Focus | You can demo at the end of the day |
|---|---|---|
| D1 Thu 8 | Scaffold, database, synthetic seed, tools installed | `docker compose up`, `/api/health` ok, 60 seeded questions |
| D2 Fri 9 | **SEB spike**: recording and local storage inside SEB | `docs/spikes/seb-findings.md` with a go/no-go |
| D3 Mon 12 | Test flow, server timer, SEB gate, integrity statement, self-report | Take a 12-question test in SEB; plain Chrome is refused |
| D4 Tue 13 | Action logger, offline queue, heartbeat | Events and heartbeats in the database; logging problem detected |
| D5 Wed 14 | Rule flags, cohort simulator, scripted tests | Scripted cheating flagged 100%; tag `week-1` |

**Before you start, do these in parallel (10 minutes each, send today):**
- [ ] Email Douglas the SEB questions from [master plan §10](00-master-plan.md#10-questions-to-ask-cytonn) (config ownership, key type, camera/mic allowed).
- [ ] Ask for the pilot date and the volunteer list (needed by D8).
- [ ] Ask for the per-question summary (needed by D8; the synthetic fallback is built today either way).

---

## D1: Thursday 8 Oct. Scaffold, database, synthetic seed

**Goal:** a running stack and a seeded database you can rebuild from scratch.

### Steps

- [x] **1. Branch and base files (15 min)** *(done on branch `chore/repo-base`)*
  - `git switch -c chore/repo-base` (one branch per task; see "Task branches and commits" at the end of D1).
  - Create `.gitignore` (Python: `.venv/`, `__pycache__/`, `.pytest_cache/`; Node: `node_modules/`, `dist/`; `.env`, `data/`, `*.seb`).
  - Create `.env.example` with the variables from master plan §3 (put real values in `.env`, which is ignored). It also has `ENV` and `TEST_DATABASE_URL`.
  - Folders: git does not track empty folders, so each folder is created by the task that first puts a file in it (`docs/spikes/` today, `backend/` and `frontend/` in their tasks, `seb/` and `eval/` from D2/D5).
- [x] **2. Record your laptop spec (10 min)** *(done: `docs/spikes/laptop-specs.md`, kept local and git-ignored; 15.7 GB RAM, i7-1185G7, Intel Iris Xe, no discrete GPU)*: needed for the Ollama decision on D11. In PowerShell:
  ```powershell
  Get-CimInstance Win32_ComputerSystem | Select-Object @{n='RAM_GB';e={[math]::Round($_.TotalPhysicalMemory/1GB,1)}}
  Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors
  Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM
  ```
  Paste the output into `docs/spikes/laptop-specs.md`.
- [x] **3. Install tools (30 min)** *(done: Docker running, Python 3.13.14, Node 24.19, Git 2.55, SEB 3.10.2 with SEB Config Tool)*: Docker Desktop (WSL2 backend; **start it**, the engine was not running at the start of D1), **Python 3.13** (3.12 or newer works; this laptop's default `python` is 3.14, which we avoid for now), Node 20 or newer (24 is fine), Git, Safe Exam Browser for Windows, and the SEB Config Tool (both from safeexambrowser.org). Check: `docker info; py -3.13 --version; node --version`. **ffmpeg is not needed until D7**; `winget` is not on PATH on this laptop, so download a build manually then.
- [x] **4. Postgres in Compose (15 min)** *(done 12 Oct: `docker-compose.yml`, init script in `docker/db-init/`; both `integrity` and `integrity_test` answer `select 1`)*: `docker-compose.yml` with one service `db` (`postgres:16`, user/password/db all `integrity` for local dev, port **`5433:5432`** because a local Postgres already uses 5432 on this laptop, named volume `pgdata`, healthcheck `pg_isready`). An init script also creates a second database, `integrity_test`, which the tests use.
  - Run: `docker compose up -d db`
  - Check: `docker compose exec db psql -U integrity -c "select 1"` → prints `1`; the same with `-d integrity_test`.
- [x] **5. Backend skeleton (60 min)** *(done 12 Oct: health route returns `{"status":"ok","db":true}`; Alembic, models and tests in step 6/7)*
  - `cd backend; py -3.13 -m venv .venv`, then call the venv's Python directly (`.\.venv\Scripts\python.exe -m pytest`, `-m uvicorn`, `-m alembic`), which avoids `Activate.ps1` and PowerShell execution-policy problems.
  - `pyproject.toml` with dependencies: `fastapi`, `uvicorn[standard]`, `sqlalchemy>=2`, `alembic`, `psycopg[binary]`, `pydantic-settings`, `httpx`, `python-multipart`, `bcrypt`, `itsdangerous`; dev extras: `pytest`, `pytest-asyncio`, `ruff`. Then `pip install -e ".[dev]"`.
  - `app/config.py`: a `Settings(BaseSettings)` reading `.env`.
  - `app/db.py`: engine, `SessionLocal`, `get_db` dependency.
  - `app/clock.py`: `class Clock(Protocol): def now() -> datetime`, `SystemClock` (UTC), `FakeClock(start)` with `advance(seconds)`. **Every later time check uses this**, never `datetime.now()`.
  - `app/main.py`: FastAPI app, router prefix `/api`, `GET /api/health` returns `{"status":"ok","db":true}` after running `select 1`.
  - Run: `uvicorn app.main:app --reload --port 8000`
  - **Test:** `curl http://localhost:8000/api/health` → `{"status":"ok","db":true}`. Add `tests/integration/test_health.py` and run `pytest -q` → 1 passed.
- [x] **6. Core models and first migration (60 min)** *(done 12 Oct: `0001_core_tables`; `test_migrations.py` runs downgrade base then upgrade head. The session model class is `TestSession`; `sessions.created_at` added)*: models for `candidates`, `sittings`, `sessions`, `questions`, `options`, `question_stats`, `session_questions` (columns in master plan §7.1; leave out tables that come later). Then:
  ```powershell
  alembic init migrations
  # set sqlalchemy.url in migrations/env.py from Settings
  alembic revision --autogenerate -m "core tables"
  alembic upgrade head
  ```
  - **Test:** `alembic downgrade base; alembic upgrade head` both succeed; `\dt` in psql lists the tables.
- [x] **7. Synthetic seed script (60 min)** *(done 12 Oct: also runnable as `python -m scripts.jobs seed_synthetic`; invitation tokens are deterministic from the seed and `SESSION_SECRET`, so `data/invites.csv` can be rebuilt)*: `scripts/seed_synthetic.py --seed 42`
  - 60 questions, `Q001`–`Q060`: 3 sections (`numerical`, `verbal`, `logical`), 20 each. Per section: 7 easy, 7 medium, 6 hard. 4 options each; `correct_option` random but fixed by the seed. Text is generated placeholder text ("Numerical question 7: ...").
  - `question_stats` with `source='synthetic'`, `n=400`. By difficulty: easy `median_s=25`, `pct_correct=0.85`; medium `45`, `0.60`; hard `75`, `0.35`. Add ±20% deterministic jitter per question. `p25_s = 0.7 × median`, `p75_s = 1.4 × median`.
  - One `sitting` (`question_count=12`, `duration_s=1800`, status `open`) and 20 candidates with invitation tokens; write the plaintext tokens to `data/invites.csv` (ignored by git) and store only hashes.
  - **Idempotent:** keyed on question ID and candidate number, so a second run changes nothing.
  - **Test:** `pytest tests/integration/test_seed.py`: run the seed twice, assert 60 questions, 240 options, 60 stats rows, 20 candidates, 1 sitting; per-section difficulty counts are 7/7/6.
- [x] **8. Frontend skeleton (30 min)** *(done 12 Oct: the current templates install React 19, Vite 8 and TypeScript 6, not React 18; `/api` proxy checked with curl through port 5173)*
  - `npm create vite@latest frontend -- --template react-ts`, then `npm i react-router-dom @tanstack/react-query idb` and `npm i -D vitest @testing-library/react jsdom @playwright/test`.
  - `vite.config.ts`: dev proxy `/api` → `http://localhost:8000`.
  - `App.tsx` calls `/api/health` and shows "API: ok".
  - **Test:** `npm run dev`, open `http://localhost:5173`, see "API: ok".
- [ ] **9. Make the first SEB config (20 min)**: open the SEB Config Tool, set the start URL to `http://localhost:5173/spike/index.html`, save as `seb/exam.seb` (ignored by git). Don't tune it yet; that is D2.

### If behind
Skip step 8's styling and the SEB config; D2 can start with `python -m http.server` in `frontend/public`.

### Task branches and commits (D1)

The proposal and plan were already committed to `main` as `docs: add proposal and implementation plan`. From here, one branch per task. Merge each into `main` (`git switch main; git merge --no-ff <branch>`) before starting the next.

| Order | Branch | Contents | Commit message(s) |
|---|---|---|---|
| 1 | `chore/repo-base` | `.gitignore`, `.env.example`, plan-file updates (`docs/spikes/laptop-specs.md` stays local and git-ignored) | `docs: record D1 findings and per-task branch workflow` · `chore: add gitignore and env example` |
| 2 | `chore/backend-scaffold` | `docker-compose.yml`, `backend/pyproject.toml`, `backend/app/*`, `backend/tests/*` | `chore: scaffold FastAPI app, Compose Postgres, injectable clock and health route` |
| 3 | `feat/core-models` | `backend/app/models`, Alembic, `0001_core_tables`, `test_migrations.py` | `feat(db): core tables for candidates, sittings, sessions, questions and stats` |
| 4 | `feat/synthetic-seed` | `backend/scripts/*`, `test_seed.py` | `feat(seed): idempotent synthetic question bank, stats and invitations` |
| 5 | `chore/frontend-scaffold` | `frontend/` | `chore(frontend): scaffold React + Vite + TypeScript with API proxy` |

---

## D2: Friday 9 Oct. SEB spike (recording and local storage inside SEB)

**Goal:** know, with evidence, what works inside real SEB, and choose how upload resumes. This is the highest-risk day of the project. **Do not start D3 until the decision at the end of this day is written down.**

### Steps

- [x] **1. Spike page (90 min)** *(built 12 Oct and exercised in headless Chromium with a fake camera/mic: record, IndexedDB write, reload survival, echo. Also `spike/quit.html`, survival markers, and a "Send log to server" button that writes `data/spike-log.jsonl`)*: `frontend/public/spike/index.html` + `spike.js` (plain JS, no build). It shows and logs:
  - `navigator.userAgent` (SEB adds a "SEB/…" token) and whether `window.SafeExamBrowser` exists; if it does, print `SafeExamBrowser.security` (some SEB versions expose the keys through a JS API).
  - **Start camera + mic** button: `getUserMedia({ video: { width: 320, height: 240, frameRate: 15 }, audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } })`; show the live preview. The three audio flags are off so a live mic keeps a noise floor and a muted one stays flat (master plan §7.8); check 12 shows whether SEB honours them. Add a small live level readout (`AnalyserNode`, peak sample) for check 12.
  - `MediaRecorder` with `mimeType: 'video/webm;codecs=vp8,opus'`, `videoBitsPerSecond: 150000`, `audioBitsPerSecond: 24000`, `start(10000)`.
  - `ondataavailable` → save each Blob into IndexedDB (database `spike`, store `chunks`, key = sequence number). Show chunk count, total bytes, and bytes per hour (extrapolated).
  - On page load, show how many chunks are **already** in IndexedDB (the survival check).
  - A test paragraph with listeners for `copy`, `cut`, `paste`, `contextmenu`, `blur`, `focus`, `visibilitychange`, and a `keyup` for `PrintScreen`, each appending a line to an on-page log.
  - A **Ping** button calling `GET /api/spike/echo`.
- [x] **2. Temporary echo route (10 min)** *(done 12 Oct; it also tests keys you give it against the rebuilt URL, and is not mounted when `ENV=production`)*: in `backend/app/api/spike.py`, `GET /api/spike/echo` returns the request headers (especially `X-SafeExamBrowser-RequestHash`, `X-SafeExamBrowser-ConfigKeyHash`) and the user agent. Delete this route before the pilot (note it in your D14 checklist).
- [ ] **3. Configure SEB (45 min)**: in the Config Tool, set start URL `http://localhost:5173/spike/index.html`, then look for these options (labels differ by SEB version, so match by meaning): allow camera / video capture, allow microphone / audio capture, block clipboard / copy-paste, block print screen, send the Browser Exam Key / Config Key in request headers, Quit URL. Save, then start SEB with the config.
- [ ] **4. Run the checklist (60 min)** and record every result in `docs/spikes/seb-findings.md` as a table: item · result · evidence (screenshot or log line) · decision.

  | # | Check | Pass means |
  |---|---|---|
  | 1 | Camera and mic prompt or permission setting works inside SEB | Preview shows, no browser permission dead-end |
  | 2 | `MediaRecorder` records and chunks arrive every ~10 s | Chunk count rises |
  | 3 | Bitrate | Bytes per hour ≈ 80 MB. If much higher, lower resolution or bitrate now |
  | 4 | **IndexedDB survives quit and relaunch** | After closing SEB and starting it again, the page shows the old chunks |
  | 5 | Echo route shows `X-SafeExamBrowser-*` headers on a `fetch()` call | Headers present (if absent on `fetch`, note whether the JS API can supply the keys) |
  | 6 | Which keys: note the Config Key and Browser Exam Key values from the Config Tool or the JS API | Keys captured into `.env` as `SEB_ALLOWED_KEYS` |
  | 7 | Copy/paste blocked. Does the page still see a `copy` event? | Note both facts |
  | 8 | Print Screen blocked. Does the page see anything? | Note both facts |
  | 9 | Alt+Tab, Win key, Ctrl+Alt+Del: does focus loss reach the page? | Note what's blocked and what isn't |
  | 10 | Quit URL quits SEB when the page navigates to it | Works / doesn't |
  | 11 | ~~OBS Virtual Camera appears as a camera~~ **Out of scope:** virtual-camera testing is not part of this build. Skip. | n/a |
  | 12 | Mute the mic at OS level (Windows privacy toggle, and a hardware switch or headset button if you have one), then unmute: does the track fire `mute` / `unmute`? Does the peak level go flat when muted, and stay above a small noise floor when unmuted in a quiet room? Are the three audio constraints honoured (`getSettings()`)? | Record yes / no for each; note the peak values. This decides how far master plan §7.8 layers 1 and 2 can be trusted |
  | 13 | CPU and RAM while recording (Task Manager) | Numbers recorded |

- [ ] **5. Write the decision (30 min)** at the top of `seb-findings.md`:
  - **GO / NO-GO** for recording inside SEB.
  - **Resume-upload plan**:
    - If check 4 passes: **Plan B**: the candidate may close SEB; a `/resume` start URL (reopened in SEB within 48 h) finishes the upload. The pre-check page and the finish page tell the candidate to keep SEB open until the upload finishes.
    - If check 4 fails but check 10 passes: **Plan A**: SEB cannot be closed until the upload is done; when `manifest.complete`, the page navigates to the Quit URL. If the connection is too bad, allow quit and log `upload_incomplete`; the candidate can file a complaint (the proposal's existing path).
    - If both fail: **Plan C**: record `upload_incomplete` and rely on the complaint path; raise it with Douglas now.
  - **What the page can observe** (checks 7–9) and the exact wording to use for "every blocked attempt is logged".
  - **Mic mute visibility** (check 12): which mutes the page can see (`mute` event, flat level, neither), and the starting values for `MIC_FLAT_PEAK` and `MIC_SILENCE_SECONDS` (master plan §7.8).
  - **Which key type** works for verification.
- [ ] **6. If recording does not work in SEB at all**: stop. Spend the rest of the day trying another SEB version or config option, then message Douglas with the evidence. The project depends on this.

### Weekend (Sat 10 – Sun 11): buffer
Use it only to finish D1–D2 items, or to rest. Don't start D3 work.

### Task branches and commits (D2)
Branches: `spike/seb-recording-test` (commit 1), then `docs/seb-findings` (commit 2).
```
git add frontend/public/spike backend/app/api/spike.py
git commit -m "spike(seb): recording, IndexedDB survival and event-visibility test page"

git add docs/spikes/seb-findings.md seb/README.md
git commit -m "docs(spike): SEB findings, go/no-go and resume-upload plan"
```

---

## D3: Monday 12 Oct. Test flow, server timer, SEB gate

**Goal:** a candidate can start, answer 12 questions one at a time with no going back, see a server-driven countdown, finish, accept an integrity statement and answer the technical-issues question. Plain Chrome is refused.

### Steps

- [x] **1. SEB verification (45 min)** *(done 12 Oct: a request passes if either SEB header matches any allowed key, so the key type chosen on D2 only changes `SEB_ALLOWED_KEYS`)*: `app/core/seb.py`
  - `verify_seb(request, settings) -> bool`: build the absolute URL as the browser saw it (`PUBLIC_BASE_URL` + request path + query), compute `sha256(url + key)` for each key in `SEB_ALLOWED_KEYS`, compare with `X-SafeExamBrowser-RequestHash` (and the Config Key header if you chose that) using `hmac.compare_digest`.
  - `SEB_MODE`: `off` (always passes, local dev), `log` (passes but records the result and prints mismatches), `enforce` (403 `{"code":"seb_required"}`).
  - `require_seb` dependency, applied to `session/start`, `answer` and `skip`. Save `sessions.seb_verified`.
  - **Test (unit):** a known URL + key + hash passes; wrong URL fails; wrong key fails; `off` always passes. **Manual:** `SEB_MODE=enforce`; the app works in SEB; the same URL in normal Chrome shows the "Safe Exam Browser required" page (D3 step 5).
- [ ] **2. Session start and question selection (60 min)**: `services/test_flow.py`
  - `POST /api/session/start {token}`: hash the token, find the candidate, create the session (or return the existing in-progress one, so a reload doesn't restart anything). Set `started_at = clock.now()`, `ends_at = started_at + duration_s`. Return `session_id` and a bearer token (random, only its hash stored in `access_token_hash`).
  - `select_questions(session, rng) -> list[Question]` — plain random sample of `question_count`, balanced by section for now (**keep it behind this one function; the blueprint generator replaces it in S1**). Seed `rng` from the session ID so it is reproducible.
  - `shuffle.py`: option order per session and question, seeded the same way; store it in `session_questions.option_order`.
  - **Test:** same session → same questions and option order; two different candidates differ; 12 questions returned; each section present.
- [ ] **3. Question, answer, skip, finish (75 min)**
  - `GET /api/session/{id}/question` returns the current question with options in the shuffled order (opaque option IDs, **no** `correct` field), the position, the total, and `remaining_s = ends_at − clock.now()`. First view sets `opened_at`; later views (reloads) do **not** change it.
  - `POST …/answer {position, option_id}` and `POST …/skip {position}`: accept only the **current** position (otherwise 409 `not_current`), set `answered_at`, `correct`, advance. No going back.
  - Any request after `ends_at` finishes the session and returns 410 `time_up`. `POST …/finish` is idempotent and computes the score.
  - `POST …/self-report {had_technical_issues: bool, note?: str (≤ 300)}`.
  - `POST …/begin` marks the test started after the integrity statement is accepted (`integrity_accepted_at`). (D6–D7 will add the pre-check gate to this route.)
  - **Test (pytest, with `FakeClock`):** answer position 1 after moving to 2 → 409; advance clock past `ends_at` → next request 410 and session finished; reload twice → `opened_at` unchanged; correct answer sets `correct=True`; skip sets `skipped=True`; token from another session → 401.
- [ ] **4. Candidate screens (90 min)**: routes `/` Start (token from `?t=` or typed), `/integrity` (statement text + checkbox + "I agree"), `/test` (question, options, Submit, Skip, countdown), `/done` (self-report), `/not-seb`.
  - `lib/api.ts`: fetch wrapper that adds the bearer token (kept in `sessionStorage`) and maps 403 `seb_required` to the `/not-seb` page.
  - `TestRunner.tsx`: countdown from the server's `remaining_s` (re-synced on every response, not from the client clock); **no Back**: a `history.pushState` trap on `/test` plus a `beforeunload` prompt; the question is fetched from the server on every load, so a reload keeps the same question and time.
  - Integrity statement text and self-report wording are placeholders until Cytonn supplies them (keep them in `src/candidate/copy.ts`). The integrity statement also carries the `MIC_NOTICE` line (master plan §7.8): the mic must stay on for the whole test, and the warning is shown to the reviewer.
- [ ] **5. Run it inside SEB (30 min)**: set `SEB_MODE=enforce`, put the key from D2 in `SEB_ALLOWED_KEYS`, change the SEB start URL to `http://localhost:5173/`. Take the whole test as a candidate from `data/invites.csv`.

### How to test the day
- `pytest -q` is green (timer, no-back, shuffle, SEB verify).
- Manual: a full 12-question run in SEB; the same URL in Chrome shows "SEB required"; reload mid-question keeps the question and countdown; let the timer run out in a short test sitting (set `duration_s=60`) and confirm the page moves to `/done`.

### If behind
Hard-code the integrity text and self-report to a single yes/no for now; do not skip the timer or no-back rule.

### Task branches and commits (D3)
Branches: `feat/seb-gate` (commit 1), `feat/test-flow` (commits 2, 3 and 5), `feat/candidate-screens` (commit 4).
```
git commit -m "feat(seb): verify SEB request hash with off/log/enforce modes"
git commit -m "feat(test-flow): session start, seeded question selection and option shuffle"
git commit -m "feat(test-flow): one-way question flow with server-side timer, skip, finish and self-report"
git commit -m "feat(ui): start, integrity, test runner, done and not-SEB screens"
git commit -m "test(test-flow): timer expiry, no-back rule, reload safety, SEB gate"
```

---

## D4: Tuesday 13 Oct. Action logger and heartbeat

**Goal:** every action in the proposal's logging list reaches the database with a server timestamp, survives a dropped connection, and a blocked logger shows up as a logging problem.

### Steps

- [ ] **1. Event and heartbeat tables (30 min)**: migration `events` (unique on `session_id, client_seq`) and `heartbeats`. Allowed event types are the list in master plan §7.3.
- [ ] **2. `POST /api/events` (60 min)**: body `{events: [{client_seq, type, age_ms, payload}]}`, max 100 per batch.
  - `server_ts = receive_time − age_ms` (receive time from the injected clock). Also store `received_at`.
  - Reject unknown types (422). Cap payload size. For `copy_attempt`/`cut_attempt`, **keep only `length`** and drop every other key, so question text can never be stored even by a buggy client.
  - Duplicates (same `session_id, client_seq`) are ignored, so retries are safe.
  - **Test:** valid batch stored; duplicate batch stores nothing new; unknown type rejected; a `copy_attempt` with a `text` key is stored without it; `age_ms=5000` gives a `server_ts` 5 s before receipt.
- [ ] **3. `POST /api/heartbeat` (30 min)**: inserts a row, returns `{server_time, remaining_s}` (the page can use this to re-sync the countdown).
- [ ] **4. Gap detection (45 min)**: `services/heartbeat.py::find_gaps(heartbeats, events, session) -> list[Gap]`. A gap is > 35 s between consecutive heartbeats (including the time from the last heartbeat to `finished_at`). A gap is **explained** if it overlaps a `connection_lost`…`connection_restored` pair or a `page_load`/`reload` event. Unexplained gaps become `LOGGING_PROBLEM` candidates (the flag itself is written on D5).
  - **Test (pure function):** steady 10 s heartbeats → no gaps; a 60 s hole → one gap; a 60 s hole covering a connection drop → explained; a hole at the end of the session counts.
- [ ] **5. Frontend logger (120 min)**: `lib/eventLogger.ts`
  - Listeners: `window` `blur`/`focus`; `document` `visibilitychange`; `copy`/`cut`/`paste`/`contextmenu` on the question text only (copy length = `String(getSelection()).length`; never read the text); `keyup` for `PrintScreen` (it may not fire inside SEB; D2 told you); an idle detector (no mouse, key, click, scroll or touch for 30 s → `idle_start`, then `idle_end` with `duration_s`).
  - Page lifecycle: on load emit `page_load`, or `reload` if `performance.getEntriesByType('navigation')[0].type === 'reload'`. `window` `online`/`offline` plus any failed request → `connection_lost`/`connection_restored`.
  - `TestRunner` emits `question_opened`, `answered`, `skipped`.
  - **Queue:** in memory, mirrored to IndexedDB (`idb`, store `events`) so a reload doesn't lose it; flush every 2 s or 20 events; retry with backoff; each event carries `client_seq` (monotonic, persisted) and `age_ms` computed at send time from `performance.now()`.
- [ ] **6. Heartbeat client (30 min)**: `lib/heartbeatWorker.ts` (a Web Worker that posts a tick every 10 s so background throttling doesn't slow it) and `lib/heartbeat.ts` that sends `POST /api/heartbeat` on each tick. Fall back to `setInterval` if the Worker can't start.
- [ ] **7. Hooks for testing failure (15 min)**: a dev-only query flag `?sim=drop-events` that makes the client skip sending events and heartbeats, so you can test logging problems without unplugging anything.

### How to test the day
- **Vitest:** dispatching `blur`/`focus`/`copy` on `window`/the question element produces the right event types; the copy payload contains only `length`; with fake timers, 30 s of nothing gives `idle_start`; the queue retries with a failing fake `fetch` and then delivers once, in order, with no duplicates.
- **pytest:** the API and gap tests above.
- **Manual in SEB:** take a few questions; in the DB (`select type, server_ts from events where session_id=… order by server_ts;`) you see `page_load`, `question_opened`, `answered`, and (try them) `focus_returned`/`copy_attempt` if SEB lets them through. Disconnect Wi-Fi for 20 s: `connection_lost`/`connection_restored` appear after reconnecting, with sensible times. Reload the page: a `reload` event appears. Run with `?sim=drop-events` for 60 s: `find_gaps` returns one unexplained gap.

### Task branches and commits (D4)
Branches: `feat/event-logging` (commits 1, 2, 4 and 6), `feat/heartbeat` (commits 3 and 5).
```
git commit -m "feat(events): events and heartbeats tables, ingest endpoint with server-side timestamps"
git commit -m "feat(events): whitelist event types, strip copy payload to length only, idempotent client_seq"
git commit -m "feat(heartbeat): 10 s heartbeat endpoint and unexplained-gap detection"
git commit -m "feat(logger): action logger with IndexedDB-backed offline queue and idle detection"
git commit -m "feat(heartbeat): Web Worker heartbeat tick with setInterval fallback"
git commit -m "test(logging): logger, queue retry, ingest and gap detection"
```

---

## D5: Wednesday 14 Oct. Rule flags, cohort simulator, scripted tests

**Goal:** the per-candidate rule flags work on real and simulated sittings, and every scripted cheating action is caught. Then merge and tag.

### Steps

- [ ] **1. Flags table and config (30 min)**: migration `flags`. `services/flags/config.py`: a dataclass `FlagConfig` with the defaults in master plan §7.4 (one place to tune; also loadable from an env-pointed JSON so you can test other values).
- [ ] **2. Pure rule functions (150 min)**: `services/flags/rules.py`. Input is plain data (`QuestionRecord(position, question_id, opened_at, answered_at, correct, skipped)`, a list of events, heartbeats, config). Output is `FlagCandidate(kind, weight, server_ts, position, detail)`. Write each function and its tests together:
  - `focus_loss_flags`: pair `focus_lost` with the next `focus_returned`; count losses ≥ 1 s; weight 0.5 each; cap at 2.0 unless ≥ 3 losses; `detail` has duration and which question was open.
  - `copy_attempt_flags`: one flag per copy/cut attempt, weight 3, `detail.length`.
  - `long_hold_correct_flags`: own median from the candidate's other answered questions (needs ≥ 5, else no flag and a note); trigger if time > `max(3 × median, median + 45 s)` and `correct`; weight 3, +1 if any focus loss overlapped the question.
  - `correct_run_after_gap_flags`: find each focus loss ≥ 5 s or idle gap ≥ 60 s; if the next ≥ 3 answers are all correct, flag with weight 2.
  - `logging_problem_flags`: from `find_gaps` (D4), unexplained gaps only.
  - **Test, per rule:** at least one positive case, one case just below the threshold (no flag), one case exactly at the threshold, and one where an innocent explanation (a reload, a dropped connection) is present. A lone focus loss → one flag of weight 0.5 only.
- [ ] **3. Engine (45 min)**: `services/flags/engine.py::compute_session_flags(db, session_id)` loads the data, runs the rules, replaces that session's previously computed `source='rule'` flags (idempotent), and stores them. CLI: `python -m scripts.jobs compute_flags --sitting <id>`.
- [ ] **4. Cohort simulator (90 min)**: `scripts/simulate_cohort.py --sitting <id> --honest 10 --seed 1 --cheaters tab_lookup,copier,answer_runner`. It writes `session_questions`, `events` and `heartbeats` straight to the database, no browser. Time per question is log-normal around the question's `median_s`; correctness drawn from `pct_correct` adjusted by a per-candidate ability. Archetypes:

  | Archetype | Behaviour | Expected flags |
  |---|---|---|
  | `honest` | Normal times, occasional single focus loss, occasional reload or drop | none, or a lone focus loss (0.5) |
  | `honest_fast` | Strong and fast, all within normal spread | none (pace is context only) |
  | `tab_lookup` | Focus lost 20–40 s on a question, long hold, then correct, ×3 questions | `FOCUS_LOSS`, `LONG_HOLD_CORRECT` (+1) |
  | `copier` | `copy_attempt` on 3 questions | `COPY_ATTEMPT` ×3 |
  | `answer_runner` | 90 s idle, then 4 fast correct answers | `CORRECT_RUN_AFTER_GAP` |
  | `logging_blocker` | Heartbeats stop for 60 s with no connection event | `LOGGING_PROBLEM` |

  (`uniform_bot` and `fast_correct` archetypes are added on D9 and D11, when their checks exist.)
- [ ] **5. Scripted-action register (20 min)**: `eval/scripted_actions.md`, a table of every scripted action (ID, how it is performed, expected flag kind, test that covers it). This is the list that "100% of scripted actions caught" is counted against.
- [ ] **6. Scripted tests (60 min)**
  - `tests/integration/test_scripted_scenarios.py`: for each archetype, run the simulator into a test DB, run the engine, assert the expected flags (and that `honest` and `honest_fast` get none above 0.5).
  - `frontend/e2e/scripted-cheater.spec.ts` (Playwright, **one** run): log in as a candidate, answer a few questions, dispatch a `blur`/`focus` pair and a `copy` event on the question text, hold a question open past the (test-config) threshold and answer correctly; then call `compute_flags` and assert that the expected flags exist. For the test, use a sitting with shortened thresholds via the config override.
- [ ] **7. Quick honest false-flag check (15 min)**: simulate 100 `honest` sessions and print how many have `sum(weights) ≥ 1.0`. Just look at the number today; the formal measurement is D10.
- [ ] **8. Wrap up the week (30 min)**: full test run (`pytest -q; npm test; npx playwright test`); write a 5-minute demo script (in `docs/` or the last merge message); make sure every task branch is merged into `main`; tag `week-1` on `main`.

### How to test the day
`pytest -q` is green and every row in `eval/scripted_actions.md` points to a passing test. The Playwright spec passes once. Honest simulated candidates are not flagged above a lone focus loss.

### Definition of done for Week 1
- [ ] `docs/spikes/seb-findings.md` has a go/no-go and a chosen resume-upload plan.
- [ ] A candidate can take the test inside SEB; plain Chrome is refused in `enforce` mode.
- [ ] Timer is server-side, no going back, reload-safe.
- [ ] Events and heartbeats are stored with server timestamps; copy events store length only.
- [ ] Rule flags work; scripted actions are caught 100%; honest archetypes aren't flagged.
- [ ] Everything committed, merged, tagged `week-1`.

### If behind
Drop the Playwright run (keep pytest scenarios). Do **not** drop the SEB spike or the gap detection.

### Task branches and commits (D5)
Branches: `feat/rule-flags` (commits 1–3), `feat/cohort-simulator` (commit 4), `test/scripted-scenarios` (commits 5–6). Merge each into `main`, then tag.
```
git commit -m "feat(flags): flags table and tunable FlagConfig defaults"
git commit -m "feat(flags): pure rule functions for focus loss, copy, long-hold-correct, correct run and logging problems"
git commit -m "feat(flags): idempotent session flag engine and compute_flags job"
git commit -m "feat(sim): synthetic cohort simulator with honest and cheater archetypes"
git commit -m "test(flags): per-rule boundary tests and scripted scenario suite"
git commit -m "test(e2e): Playwright scripted-cheater run and scripted-action register"
git commit -m "docs: week 1 demo notes"      # on test/scripted-scenarios or a docs/week-1-notes branch
# all task branches are now merged into main
git switch main
git tag week-1
```
