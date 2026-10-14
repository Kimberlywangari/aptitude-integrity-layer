# Master Plan: Aptitude Test Integrity Layer

Weekly detail: [week-01.md](week-01.md) · [week-02.md](week-02.md) · [week-03.md](week-03.md)

---

## 1. Project summary and goals

**What it is.** A layer around Cytonn's aptitude test that makes the sitting harder to cheat in and gives human reviewers evidence instead of guesses. It does not decide anything about a candidate.

**What it does**

1. Locks the test inside Safe Exam Browser (SEB). The server rejects answers that don't come from a verified SEB session.
2. Records webcam and microphone for every candidate, at low resolution, in short chunks saved on the device first and then uploaded in order with retries. The test cannot start until camera and microphone work. If the microphone looks muted or silent during the test, a non-blocking banner warns the candidate and the stretch is logged for the reviewer (§7.8).
3. Logs actions, not keystrokes: answers, skips, focus loss and return, copy attempts (length only), idle time, plus a 10-second heartbeat.
4. Raises rule-based flags per candidate, per sitting (cohort), and per question (against past sittings).
5. Bundles each flagged candidate's flags into an evidence packet, ranks them by simple rules, and (week 3) has a local AI model on Ollama re-rank them and write a short explanation, with a fact check and a fallback to the rule order.
6. Gives reviewers a queue ordered by rank, where each flag jumps to the video 5 seconds before the moment. Every decision needs a written reason. Videos are deleted 30 days after the decision.

**Hard rules from the proposal (never break these)**

- Only two things are automatic: the camera/mic gate and rejecting non-SEB requests. Everything else is evidence for a human.
- The AI ranks and explains. It never gives a verdict, never sets a threshold, never sets anyone aside. Every flagged candidate reaches a reviewer.
- Score and pace are context only and are never flagged on their own.
- Packets use the candidate ID, never a name. Copy events record length, never text.
- Dropped connections and page reloads are shown to the reviewer as context, not flagged.
- A muted or silent microphone mid-test gets a warning banner and a log entry, and is shown to the reviewer as context. It never stops the test and is never a flag.

