# Week 3: Per-question check, AI ranking, reviewer app, deletion, pilot (+ handover)

**Dates:** Thu 22 Oct – Wed 28 Oct 2026, then Thu 29 Oct (handover) · **Days:** D11 Thu 22 · D12 Fri 23 · (Sat–Sun buffer) · D13 Mon 26 · D14 Tue 27 · D15 Wed 28 · Handover Thu 29
**Branches:** one per task (`<type>/<short-task>`, see [master plan §5](00-master-plan.md#5-working-method)), started from `main` at tag `week-2` · **Tag on `main` at end of week:** `week-3`
**Back to:** [00-master-plan.md](00-master-plan.md) · **Previous:** [week-02.md](week-02.md)

## Goal

Reviewers can work a ranked queue and jump to the right moment in the video. A local AI model re-ranks and explains, with a fact check and a guaranteed fallback. Videos are deleted 30 days after a decision. The pilot runs, and every success criterion has a measured result.

## Week at a glance

| Day | Focus | You can demo at the end of the day |
|---|---|---|
| D11 Thu 22 | Per-question check; `Ranker` interface; Ollama ranker; model benchmark | One packet in, valid JSON out; seconds per packet known |
| D12 Fri 23 | Fact check, retry, fallback, batch runner; Claude adapter | Hallucinations rejected; Ollama down → rule order, nobody lost |
| D13 Mon 26 | Reviewer app: queue, packet, video at flag − 5 s, decisions, audit | Click a flag, land in the video; decision needs a reason |
| D14 Tue 27 | 30-day deletion; full scripted run in a real browser; **dry run and freeze** | Backdated-decision test passes; pilot checklist ticked |
| D15 Wed 28 | **Pilot sitting and measurement** | `eval/reports/pilot-report.md`; tag `week-3` |
| Thu 29 | Handover walkthrough with Douglas; then integration questions and bug fixes only | `docs/handover.md` |

**This week has no slack.** The pilot is the last build day. If any day slips, use the weekend buffer first, then the cut list in [master plan §11](00-master-plan.md#11-cut-list-in-this-order-if-you-fall-behind).

**Confirm by Mon 26 Oct:**
- [ ] Pilot date, time, venue and network, and the volunteer list (≥ 10 honest, 6 scripted cheaters, an observer).
- [ ] Reviewer logins and the decision outcomes Cytonn wants.
- [ ] The answer on the "flagged" definition (rule score ≥ 1.0).

---

## D11: Thursday 22 Oct. Per-question check, Ranker interface, Ollama

**Goal:** answers that are correct far faster than a question's usual time are flagged; one evidence packet goes through Ollama and comes back as valid, strict JSON; you know how long it takes on your laptop.

### Steps

- [ ] **1. Branch (2 min):** `git switch main`, then one branch per task, for example `git switch -c feat/per-question-check`. Merge each into `main` with `--no-ff` when its tests pass. Suggested names: `feat/per-question-check` and `feat/ollama-ranker` (D11), `feat/fact-check-runner` and `feat/claude-adapter` (D12), `feat/reviewer-app` (D13), `feat/video-purge` and `test/pilot-dry-run` (D14), `feat/pilot-metrics` (D15), `docs/handover` (29 Oct).
- [ ] **2. Per-question check (75 min):** `services/flags/history.py` (pure function) + wire into `compute_session_flags`.
  - For each answer that was correct and has `question_stats` with `n ≥ 30`: fast if `time < 0.5 × p25_s` (ratio from `FlagConfig`).
  - Flag `FAST_CORRECT_VS_HISTORY` only if the candidate has **at least 2** such questions. Weight 2; any hard question in the set multiplies by 1.5. `detail` lists question numbers, times, p25 and difficulty, and `history_source` (`cytonn` or `synthetic`).
  - If the stats are synthetic, still flag, but the packet shows `history_source: synthetic` so a reviewer knows the baseline is made up.
  - **Test:** two fast-correct questions → flagged; one fast-correct → no flag; fast but wrong → no flag; fast on hard questions → weight 3; `n < 30` ignored; a candidate who is simply fast on *everything* but whose times aren't below 0.5 × p25 → no flag. Add the `fast_correct` archetype to the simulator, and update `eval/scripted_actions.md`.
- [ ] **3. Install and pull a model (30 min):** install Ollama for Windows. Pick the tier from master plan §7.7 using your D1 spec (≥ 16 GB RAM: `ollama pull qwen2.5:7b-instruct`; 8 GB: `ollama pull qwen2.5:3b`). Check: `ollama --version` is 0.5 or newer (schema-constrained JSON output needs it) and `curl http://localhost:11434/api/tags` lists the model. If the Docker `api` container can't reach it, either set `OLLAMA_HOST=0.0.0.0` on the host or run the `rank` job from the host venv (simplest — the AI step is a batch job run after the sitting).
- [ ] **4. `Ranker` interface and `Assessment` schema (30 min):** finish `ranking/base.py`:
  - `Assessment` (pydantic, master plan §7.6) with strict validation: `strength` 1–5, `explanation` ≤ 80 words, the `cited` object.
  - `class Ranker(Protocol): name: str; model: str; def assess(self, packet: dict) -> Assessment`.
  - `get_ranker(settings)` picks `RuleRanker`, `OllamaRanker` or `ClaudeRanker` from `AI_PROVIDER`. **Nothing else in the app imports a specific provider.**
- [ ] **5. Prompt (45 min):** `ranking/prompts.py`: a system prompt that says:
  - you are helping a human reviewer; you only rank and explain; you never give a verdict, never say anyone cheated, never recommend rejecting or disqualifying;
  - use only facts in the packet; cite flag IDs; mention an innocent explanation if the packet has one;
  - answer with the JSON schema only; explanation ≤ 80 words.
  Include the packet JSON (including its `facts` block) and the schema. Keep the packet short: if it is over about 1,500 tokens, drop `detail` fields in this order: device labels, then repeated focus losses (summarise as a count).
- [ ] **6. `OllamaRanker` (60 min):** `ranking/ollama.py` using `httpx`: `POST {OLLAMA_BASE_URL}/api/chat` with `model`, `messages`, `stream: false`, `format: Assessment.model_json_schema()`, `options: {temperature: 0, num_ctx: 4096, seed: 7}`, timeout 150 s. Parse `message.content` with `Assessment.model_validate_json`. Surface HTTP errors, timeouts and JSON errors as one `RankerError`.
- [ ] **7. Benchmark (60 min):** `eval/metrics/ai_benchmark.py`: generate 10 packets from the simulator (mix of cheater and honest archetypes), run each through the Ollama ranker, and record seconds per packet, tokens per second (`eval_count / eval_duration` from the response), and the share of valid JSON. Write the table to `docs/spikes/ollama-benchmark.md`.
  - **Target:** under 2 minutes per packet. If you miss it, apply the escape routes in master plan §7.7 (shorter packet → smaller model → top-N only). Make the model name a config value and record the final choice.

### How to test the day
- **pytest:** history-check boundary cases; `Assessment` rejects `strength=7` and an 81-word explanation; `OllamaRanker` against a mocked HTTP response returns a parsed `Assessment`; a mocked timeout raises `RankerError`; the prompt snapshot contains no `name`/token fields.
- **Live (marked `@pytest.mark.ollama`, skipped by default):** one real call returns valid JSON.
- **Benchmark:** table filled in; chosen model recorded.

### Commits
```
git commit -m "feat(flags): per-question check against past-sitting statistics"
git commit -m "test(flags): fast-correct boundary cases and fast_correct archetype"
git commit -m "feat(ranking): Assessment schema, Ranker protocol and provider factory"
git commit -m "feat(ranking): reviewer-support prompt with no-verdict rules"
git commit -m "feat(ranking): Ollama ranker with structured JSON output"
git commit -m "docs(eval): Ollama benchmark and chosen model"
```

---

## D12: Friday 23 Oct. Fact check, retry, fallback, runner, Claude adapter

**Goal:** the AI can never put a wrong fact in front of a reviewer, and if it fails, the rule order is used. No candidate is ever lost.

### Steps

- [ ] **1. Fact checker (90 min):** `ranking/factcheck.py::fact_check(assessment, packet) -> list[Violation]` (pure function). It checks that:
  - `candidate_id` matches the packet;
  - every `cited.flag_ids` entry exists in the packet's flags;
  - every `cited.question_numbers` entry exists in the packet's questions;
  - every `cited.times_s` entry is one of the packet's times (whole seconds, exact match);
  - every `cited.counts` key/value equals a count in the packet's `facts.counts`;
  - every number and every `Q<number>` / "question <number>" found by regex in the `explanation` text is in `facts`;
  - the explanation contains none of the verdict words: `cheat`, `guilty`, `disqualif`, `reject`, `fraud`, `dishonest`;
  - `innocent_explanation.evidence_ids` all exist in the packet.
  Each violation says which rule failed and what value was unknown, so you can feed it to the retry prompt.
- [ ] **2. Runner (90 min):** `ranking/runner.py::rank_sitting(db, sitting_id, ranker, clock)`:
  1. For each flagged session (those with a rule rank), call `ranker.assess(packet)`.
  2. Run the fact check. If it fails (or the call raises `RankerError`), call once more with the violations appended to the prompt ("These claims are not in the packet: …").
  3. If the second attempt fails, set `ai_status='fallback'` and keep the rule explanation.
  4. Store `ai_json`, every attempt in `ai_attempts` (including the raw output and violations, for audit), and `ai_seconds`.
  5. **Final order:** AI `strength` if it passed, otherwise a 1–5 bucket mapped from `rule_score` (thresholds in config); ties broken by `rule_score`, then earlier first flag. Write `final_rank`.
  6. **Guarantee:** `assert len(ranked) == len(flagged)`. The AI can reorder; it can never drop anyone.
  - `rank` job: `python -m scripts.jobs rank --sitting <id> --provider ollama`; prints the order, status per candidate (`ok`, `retried`, `fallback`) and median/max seconds per candidate.
- [ ] **3. Claude adapter (60 min):** `ranking/claude.py::ClaudeRanker` behind the same protocol. **Open the `claude-api` skill first** (current model IDs, structured output, parameters) rather than writing from memory. Model ID from `CLAUDE_MODEL`, key from `ANTHROPIC_API_KEY`, optional dependency (`pip install -e ".[claude]"`). Same prompt, same `Assessment` schema, same fact check, same runner. Switched on by `AI_PROVIDER=claude`. **Not run live** until the payment clears; mark it clearly in the handover.
- [ ] **4. Explanation-accuracy script (30 min):** `eval/metrics/ai_explanations.py --sitting <id>`: runs the automatic fact check over all stored AI outputs (target 100%) and writes `eval/reports/ai-explanations-handcheck.csv` (candidate, explanation, the packet facts side by side) for you to tick off by hand on D15.
- [ ] **5. Live end-to-end on synthetic cohorts (30 min):** run `rank --provider ollama` on three simulated sittings; read every explanation yourself.

### How to test the day
- **Hallucination table (pytest):** each of these must produce a violation and trigger the retry path: a flag ID not in the packet; `Q99`; a time of 999 s; a count mismatch; the word "cheated"; a number in the text that isn't in `facts`; the wrong `candidate_id`.
- **Retry path:** mock a ranker that fails once then passes → `ai_status='retried'`; fails twice → `fallback` and the rule explanation shown.
- **Ollama down:** stop Ollama → every candidate gets `fallback`; order equals the rule order; row count equals the flagged count.
- **Timing:** median and max seconds per candidate under 2 minutes on your laptop (otherwise apply the escape routes from D11).
- **Claude adapter:** the same fact-check test file passes against a mocked HTTP response.

### Commits
```
git commit -m "feat(ranking): fact checker for cited ids, question numbers, times, counts and explanation text"
git commit -m "feat(ranking): sitting runner with one retry, rule-order fallback and audit of attempts"
git commit -m "test(ranking): hallucination table, retry path, Ollama-down fallback keeps every candidate"
git commit -m "feat(ranking): Claude adapter behind the Ranker interface (mocked tests only)"
git commit -m "feat(eval): AI explanation accuracy script and hand-check sheet"
```

---

## D13: Monday 26 Oct. Reviewer app

**Goal:** a reviewer logs in, sees the queue in rank order, opens a candidate, clicks a flag, lands in the video 5 seconds before it, and records a decision with a written reason. Every decision and video view is logged.

### Steps

- [~] **1. Reviewer accounts and login (45 min):** **built early** on `feat/staff-login-and-nav` (see `docs/plan/staff-login-and-navigation.md`): migration `0002` has `reviewers` (with `role` and `is_active`) and `audit_log`; `create_reviewer` and `deactivate_reviewer` jobs (bcrypt, 12 characters minimum); `POST /api/review/login` returns a signed 8 h token and `GET /api/review/me` is the first route behind `require_reviewer`; `require_admin` exists; failures are limited per address and per email; `login` is audited. **Still to do here:** the `decisions` table and its migration, and `require_reviewer` on each new `/api/review/*` route.
- [ ] **2. Queue and candidate endpoints (75 min)**
  - `GET /api/review/queue?sitting=` → ordered by `final_rank`: candidate ID, rank, rule score, AI strength and status (`ok`/`retried`/`fallback`), flag kinds, decision status, shortlisted. The `LOGGING_PROBLEM`-only lane sits at the bottom, clearly labelled.
  - `GET /api/review/candidates/{id}` → packet, flags (each with `video_seek_s`), AI explanation (or the rule explanation), complaints, decisions, and the segment list from D8.
  - **Seek maths** (`services/video/seek.py`, pure and unit-tested): for a flag at `server_ts`, find the segment whose `[start, start + duration]` contains it; `seek_s = max(0, (server_ts − segment_start) − 5)`. If no segment contains it, return `no_video_at_moment` (a camera drop, or an incomplete upload).
  - `POST /api/review/candidates/{id}/shortlist` toggles the shortlist flag (master plan R9: the app's stand-in for the missing link to Cytonn).
  - **Who can see video:** candidates in the queue, or shortlisted. Others return 403.
- [ ] **3. Video endpoint (60 min):** `GET /api/review/candidates/{id}/video?segment=n` streams the assembled file (call `ensure_assembled` from D8 on first use) with HTTP Range support so the player can seek. Verify that scrubbing in a browser works; if Starlette's `FileResponse` doesn't honour Range in your version, write a small Range handler. Log a `video_view` audit entry on the first request for a (reviewer, session, segment) in a 5-minute window, plus an explicit `POST …/video-view {flag_id}` when the reviewer jumps to a flag.
- [ ] **4. Decisions (45 min):** `POST /api/review/decisions {session_id, outcome, reason}`. Outcomes (placeholders until Cytonn confirms): `no_concern`, `concern_noted`, `refer_for_follow_up`. `reason` is required, at least 20 characters (422 otherwise). Store `decided_at = clock.now()`; audit-log it. A newer decision supersedes an older one, and **the 30 days run from the latest `decided_at`** (write this rule in `docs/handover.md`).
- [ ] **5. Reviewer UI (150 min)**, routes under `/review`:
  - `Login.vue`.
  - `Queue.vue`: table (rank, candidate ID, flag chips, an "AI advisory" badge with strength or "rules only", decision status); filter by sitting.
  - `CandidateDetail.vue`: packet summary (flags with times and question numbers; how the candidate compares with the sitting; score and pace labelled *context only*; innocent signals highlighted; muted or silent mic stretches from `mic_silence[]` listed as context with their times and a **Jump to video** button using the same seek maths), the explanation text with a clear "AI-generated, advisory, not a verdict" label, complaints, past decisions.
  - `VideoPlayer.vue`: an HTML `<video controls>`; each flag has a **Jump to video** button that sets `currentTime` to `seek_s`, shows "starting 5 s before the moment", and handles `no_video_at_moment`.
  - `DecisionForm.vue`: outcome select + required reason + confirm.
  - Plain, readable styling only. Function over looks (cut-list item 3).
- [ ] **6. Seek accuracy rehearsal (45 min):** this is the "flag lands within 2 seconds" criterion, practised before the pilot. Run a test yourself in Chrome. At 5 planted moments (a focus loss, a copy attempt, a long hold, etc.), say "mark" out loud and wave at the camera, and write down the real wall-clock time. Then open the candidate in the reviewer app, jump to each flag, and use `eval/metrics/video_offset.py` to compare the time of the cue in the video with `seek_s + 5`. Record the error for each. **Target ≤ 2 s.** If it's off, check the anchor (D7 step 3) and for event-queue delay (D4 `age_ms`).
- [x] **7. Admin backend (90 min):** **built early** on `feat/staff-login-and-nav` (admin screens now call the real server; the question-bank export's columns are provisional, see `staff-login-and-navigation.md`). the recruiter's setup screens (`frontend/src/admin/`, already built on fixtures) need their endpoints. Add an `admin` role to `reviewers` and a `require_admin` dependency on `/api/admin/*`. Endpoints are thin wrappers over the CLI job functions, so no logic is duplicated: `GET/POST /api/admin/sittings` (list with finished / in-progress / not-started counts, create), `POST /api/admin/sittings/{id}/close {force}` (409 `sessions_unfinished {unfinished}` unless forced; a forced close is audited), `POST /api/admin/invites {count 1-500}` (generates opaque candidate IDs and short codes with `new_invite_code`, returns them once, stores only the hash), `GET /api/admin/questions/summary`, `POST /api/admin/questions/import {filename, summary_csv, bank_csv}` (same checks and report as `import_question_summary`; 409 `sitting_open` while a sitting is open), `POST /api/admin/questions/retire-synthetic` (keeps any question an earlier session points at). Every admin action goes in the audit log. **Then flip the screens off the fixtures:** remove `/api/admin` and `/api/review` from `MOCKED_PREFIXES` in `frontend/src/lib/api.ts`.
  - **Test:** non-admin token → 403; import during an open sitting → 409; forced close is audited; invite codes are returned once and only hashes are stored.

### How to test the day
- **pytest:** no token → 401; unknown outcome → 422; reason of 5 characters → 422; each decision and video view creates an `audit_log` row; seek maths (flag inside segment 0; flag inside segment 1; flag in a gap; flag in the first 3 s → `seek_s=0`); non-queued, non-shortlisted candidate's video → 403.
- **Playwright click-through:** login → queue → candidate → jump to flag → decision.
- **Manual:** scrub the video around; check the rehearsal table.

### Commits
```
git commit -m "feat(review): reviewer accounts, login and audit log"
git commit -m "feat(review): ranked queue and candidate detail with flag-to-video seek maths"
git commit -m "feat(review): range-capable video streaming with view audit"
git commit -m "feat(review): decisions require a written reason; shortlist toggle"
git commit -m "feat(ui): reviewer queue, candidate detail, video jump and decision form"
git commit -m "test(review): auth, validation, audit and seek accuracy script"
```

---

## D14: Tuesday 27 Oct. Deletion, real-browser scripted run, dry run, freeze

**Goal:** deletion is proven, the scripted-action run has been done in a real browser, and the whole pilot has been rehearsed. At the end of today the code is **frozen** (bug fixes only).

### Steps

- [ ] **1. 30-day deletion (90 min):** `services/video/purge.py::purge_due(db, store, clock, retention_days)`:
  - Sessions whose latest `decided_at + 30 days ≤ clock.now()` and `video_deleted_at is null`: delete every chunk file and the assembled files via `VideoStore.delete_session`, set `video_chunks.deleted_at`, set `sessions.video_deleted_at`, write an audit entry `video_purged`.
  - Idempotent. Keep the metadata rows (so the manifest and the audit trail still make sense) but not the video.
  - The video endpoint returns 410 for a purged session; the reviewer page says "video deleted on …".
  - `python -m scripts.jobs purge_videos [--report]`: `--report` also lists undecided sessions with video older than a configurable number of days (default 60), so a human decides what to do (master plan R9; question for Cytonn).
  - The `worker` container runs `scripts.jobs loop`, which runs `purge_videos` hourly.
  - **Test (this is the "deletion works" criterion):** with a `FakeClock`, create decisions at day −31, −30 (boundary) and −29; run purge; the −31 and −30 cases are deleted and the −29 case is kept; files are gone from disk; a second run does nothing; the video endpoint returns 410. **Real-clock version:** `update decisions set decided_at = now() - interval '31 days' where …;` then run the CLI.
- [ ] **2. Remove dev-only bits (15 min):** delete the D2 spike page (`frontend/public/spike`); make sure `CHUNK_FAIL_RATE` and `?sim=drop-events` are off by default and ignored when `ENV=production`; build the frontend without `VITE_MOCK_API` and without `VITE_MIC_CHECK=off`.
- [ ] **3. Full scripted run in a real browser (75 min):** everything in `eval/scripted_actions.md`, performed by hand in Chrome and then in Edge, at full screen, through `http://localhost:8080`, once. For each action write down *whether the page can see the action at all* (Print Screen and some operating-system shortcuts are invisible to a page; list those as "not observable"). Include:
  - a long hold, a copy attempt, an idle gap, a correct run.
  Then `close_sitting`, `compute_flags`, `rank`; confirm every performed action produced its flag. Save the result in `eval/reports/scripted-run-browser.md`.
- [ ] **4. Dry run of the pilot (120 min):** use 2–3 people (or you on two machines) and run the **entire** pilot procedure with the Compose stack:
  1. start the stack: `docker compose up -d`; start Ollama; check `/api/health`;
  2. hand out invite links, sit the test in Chrome or Edge at full screen;
  3. observers log planted actions with wall-clock time;
  4. close the sitting, compute flags (cohort checks are skipped below 8 — expected), run the silence scan, build packets, rank with Ollama;
  5. log in as a reviewer, check each flag's video jump, record decisions;
  6. time every step.
  Fix anything that blocks. Anything that doesn't block goes to the post-pilot list.
- [ ] **5. Prepare pilot-day material (60 min):** `eval/pilot/runbook.md` (start-up checklist, network check, what to do if a camera or microphone permission is blocked, who does what), `eval/pilot/cheater-scripts.md` (6 scripts, below), `eval/pilot/observer-sheet.md` (per planted action: candidate ID, action, **wall-clock time to the second**), `eval/pilot/volunteer-brief.md` (what is recorded, data use ≈ 80 MB/h, Wi-Fi, consent wording, where to complain, and the `MIC_NOTICE` line from master plan §7.8: keep the mic on for the whole test, and the warning is shown to the reviewer).
  - Suggested scripted roles: **C1** tab-out to look something up on 4 questions; **C2** copy the question text on 3 questions; **C3** go idle for 90 s, then answer 4 questions quickly and correctly; **C4** answer every question in a near-identical short time; **C5** answer many questions correctly in a fraction of the usual time; **C6** a mixed set (one tab-out, one copy, one long hold). Each also performs 5–6 timed, observer-logged actions for the video-timing check.
  - Also assign two honest volunteers to go offline for 2 minutes (the chunk-loss criterion).
- [ ] **6. Freeze (30 min):** `pg_dump` a backup; run the whole test suite; tag `rc-pilot`; from now on, only fixes for blockers.

### How to test the day
Backdated deletion test passes (fake clock **and** real SQL clock). The scripted run file is complete. The dry run completes end to end with no blocker open.

### If behind
Do steps 1, 3 and 4 in that order; step 5 can be done on the evening of D14 or the morning of D15 before volunteers arrive. Virtual-camera (OBS) and muted-mic runs are out of scope and are not part of the browser run.

### Commits
```
git commit -m "feat(video): 30-day purge job with audit trail and undecided-session report"
git commit -m "chore(worker): hourly purge loop in the worker container"
git commit -m "test(video): backdated-decision deletion on fake and real clocks"
git commit -m "chore: remove spike echo route and disable fault injection outside dev"
git commit -m "docs(eval): scripted run in a real browser, pilot runbook, observer sheet and cheater scripts"
git commit -m "fix: issues found in pilot dry run"
git tag rc-pilot
```

---

## D15: Wednesday 28 Oct. Pilot sitting and measurement

**Goal:** run the pilot with 12–16 volunteers (≥ 8 honest, 6 following scripted cheating, ideally ≥ 10 honest), measure every criterion, and write the result down honestly, including the ones that miss.

### Steps

- [ ] **1. Pre-flight (45 min before volunteers):** `docker compose up -d`; `/api/health` ok; Ollama running with the chosen model; each volunteer's invitation link ready and **their role (honest or C1–C6) recorded in `eval/pilot/truth.csv`** (candidate ID, role, planted actions); observers have their sheets; Wi-Fi checked; disk space checked (≈ 80 MB/h × 16).
- [ ] **2. Run the sitting (≈ 60–90 min):** volunteers pre-check, test, upload. You are watching `/api/health`, the chunk counts and the heartbeat table for trouble; don't fix code mid-sitting. Two honest volunteers go offline for 2 minutes (as briefed).
- [ ] **3. Wait for uploads:** check each candidate's manifest until `complete`, or note which ones aren't (and why).
- [ ] **4. Process the sitting (time each step):**
  ```powershell
  python -m scripts.jobs close_sitting --sitting <id>
  python -m scripts.jobs compute_flags --sitting <id>      # includes cohort checks (sitting ≥ 8, closed)
  python -m scripts.jobs detect_silence --sitting <id>     # server scan for muted/silent mic stretches
  python -m scripts.jobs build_packets --sitting <id>
  python -m scripts.jobs rank --sitting <id> --provider ollama   # records seconds per candidate
  ```
- [ ] **5. Measure (60 min):** `eval/metrics/compute_metrics.py --sitting <id> --truth eval/pilot/truth.csv`, and the other scripts, to fill this table in `eval/reports/pilot-report.md`:

  | Criterion | Target | How measured | Result | Pass? |
  |---|---|---|---|---|
  | Rule-based checks catch scripted actions | 100% | `scripted_actions.md` register + the real-browser run (D14) | | |
  | Honest volunteers wrongly flagged | ≤ 1 in 10 | honest volunteers with score ≥ 1.0 ÷ honest total; plus the 500-candidate synthetic result (D10) | | |
  | Planted cheating caught | ≥ 8 in 10 | cheaters in the queue ÷ 6 | | |
  | Planted cheaters ranked in top third | ≥ 8 in 10 | cheaters in the top third of queued candidates ÷ 6 | | |
  | Flag lands near the moment in the video | within 2 s | `video_offset.py` on the observer's 5–6 timed actions | | |
  | AI explanations match the logs | 100% | `ai_explanations.py` (automatic) + the hand-check CSV | | |
  | No video chunks lost after upload | 0 missing | `chunk_integrity.py` on every volunteer, including the two offline ones | | |
  | Papers match the blueprint | 500 of 500 | validator run (D10) — **only if S1 built** | | |
  | Deletion works | video gone 30 days after decision | backdated test (D14) | | |
  | AI step runs on the available laptop | < 2 min per flagged candidate | seconds per candidate from step 4 | | |

  Write the caveats the proposal already promises: 12–16 people is indicative, not proof; define "flagged" as you did (rule score ≥ 1.0) and "top third" as among queued candidates; if the pilot had fewer than 8 finished sessions, the cohort checks did not run and you must say so.
- [ ] **6. Hand-check the AI explanations (30 min):** tick off the CSV from D12 against the packets.
- [ ] **7. Look at the misses (30 min):** for every cheater not caught and every honest volunteer flagged, write down which flag/rule is responsible and what you would change. Do **not** change the thresholds today to make the numbers look better; list proposed changes for the handover.
- [ ] **8. Wrap up (30 min):** make sure every task branch is merged into `main`, tag `week-3` on `main`, back up the database and the report.

### Definition of done for Week 3
- [ ] Reviewer app works end to end; decisions need written reasons; decisions and video views are audited.
- [ ] AI ranking has a fact check, one retry, and a rule-order fallback; no candidate is ever lost.
- [ ] 30-day deletion proven with backdated decisions.
- [ ] Pilot report exists with a result for every criterion (or "not built" for S1).
- [ ] Tagged `week-3`.

### Commits
```
git commit -m "feat(eval): pilot metrics scripts and truth-file format"
git commit -m "docs(eval): pilot report"
# all task branches are now merged into main
git switch main
git tag week-3
```

---

## Thursday 29 Oct. Handover (week 4, day 1)

**Goal:** Douglas can run, understand and take over the system. After today: integration questions and bug fixes only.

### Before the meeting (morning, 2 hours)

- [ ] Write `docs/handover.md` covering:
  - what was built and how to run it (`docker compose up`, Ollama, create a reviewer, import a question summary, run a sitting, run the jobs);
  - the environment variables (master plan §3) and what each does;
  - the decision log: thresholds in `flags/config.py` and why, "flagged" = rule score ≥ 1.0, the 30 days run from the **latest** decision, queue/video visibility rules, packet contents;
  - **known limits**, from the proposal (phone photos, second device or person, earpiece, steady low-level cheating, memorised/shared questions) plus the ones found while building: the mic-muting limits in master plan §7.8 (which mutes the page can see, a faint-hiss mic, background noise played into the mic), a browser page cannot stop screenshots, a second monitor, other applications or the developer tools, honest focus loss from notifications and pop-ups, only Windows with Chrome and Edge was tested, what the page cannot observe (from the D2 findings), what happens if upload can't finish (your D2 plan);
  - **untested items:** Mac and iPad, `ClaudeRanker` live (mocked only), HTTPS hosting, scale beyond the pilot;
  - **open sign-offs from Cytonn:** DPIA, consent wording, storage location, retention (including what deletes video for candidates with no decision), complaint process, reviewer outcomes;
  - the pilot results and the changes you propose.
- [ ] Update `README.md` with a short quick-start.
- [ ] Make sure the demo data is clean: a seeded sitting you can show in 5 minutes (use the simulator and the pilot data).

### Walkthrough agenda (45–60 min with Douglas)

1. 5 min: the problem and the one automatic outcome (the camera and microphone gate).
2. 10 min: live walk through the candidate flow in the browser: permissions → test → upload.
3. 10 min: what is logged, the flag list, how a packet looks.
4. 10 min: the ranker: rules, AI, fact check, fallback; show a rejected hallucination.
5. 10 min: the reviewer app: queue → flag → video 5 s early → decision with reason → audit log.
6. 5 min: deletion and the audit trail.
7. 10 min: hosting on Cytonn's side (Douglas's task from the proposal): the server, the HTTPS address and the URL candidates open.
8. 5 min: pilot numbers, known limits, open sign-offs.

### After the meeting

- [ ] Log every question and bug in a list; fix only bugs and integration questions this week.
- [ ] Commit:
  ```
  git commit -m "docs: handover guide, known limits and open sign-offs"
  git commit -m "docs: README quick-start"
  git tag handover
  ```