**Goals (the proposal's success table)** are listed with a test and a day in section 9.

**Out of scope (don't build):** face/voice/expression/mouse analysis, keylogging, answer-similarity comparison, watermarking, automatic rejection, ID verification, per-question timers, test-format changes, links into Cytonn's recruitment system, verifying every request (heartbeats and chunks), Mac/iPad testing, question-leak detection, testing with a virtual camera (OBS or any other fake webcam feed), a muted microphone as a scripted-run or pilot scenario (the muting detection itself is built, §7.8).

---

## 2. Assumptions (tell me if any is wrong)

| # | Assumption | Why |
|---|---|---|
| A1 | Weeks run Thu–Wed. Working days are Thu, Fri, Mon, Tue, Wed (D1–D15). Sat/Sun are buffer. | Proposal dates: week 1 = 8–14 Oct. 8 Oct 2026 is a Thursday. Confirmed with you. |
| A2 | Weekly files give concrete steps: files, endpoints, tables, PowerShell commands, expected output. | Confirmed with you. |
| A3 | Pilot stays on **Wed 28 Oct**; **Tue 27 Oct** is the full dry run and code freeze. | Confirmed. Zero slack after the pilot is a known risk (R3). |
| A4 | Ollama runs on **your laptop** (spec unknown yet) while the Claude API payment is pending. D1 records the spec; D11 benchmarks and picks the model. The Claude adapter is built and tested with mocked responses and switched on with `AI_PROVIDER=claude` later. | Confirmed. |
| A5 | Python **3.13** (3.12 or newer works; this laptop's default 3.14 is avoided for now), TypeScript on the frontend, Windows 11, PowerShell. | Matches your machine (checked on D1). |
| A6 | One origin for UI and API (Vite proxy in dev, nginx in compose). | SEB's request hash includes the exact URL. |
| A7 | No candidate names are stored. Invitation tokens map to opaque candidate IDs. | Proposal says packets use IDs, never names. |
| A8 | Only Windows + SEB is tested. | Proposal says so. |
| A9 | Flag thresholds in section 7 are my proposed defaults. All live in one config file and are meant to be tuned on synthetic honest data. | The proposal says "far longer", "far from typical" without numbers. |
| A10 | "Flagged" = rule score ≥ 1.0, or a logging problem. A lone focus loss (0.5) does not enter the queue. | Needed so honest candidates aren't flooded in. **Confirm with Douglas** (§10, "Policy and metrics"). |
| A11 | Week 4 day 1 (29 Oct handover) is a closing section in `week-03.md`, not a fourth file. | You asked for a three-week plan. |
| A12 | **One git branch per task**, named `<type>/<short-task>`, merged into `main` with `--no-ff` when its tests pass. You run the commits and merges; Claude builds each task and stops. | Changed on D1 (was one branch per week). |
| A13 | Compose Postgres is on host port **5433** (a local Postgres already uses 5432). ffmpeg is installed on D7, not D1. Docker Desktop must be started by hand. | Found by checking this laptop on D1. |

---

## 3. Tech stack and dependencies

| Layer | Choice | Notes |
|---|---|---|
| API | FastAPI, Uvicorn | Python 3.13 |
| DB | PostgreSQL 16, SQLAlchemy 2, Alembic, `psycopg[binary]` | Migrations per day, never edit old migrations. Compose maps the database to host port 5433; the tests use a second database, `integrity_test`, in the same container |
| Config / validation | pydantic v2, pydantic-settings | One `Settings` class; `.env` file |
| HTTP client | httpx | Ollama and Claude adapters |
| Video | `ffmpeg` / `ffprobe` | Remux MediaRecorder WebM so it seeks; check chunk 0 has video + audio. Install ffmpeg manually on D7 (`winget` is not on PATH on this laptop); installed in the API image |
| Auth (reviewers) | `bcrypt` + signed tokens (`itsdangerous`) | Simple, no external IdP |
| AI | Ollama (local), `anthropic` SDK as an optional extra | Behind one `Ranker` interface |
| Tests (backend) | pytest, pytest-asyncio, httpx `TestClient` | Fake clock injected everywhere time matters |
| Frontend | React 18, Vite, TypeScript, react-router, TanStack Query, `idb` | IndexedDB for events and video chunks |
| Tests (frontend) | Vitest + Testing Library, Playwright | Playwright drives scripted cheater runs |
| Infra | Docker Compose: `db`, `api`, `web` (nginx), `worker`. Ollama runs on the host | `OLLAMA_BASE_URL=http://host.docker.internal:11434` |
| Tools | SEB for Windows + SEB Config Tool | Install on D1. No OBS: virtual-camera testing is out of scope |

**Environment variables** (`.env.example`): `ENV`, `DATABASE_URL`, `TEST_DATABASE_URL`, `PUBLIC_BASE_URL`, `SESSION_SECRET`, `SEB_MODE` (`off`|`log`|`enforce`), `SEB_ALLOWED_KEYS`, `VIDEO_ROOT`, `RETENTION_DAYS=30`, `AI_PROVIDER` (`rules`|`ollama`|`claude`), `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `CLAUDE_MODEL`, `ANTHROPIC_API_KEY`, `CHUNK_FAIL_RATE` (dev only, fault injection).

---

## 4. Folder structure

```
aptitude-integrity-layer/
├── README.md
├── docker-compose.yml
├── .env.example
├── .gitignore
├── docs/
│   ├── proposal.md / proposal.pdf
│   ├── plan/                      # these files
│   ├── spikes/                    # laptop-specs.md (local only, git-ignored), seb-findings.md, video-anchor.md, question-data.md,
│   │                              # threshold-tuning.md, ollama-benchmark.md
│   ├── candidate-notice.md        # device-requirement + data-use text, for Cytonn's registration page
│   └── handover.md                # written on 29 Oct
├── seb/
│   ├── README.md                  # how the config was built, how keys are checked
│   └── exam.seb.template          # config without secrets
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── migrations/versions/
│   ├── app/
│   │   ├── main.py  config.py  db.py  clock.py
│   │   ├── api/        deps.py session.py precheck.py events.py chunks.py complaints.py review.py
│   │   ├── core/       seb.py security.py
│   │   ├── models/     (one module per table group)
│   │   ├── schemas/    (pydantic request/response + Packet + Assessment)
│   │   └── services/
│   │       ├── test_flow.py  shuffle.py
│   │       ├── events.py  heartbeat.py
│   │       ├── flags/      config.py rules.py cohort.py history.py engine.py scoring.py
│   │       ├── packets.py
│   │       ├── ranking/    base.py rules.py ollama.py claude.py prompts.py factcheck.py runner.py
│   │       ├── video/      store.py assemble.py seek.py purge.py
│   │       ├── audio/      silence.py                      # server scan for silent stretches (§7.8)
│   │       └── blueprint/  generator.py validator.py        # stretch S1
│   ├── scripts/        seed_synthetic.py import_question_summary.py simulate_cohort.py jobs.py
│   └── tests/          unit/ integration/ fixtures/
├── frontend/
│   ├── Dockerfile  nginx.conf  package.json  vite.config.ts  index.html
│   ├── public/spike/   (D2 SEB spike page)
│   ├── src/
│   │   ├── lib/        api.ts routes.ts session.ts eventLogger.ts heartbeat.ts heartbeatWorker.ts
│   │   │               media.ts micWatch.ts recorder.ts chunkQueue.ts uploader.ts
│   │   ├── candidate/  Start.tsx NotSeb.tsx PreCheck.tsx Integrity.tsx TestRunner.tsx
│   │   │               SelfReport.tsx UploadStatus.tsx Complaint.tsx MicBanner.tsx
│   │   ├── entry/      Entry.tsx   # "/": candidate, reviewer or admin; forwards /?t=CODE
│   │   ├── reviewer/   Queue.tsx CandidateDetail.tsx VideoPlayer.tsx DecisionForm.tsx Audit.tsx
│   │   ├── admin/      Sittings.tsx Invites.tsx Questions.tsx   # the recruiter's setup screens
│   │   ├── staff/      StaffApp.tsx StaffLayout.tsx SignIn.tsx Breadcrumbs.tsx crumbs.ts staff.css
│   │   │               # lazy chunk: sign-in, reviewer and admin only
│   │   └── lib/mock/   fixtures for endpoints not built yet (VITE_MOCK_API=1, dev only)
│   ├── tests/          (Vitest)
│   └── e2e/            (Playwright scripted-cheater specs)
└── eval/
    ├── scripted_actions.md         # every scripted action and its expected flag
    ├── metrics/                    # false_flags.py, compute_metrics.py, video_offset.py,
    │                               # chunk_integrity.py, ai_explanations.py, ai_benchmark.py
    ├── pilot/                      # runbook.md, observer-sheet.md, cheater-scripts.md, volunteer-brief.md, truth.csv
    └── reports/                    # scripted-run-seb.md, ai-explanations-handcheck.csv, pilot-report.md
```

---

## 5. Working method

- **Branch per task**, named `<type>/<short-task>` where the type is the commit prefix (`feat`, `fix`, `chore`, `docs`, `test`, `spike`). Examples: `chore/repo-base`, `feat/synthetic-seed`, `spike/seb-recording-test`. Start each from an up-to-date `main`, commit in small steps, and merge into `main` with `git merge --no-ff <branch>` once that task's tests pass. Tag `main` at the end of each week (`week-1`, `week-2`, `week-3`). Suggested branch names for each day are in the weekly files.
- **Daily rhythm:** build in the morning, test in the afternoon, last 30 minutes: run the full test suite, commit, tick the boxes in the weekly file, write one line of "what I changed from the plan" in the commit body.
- **Test pyramid:** pytest unit tests on pure functions (flag rules, scoring, fact check, seek maths) → pytest integration tests on a test database → Vitest for browser logic (logger, queue, uploader) → Playwright for scripted cheater runs → a manual SEB checklist every Friday → the pilot.
- **Everything time-based takes an injected clock** (`app/clock.py`), so timer expiry, heartbeat gaps and 30-day deletion are testable without waiting.
- **Pure functions first.** Flag rules take plain data in and return flags. The database layer only loads and stores. That is what makes "100% of scripted actions caught" provable.
- **Synthetic cohort simulator** (built D5, extended D9–D11) is reused for flag tests, the honest false-flag measurement, and ranking tests.
- **Commit rule:** only commit when the day's tests are green. Suggested commit messages are in each weekly file.

---

## 6. Phases and deliverables

| Phase | Days | What gets built | Deliverable (you can show this) |
|---|---|---|---|
| **P0 Foundations and SEB feasibility** | D1–D2 | Repo, Compose + Postgres, models, synthetic seed, SEB spike | Running stack, seeded database, `docs/spikes/seb-findings.md` with a go/no-go and the chosen resume-upload approach |
| **P1 Secure session and logging** | D3–D5 | Test flow, server timer, SEB gate, event logger, heartbeat, rule flags, cohort simulator | A sitting you can take inside SEB, with every action logged, and a pytest + Playwright suite where scripted cheating is flagged 100% of the time |
| **P2 Recording and evidence** | D6–D10 | Pre-check gate, recording, resilient upload, question-stats ingest, cohort checks, evidence packets, rule-based ranking | Full sitting → video chunks (none lost) → flags → packets → ranked list on synthetic data; honest false-flag rate measured |
| **P3 AI and review** | D11–D14 | Per-question check, Ollama ranker, fact check + fallback, Claude adapter, reviewer app, 30-day deletion | Reviewer queue with video at flagged moments; AI explanations fact-checked; deletion proven with backdated decisions |
| **P4 Pilot and handover** | D14–D15, 29 Oct | Dry run, pilot sitting, metrics, report, walkthrough | `eval/reports/pilot-report.md` with a result for every criterion, handover walkthrough done |
| **S1 Stretch** | D10 (go/no-go) | Blueprint paper generator + validator | 500/500 generated papers match the blueprint. Skipped if behind; the related criterion then doesn't apply (the proposal allows this) |

### Week → focus → deliverable

| Week | Dates | Focus | Deliverable |
|---|---|---|---|
| **1** | Thu 8 – Wed 14 Oct | Scaffold and synthetic seed; SEB recording + local-storage spike (D2); test flow with server timer; action logger and heartbeat; rule-based flags with scripted tests | Playable, logged sitting inside SEB; SEB findings doc; scripted flag tests green; tag `week-1` |
| **2** | Thu 15 – Wed 21 Oct | Pre-check page; recording and resilient upload; question data ingested (or synthetic fallback confirmed); cohort checks; evidence packets; rule-based ranking; stretch: blueprint generator | Zero-loss video pipeline; packets and rule-ranked queue from synthetic cohorts; honest false-flag rate measured; tag `week-2` |
| **3** | Thu 22 – Wed 28 Oct | Per-question check; Ollama ranking with fact check; reviewer queue with video at flagged moments; 30-day deletion; dry run; pilot and measurement | Reviewer app, AI ranking with fallback, deletion proof, pilot report; tag `week-3` |
| **Handover** | Thu 29 Oct | Walkthrough with Douglas, then integration questions and bug fixes only | `docs/handover.md`, walkthrough done |

---

## 7. Design reference (names used in every weekly file)

### 7.1 Tables

| Table | Key columns |
|---|---|
| `candidates` | `id` (opaque), `invite_token_hash`. No names. |
| `sittings` | `id`, `name`, `opens_at`, `closes_at`, `question_count`, `duration_s`, `status` (`open`/`closed`) |
| `sessions` | `id`, `candidate_id`, `sitting_id`, `status`, `started_at`, `ends_at`, `finished_at`, `seb_verified`, `integrity_accepted_at`, `precheck_passed_at`, `precheck_report`, `recording_started_at`, `self_report`, `shortlisted`, `video_deleted_at`, `access_token_hash` |
| `questions` / `options` | `id` (e.g. `Q001`), `section`, `difficulty` (`easy`/`medium`/`hard`/null), `correct_option`, text; options with label/text |
| `question_stats` | `question_id`, `n`, `pct_correct`, `median_s`, `p25_s`, `p75_s`, `source` (`cytonn`/`synthetic`) |
| `session_questions` | `session_id`, `position`, `question_id`, `option_order`, `opened_at`, `answered_at`, `selected_option`, `correct`, `skipped` |
| `events` | `session_id`, `client_seq`, `type`, `server_ts`, `received_at`, `payload` (unique on session + client_seq) |
| `heartbeats` | `session_id`, `server_ts` |
| `video_chunks` | `session_id`, `segment`, `seq`, `bytes`, `sha256`, `path`, `received_at`, `deleted_at` |
| `audio_silences` | `session_id`, `segment`, `start_s`, `end_s`, `start_server_ts`, `end_server_ts` (server scan of the saved audio, §7.8) |
| `flags` | `session_id`, `kind`, `weight`, `server_ts`, `position`, `detail`, `source` |
| `sitting_stats` | `sitting_id`, metric, `median`, `mad`, `n` (cohort baselines) |
| `packets` | `session_id`, `json`, `built_at` |
| `rankings` | `session_id`, `rule_score`, `rule_rank`, `ai_status` (`not_run`/`ok`/`retried`/`fallback`), `ai_json`, `ai_attempts`, `ai_seconds`, `final_rank` |
| `reviewers` | `id`, `email` (lower-case, unique), `password_hash` (bcrypt), `role` (`reviewer`/`admin`), `is_active`, `created_at` |
| `decisions` | `session_id`, `reviewer_id`, `outcome`, `reason`, `decided_at` |
| `audit_log` | `id`, `reviewer_id` (null if the account is removed), `action` (`decision`/`video_view`/`video_purged`/`login`), `session_id`, `ts`, `detail` |
| `complaints` | `session_id`, `category`, `text`, `created_at`, `status` |

### 7.2 Endpoints

Candidate (bearer = per-session token): `POST /api/session/start`, `POST /api/session/{id}/begin`, `GET /api/session/{id}/question`, `POST /api/session/{id}/answer`, `POST /api/session/{id}/skip`, `POST /api/session/{id}/finish`, `POST /api/session/{id}/self-report`, `POST /api/session/resume`, `POST /api/precheck/result`, `POST /api/events`, `POST /api/heartbeat`, `PUT /api/chunks/{session}/{seq}`, `GET /api/chunks/{session}/manifest`, `POST /api/complaints`, `GET /api/health`.

Reviewer (bearer = reviewer token): `POST /api/review/login`, `GET /api/review/me`, `GET /api/review/queue`, `GET /api/review/candidates/{id}`, `GET /api/review/candidates/{id}/video`, `POST /api/review/candidates/{id}/video-view`, `POST /api/review/decisions`, `POST /api/review/candidates/{id}/shortlist`.

Admin (bearer = admin token; the recruiter's setup screens, thin wrappers over the CLI jobs below): `GET/POST /api/admin/sittings`, `POST /api/admin/sittings/{id}/close`, `POST /api/admin/invites`, `GET /api/admin/questions/summary`, `POST /api/admin/questions/import`, `POST /api/admin/questions/retire-synthetic`. Reviewer calls also include `GET /api/review/audit`. Candidate side adds `GET /api/chunks/{session}/manifest` returning counts only (`expected`, `received`, `missing`, `bytes`, `complete`).

CLI jobs (`python -m scripts.jobs <name>`): `seed_synthetic`, `import_question_summary`, `simulate_cohort`, `close_sitting`, `compute_flags`, `build_packets`, `rank`, `mark_incomplete_uploads`, `detect_silence`, `purge_videos`, `create_reviewer`, and `loop` (the worker's hourly runner for the purge and incomplete-upload jobs).

### 7.3 Event types

`page_load`, `reload`, `question_opened`, `answered`, `skipped`, `focus_lost`, `focus_returned`, `visibility_hidden`, `visibility_visible`, `copy_attempt{length}`, `cut_attempt{length}`, `paste_attempt`, `contextmenu_attempt`, `idle_start`, `idle_end{duration_s}`, `connection_lost`, `connection_restored`, `device_info{camera_label, mic_label}`, `mic_muted`, `mic_unmuted`, `mic_silent_start`, `mic_silent_end{duration_s}`, `camera_dropped`, `track_ended`, `recording_started{segment}`, `upload_incomplete`.

Events sent late (after a dropped connection) carry `age_ms`, so the server computes `server_ts = server_receive_time − age_ms`. The server clock is the only clock that counts, and late events don't get a misleading time.

### 7.4 Flags and proposed defaults (all in `services/flags/config.py`)

| Flag | Rule | Weight |
|---|---|---|
| `FOCUS_LOSS` | each loss ≥ 1 s; total from focus loss capped at 2.0 unless there are ≥ 3 losses | 0.5 each |
| `COPY_ATTEMPT` | any copy/cut attempt on question text | 3 |
| `LONG_HOLD_CORRECT` | time on question > max(3 × the candidate's own median, own median + 45 s), own median from ≥ 5 other answers, answered correctly | 3 (+1 if focus was lost during it) |
| `CORRECT_RUN_AFTER_GAP` | ≥ 3 correct in a row straight after a focus loss ≥ 5 s or an idle gap ≥ 60 s | 2 |
| `PACE_OUTLIER` (cohort) | robust z (median/MAD) of mean time per question, \|z\| ≥ 3 either direction, sitting closed and ≥ 8 candidates | 1.5 |
| `SPREAD_OUTLIER` (cohort) | robust z of answer-time spread, \|z\| ≥ 3 either direction (narrow band is the interesting one), same size rule | 1.5 |
| `FAST_CORRECT_VS_HISTORY` | correct and time < 0.5 × the question's p25; at least 2 such questions; hard questions × 1.5 | 2 |
| `LOGGING_PROBLEM` | no heartbeat for > 35 s while the session is active and not explained by a `connection_lost` or `page_load` | separate lane, low rank |

**Rule score** = sum of flag weights + 1 per extra distinct kind + 1 if any two flags fall within 120 s. Always show the breakdown. Score, pace, reloads, drops and self-report are context in the packet, never flags.

### 7.5 Evidence packet (JSON, candidate ID only)

`candidate_id`, `flags[]` (id, kind, `server_ts`, `elapsed_s`, `question_number`, `detail`), `questions[]` (number, section, difficulty or null), `vs_sitting` (percentiles, or `cohort_skipped: too_small`), `score`, `pace_s_per_q`, `innocent_signals[]` (drops, reloads, device events, self-report category and short note), `mic_silence[]` (muted or silent stretches: start and end `server_ts`, `duration_s`, which layers saw it; context only, never a flag), `video_anchor`, and a `facts` block: every question number, whole-second time and count the packet contains. The AI sees `facts`, and the fact checker uses it.

### 7.6 AI assessment (strict JSON)

`candidate_id`, `flags_support_each_other` (`yes`/`partly`/`no`), `innocent_explanation` {`present`, `evidence_ids[]`}, `strength` (1–5), `explanation` (≤ 80 words), `cited` {`flag_ids[]`, `question_numbers[]`, `times_s[]`, `counts{}`}.

Fact check: every cited value must be in the packet; every number and "Q" reference found in the explanation text must be in `facts`; verdict words (`cheated`, `guilty`, `disqualify`, `reject`) fail it. One retry, then fall back to the rule order. Final order = AI `strength` if it passed, otherwise a 1–5 bucket mapped from the rule score; ties broken by rule score. The AI can reorder; it can never remove anyone.

### 7.7 Ollama model tiers (decide on D11 from measured seconds per packet)

| Your laptop | Try first |
|---|---|
| ≥ 16 GB RAM | 7–8B instruct, 4-bit (`qwen2.5:7b-instruct`, `llama3.1:8b`) |
| 8 GB RAM | ~3B (`llama3.2:3b`, `qwen2.5:3b`) |
| Slower than 2 min per packet | shrink the packet, drop a tier, or send only the top-N rule-ranked packets to the AI and use the rule order for the rest (nobody is lost) |

Settings: temperature 0, `num_ctx` 4096, `stream: false`, JSON schema passed as `format`.

### 7.8 Microphone muting checks

A web page cannot stop a candidate muting the microphone (a hardware switch, a headset button, the Windows privacy toggle). So the plan detects it in three layers: the browser layers (1 and 2) warn the candidate live, and all three layers feed what the reviewer is shown. It never blocks the test and never raises a flag.

| Layer | Where | How | Result |
|---|---|---|---|
| 1. Track events | Browser, `lib/media.ts` | `onmute` / `onunmute` on the audio track | `mic_muted` / `mic_unmuted` logged at once; a mute counts toward the banner timer in layer 2 |
| 2. Live level watch | Browser, `lib/micWatch.ts` | An `AnalyserNode` on the shared stream, read every 250 ms. A window is *flat* when its peak sample is below `MIC_FLAT_PEAK` (default 0.0005). Audio is requested with `echoCancellation`, `noiseSuppression` and `autoGainControl` all `false`, so a live mic in a quiet room keeps a faint noise floor and a muted one stays flat | After `MIC_SILENCE_SECONDS` (default 60) of flat signal or mute: banner plus `mic_silent_start` (back-dated to when the flat run began). Signal back for 1 s: banner clears plus `mic_silent_end{duration_s}` |
| 3. Server scan | `services/audio/silence.py`, job `detect_silence` | After assembly (D8): `ffmpeg -i seg.webm -vn -af silencedetect=noise=-65dB:d=60 -f null -`, parsing `silence_start` / `silence_end`. Thresholds in `MIC_SILENCE_DB` and `MIC_SERVER_MIN_SILENCE_SECONDS` | Rows in `audio_silences`; `server_ts` = segment start + offset (the D7 anchor formula) |

**Banner** (`MicBanner.tsx`): non-blocking, `role="status"`, above the question and clear of the options and the Submit button. Text (placeholder): "Your microphone looks muted or silent. Please unmute it and keep it on for the whole test. Your test continues." The countdown and the answer buttons are untouched.

**Packet:** `build_packet` merges the layers into `mic_silence[]`: every stretch the server scan (layer 3) found and every stretch the browser (layers 1 and 2) reported, which is the same moment the candidate saw the banner. Stretches that overlap in time are listed once, and the entry lists which layers saw it (`server`, `browser`, or both), so the reviewer can tell whether the candidate was warned and whether the saved audio confirms it. A browser-only stretch (for example when the audio never uploaded) and a server-only stretch (for example lost events or a closed tab) both appear. Run `detect_silence` before `build_packet`; without it only browser stretches appear. These stretches add no flag and no weight to the rule score. Their times and counts go in `facts` so the AI can cite them. A stretch shorter than `MIC_SILENCE_SECONDS` (60 s) is left out of the packet; the raw events stay in the `events` table. A "stretch" means 1 minute or more of mute or silence, the same figure for the banner (layer 2) and the server scan (layer 3), so a quick mute to cough triggers nothing.

**Candidate wording** (one constant, `MIC_NOTICE` in `copy.ts`, placeholder until Cytonn approves): "Keep your microphone on for the whole test. If it is muted for a while you will see a warning which will be shown to your reviewer." Used in the device notice (D6, also `docs/candidate-notice.md`), the integrity statement (D3) and the volunteer brief (D14).

**Known limits (list in the handover):** a stretch only the browser saw (for example when the audio never uploaded) is not confirmed by the saved audio, which is why each entry shows which layers saw it; layer 1 depends on whether SEB's browser fires `mute` for OS and hardware mutes (D2 spike check 12 finds out); a mic that outputs a faint hiss when muted passes layer 2; background noise played into the mic defeats all three layers; a very quiet, noise-gated mic can look silent, which is why this is context and not a flag. Thresholds are set on D6 against a live quiet room and a muted mic, and rechecked on D8.

---

## 8. Gaps, ambiguities and risks in the proposal

Ordered by how much they can hurt you. "Handling" is what the plan does about each.

| # | Issue | Handling in this plan |
|---|---|---|
| R1 | **Resume-upload for 48 h vs SEB closing.** Once the candidate quits SEB nothing can upload, and SEB may wipe its browser storage on exit. The proposal doesn't say how upload resumes. | D2 spike tests whether IndexedDB survives quit and relaunch. Plan A: keep SEB open until upload finishes, then send the candidate to SEB's **Quit URL**. Plan B (if storage survives): a `/resume` start URL reopened in SEB within 48 h. Plan C: mark `upload_incomplete` and use the complaint path (the proposal already allows this). |
| R2 | **SEB is the whole foundation and the riskiest part.** Camera/mic permissions in the SEB config, whether `getUserMedia` and `MediaRecorder` work inside SEB, what the page can observe. | D2 is a dedicated spike with a go/no-go. Don't start D3 until it is decided. Escalate to Douglas the same day if recording doesn't work. |
| R3 | **Pilot is on the last build day** (28 Oct); measurement the same day; handover next day. No time to fix what the pilot reveals. | D14 is a full dry run and freeze. Book volunteers by D8. Prepare the metrics scripts before D15 so measurement is a run, not a build. |
| R4 | **Pilot arithmetic is tight.** 6 cheaters in 12–16 people means "top third" is 4–5 slots, and "at most 1 in 10 honest flagged" allows **zero** false flags with 8 honest. | Define "flagged" (A10) and measure "top third" **among queued candidates**. Recruit ≥ 10 honest volunteers. State the small-n caveat in the report (the proposal already does). |
| R5 | **Seekable video.** MediaRecorder chunks only play when joined, and the WebM has no duration or seek index. The "within 2 seconds" criterion needs a precise anchor. | Single recorder with timeslice; `recording_started` event gives the server-time anchor; ffmpeg remux (`-c copy`) on assembly; `segment` index so a camera drop and restart doesn't break the mapping. |
| R6 | **Heartbeat vs background throttling.** Browsers slow timers in unfocused windows, which would look like a "logging problem". | Heartbeat tick runs in a Web Worker; 35 s tolerance; gaps overlapping a drop or reload are context, not a flag. |
| R7 | **SEB verification mechanics.** The hash covers the exact URL; behind a proxy the server must know the public URL. Config Key vs Browser Exam Key. HTTPS is required for the camera outside localhost. Anyone holding the key can spoof it. | `PUBLIC_BASE_URL` setting; `SEB_MODE=off/log/enforce`; D2 checks that `fetch()` calls carry the header (or uses SEB's JS API to read the keys); document HTTPS as a production requirement; list "spoofable" in known limits. |
| R8 | **"Every blocked attempt is logged."** If SEB blocks copy/paste/print-screen at OS or keyboard-hook level, the web page may never see the attempt. | D2 records which attempts the page can observe. Adjust the claim to what is actually loggable and say so in the handover. |
| R9 | **Retention hole.** Videos are deleted 30 days after a *review decision*. Candidates who are never flagged, never shortlisted, or never reviewed have no decision, so nothing deletes their video. Also, "shortlisted" has no source (no link to Cytonn's system). | Reviewers mark candidates shortlisted in the app. Deletion job also reports undecided sessions older than a limit for a human to decide. Ask Cytonn (§10, "Needed for review and retention"). |
| R10 | **Thresholds are undefined** ("far longer", "far from typical", idle time, "run", what counts as flagged). | Section 7.4 defaults, all configurable, tuned on the synthetic honest cohort, never on the cheaters alone. |
| R11 | **Promised but not scheduled:** complaint filing, device-requirement notice, data-use/Wi-Fi notice, integrity statement and self-report wording, reviewer login, reviewer outcome options. | Each is placed on a day (complaints D8; notices D6; integrity/self-report D3; reviewer login and outcomes D13). Wording is a placeholder until Cytonn supplies it. |
| R12 | **Mic muted after the pre-check; virtual camera.** The proposal gates the start on a working mic but says nothing about muting afterwards, and a page cannot prevent it. The scripted-test criterion also mentioned OBS; virtual-camera testing is out of scope. | Three-layer detection (§7.8): browser mute events, a live level watch and a server scan of the saved audio. Warn with a non-blocking banner, log, show the reviewer as context; no block and no flag. The notice tells candidates the mic must stay on. Virtual camera and muted mic are not scripted-run or pilot scenarios. Confirm with Cytonn (§10). |
| R13 | **AI "ranks" vs a small context window.** Ranking all candidates in one prompt won't fit on a laptop. | Assess each packet separately, then sort. |
| R14 | **Speed.** "Under 2 minutes per flagged candidate" depends on hardware nobody has named. | D11 benchmark; model tiers in 7.7; top-N fallback. |
| R15 | **Cohort statistics are distorted by cheaters** in a group of ~14, and meaningless below ~8. | Median/MAD instead of mean/SD; below 8 the cohort checks are skipped and the packet says so. |
| R16 | **Own laptop is server, database, AI host, and camera.** Docker Desktop + Postgres + Ollama + SEB can run out of RAM. | Measure on D1/D11. Run the AI step *after* the sitting closes, not during it. |
| R17 | **Claude API not yet paid for.** | All acceptance runs on Ollama. The Claude adapter is tested with mocked responses only and listed as "untested live" in the handover. |
| R18 | **Device claims.** Mac and iPad are listed as allowed but only Windows is tested. | Candidate-facing text says "tested on Windows"; flag it in the handover. |
| R19 | **Timestamps vs offline queue.** The proposal says events are server-timestamped, but events made while offline arrive later. | `age_ms` correction (7.3). |
| R20 | **Legal and operations.** DPIA, consent wording, storage location, retention. Kenya's Data Protection Act 2019 will apply. The proposal says they don't block the volunteer pilot, but they do block production. | Keep consent text and retention values in config; list as open sign-offs in the handover. Candidate free-text in the self-report may contain names: cap length and redact obvious emails and phone numbers before it goes into a packet. |
| R21 | **Free-text self-report in packets** could contain a name, which breaks "never the name". | Cap at 300 characters, redact emails/phones, show category in the packet and the text only in the reviewer view. |

---

## 9. Success criteria → test → day

| Proposal criterion | Target | How it is tested | Script / test | First testable | Final run |
|---|---|---|---|---|---|
| Rule-based checks catch scripted actions | 100% | Scripted tests; one run in real SEB (virtual-camera and muted-mic scenarios are out of scope) | `eval/scripted_actions.md`, `tests/integration/test_scripted_scenarios.py`, `frontend/e2e/scripted-cheater.spec.ts` | D5 | D14 (real SEB) |
| Honest volunteers wrongly flagged | ≤ 1 in 10 | Pilot plus a synthetic honest cohort | `eval/metrics/false_flags.py` | D10 | D15 |
| Planted cheating caught | ≥ 8 in 10 | Pilot | `eval/metrics/compute_metrics.py` | D10 (synthetic) | D15 |
| Planted cheaters ranked in top third | ≥ 8 in 10 | Pilot | `eval/metrics/compute_metrics.py` | D10 (synthetic) | D15 |
| Flag lands near the moment in the video | within 2 s | Observer logs real time of 5–6 planted actions | `eval/metrics/video_offset.py`, `eval/pilot/observer-sheet.md` | D13 (rehearsal) | D15 |
| AI explanations match the logs | 100% | Automatic fact check, then by hand | `eval/metrics/ai_explanations.py` | D12 | D15 |
| No video chunks lost after upload | 0 missing | Simulated drops, and two volunteers offline for 2 minutes | `eval/metrics/chunk_integrity.py`, Playwright offline test | D8 | D15 |
| Papers match the blueprint *(only if S1 is built)* | 500 of 500 | Validator | `services/blueprint/validator.py` | D10 | D10 |
| Deletion works | video gone 30 days after decision | Test with backdated decisions | `tests/integration/test_purge.py` | D14 | D14 |
| AI step runs on the available laptop | < 2 min per flagged candidate (proposed) | Timed in the pilot | `rank` job timing, `eval/metrics/ai_benchmark.py` | D11 | D15 |

---

## 10. Questions to ask Cytonn

Ask the **blocking** ones first. "Needed by" is the day the answer starts to matter.

### Blocking early

| Needed by | Question |
|---|---|
| D2 | **SEB:** Who owns the SEB config? Config Key or Browser Exam Key for verification? Which SEB versions are allowed? Can the camera and microphone be enabled in the config, and is that allowed by their policy? |
| D3 | **Test shape:** How many questions per test and how many sections? Time limit? Options per question? Negative marking? What is the difficulty-tag scale? |
| D8 | **Question data:** Will the per-question summary (question ID, section, correct option, difficulty tag, n, % correct, median/p25/p75 time) arrive, in what format, and on what date? If not, can I have the question bank export? |
| D8 | **Pilot:** Who are the volunteers (≥ 10 honest, 6 for scripted cheating), what date and time on 28 Oct, what venue and network? Windows machines only. Consent wording for volunteers. An observer for the timing check. |
| D9 | **Typical sitting size**, staggered or fixed start, and how a "sitting" closes (the cohort checks run after it closes; needs ≥ 8). |

### Needed for review and retention

| Needed by | Question |
|---|---|
| D13 | **Reviewers:** Who are they, how many, how do they log in? What decision outcomes do they need? What happens to a candidate after a decision? |
| D13 | **Shortlist:** The proposal reviews video for "the shortlisted candidates", but the layer isn't linked to Cytonn's system. How does the shortlist reach the reviewer? (Plan: reviewer marks it in the app.) |
| D14 | **Retention:** What deletes the video of candidates who are never flagged, shortlisted or reviewed? How long are events, packets and decisions kept? Where is storage located? |
| D14 | **Complaints:** Who reviews them, and in what time? What can a complaint change? |
| D14 | **Accessibility:** What route exists for candidates who cannot use SEB or a webcam? |

### Policy and metrics

| Question |
|---|
| **Muted mic during the test:** the plan warns the candidate and shows silent stretches to the reviewer as context (no block, no flag). Confirm, and confirm the notice wording (§7.8). |
| **Definition of "flagged" for the pilot metrics:** confirm "rule score ≥ 1.0 enters the queue; a lone focus loss does not", and that "top third" means among queued candidates. |
| **Recruitment pipeline result format:** the proposal asks for it even though the link is out of scope. What is it for, and does anything need to be exported? |
| **Production hosting:** where will the server run, with HTTPS? Who runs Ollama or pays for the Claude API? |
| **Sign-offs for production** (these don't block the pilot): DPIA, consent wording, storage location, 30-day retention, and who owns the open items after handover. |
| **Candidate-facing wording:** integrity statement, self-report question, device-requirement notice, data-use notice, mic-must-stay-on notice. Placeholders are used until supplied. |

---

## 11. Cut list (in this order, if you fall behind)

1. S1 blueprint generator and validator (the related criterion then doesn't apply).
2. Complaint UI polish (keep the endpoint and a plain form).
3. Reviewer UI styling (keep function).
4. Playwright cheater scripts (fall back to pytest event streams, which already cover the rules).
5. Top-N AI (send fewer packets to the AI if the laptop is slow).

**Never cut:** the SEB gate, camera/mic gate, zero-loss upload, the fact check and fallback, written reasons on decisions, the audit log, and 30-day deletion. These are the proposal's promises.

---

## 12. Definition of done for the whole project

- Every criterion in section 9 has a measured result in `eval/reports/pilot-report.md` (or "not built" for S1).
- A reviewer can log in, work the queue in rank order, jump to each flag in the video 5 s early, record a decision with a written reason, and see all of it in the audit log.
- Every flagged candidate reaches the queue, with or without a working AI.
- `docs/handover.md` lists known limits, untested items (Mac/iPad, Claude live, hosted HTTPS), and Cytonn's open sign-offs.
