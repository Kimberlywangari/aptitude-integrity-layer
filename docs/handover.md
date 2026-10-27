# Handover

For the engineer who takes the system over: how to run it, what was decided and why, what has
not been tested, and what Cytonn still has to sign off.

**Written 21 October 2026, before the pilot.** Sections marked **[after the pilot]** are filled in
once it has run. On 21 October the backend suite had 520 tests passing and 10 skipped, and the
frontend suite had 450 passing. Both are green on the day of writing; re-run them rather than
trusting these numbers.

Written by Kimberly Njoroge. The proposal and the day-by-day plan are kept privately; everything needed to run the system and take it over is in this folder and the README.

## What it is

A layer around Cytonn's aptitude test. The test runs in a normal desktop browser (Chrome or Edge),
full screen. The camera and microphone are recorded, the candidate's actions are logged, rules
raise flags, and a person reviews them. It gives reviewers evidence and never decides anything
about a candidate. The only automatic outcome is that the test does not start until the camera and
microphone work.

## How it fits together

```
browser (Vue 3)  ->  nginx (web, port 80 in the container, 8080 on the host)
                         |  /api
                         v
                     FastAPI (api)  ->  PostgreSQL 16 (db)
                         |          ->  video volume (VIDEO_ROOT)
                         |          ->  Ollama on the host (AI step)
                     worker: the same image, runs hourly housekeeping
```

| Where | What |
|---|---|
| `backend/app/api` | The routes: session, precheck, events, chunks, complaints, review, admin |
| `backend/app/services` | The logic: `test_flow`, `flags/` (rules, scoring, config), `packets`, `ranking/` (rules, Ollama, Claude, fact check, runner), `video/` (store, assemble, seek, purge), `audio/` (silence scan), `review`, `admin` |
| `backend/scripts` | The batch jobs, run as `python -m scripts.jobs <name>` |
| `backend/migrations` | Alembic. Never edit an old migration |
| `frontend/src` | `candidate/` and `entry/` are in the main bundle (about 67 KB gzipped); `reviewer/`, `admin/` and `staff/` are lazy chunks |
| `eval/` | The scripted actions, the pilot pack and the reports |
| `docs/` | This file, the [API reference](api-reference.md), [candidate notice](candidate-notice.md) |

Every route and job is listed in the [API reference](api-reference.md), so this file does not
repeat them.

## Run it

Local development is in the [README](../README.md). The whole thing in containers:

```powershell
docker compose up -d --build        # db, api, worker, web
docker compose exec api python -m scripts.jobs create_reviewer --email you@cytonn.com --role admin
```

Then, at `/login/admin`: import Cytonn's question summary (and the bank export if they send one),
create a sitting, and generate invitations. The codes are shown once, and only their hashes are
stored. Candidates open `<address>/candidate?t=<code>`.

After a sitting:

```powershell
docker compose exec api python -m scripts.jobs close_sitting --sitting "<name>"
docker compose exec api python -m scripts.jobs process_sitting --sitting "<name>" --provider ollama
```

`process_sitting` computes flags (including the sitting-wide checks), joins the video, scans the
audio, builds the packets and ranks them, timing each step. Reviewers then work the queue at
`/review`. The jobs run inside the `api` container because the video is in its volume.

## Settings

All are environment variables; `.env.example` shows the ones to copy into `.env`.

| Setting | Default | What it does |
|---|---|---|
| `ENV` | `development` | `production` refuses to start unless `PRECHECK_GATE=recording`, and switches off the upload fault injection |
| `PRECHECK_GATE` | `off` | `off`, `precheck` or `recording`. Production needs `recording`: the test begins only after a real video and audio chunk has reached the server |
| `SESSION_SECRET` | `change-me-dev-only` | Signs staff tokens and the reviewers' video links. **Nothing stops a production server running with the default.** Set a long random value |
| `PUBLIC_BASE_URL` | `http://localhost:5173` | Builds the links in the invitation CSV the seed writes |
| `VIDEO_ROOT` | `./data/video` | Where chunks and assembled video live. In Compose it is a volume |
| `RETENTION_DAYS` | 30 | Days after the **latest** decision before video is deleted |
| `RESUME_WINDOW_S` | 172800 | How long after finishing a candidate can still upload (48 hours) |
| `UNDECIDED_REPORT_DAYS` | 60 | A recording with no decision this old is listed by `purge_videos --report` |
| `AI_PROVIDER` | `rules` | `rules` means no AI and the rule order stands. `ollama` or `claude` turn the model on |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | host Ollama / `gemma4:e2b` | In Compose the URL is `OLLAMA_BASE_URL_IN_DOCKER`, default `http://host.docker.internal:11434` |
| `AI_TIMEOUT_S` | 150 | One packet through the model |
| `CLAUDE_MODEL` / `ANTHROPIC_API_KEY` | `claude-sonnet-5-5` / empty | The Claude adapter. See "Not tested" |
| `MIC_SILENCE_DB`, `MIC_SERVER_MIN_SILENCE_SECONDS` | -65, 60 | The server's scan of saved audio for muted stretches |
| `TRUST_FORWARDED_FOR` | false (true in Compose) | Read the caller's address from nginx's `X-Forwarded-For`. Only safe when the API is reached through nginx |
| `START_MAX_FAILURES`, `START_WINDOW_S`, `LOGIN_MAX_FAILURES`, `LOGIN_WINDOW_S`, `STAFF_TOKEN_TTL_S` | 20 / 300 s, 10 / 60 s, 8 h | Wrong-code and wrong-password limits, and how long a staff token lasts |
| `CHUNK_FAIL_RATE` | 0 | Dev only: refuse some uploads on purpose. Ignored when `ENV=production` |

The frontend has two switches for testing, `VITE_MIC_CHECK=off` and `VITE_FULLSCREEN=off`, set in
`frontend/.env.development.local`. They only affect `npm run dev`. The Compose build has neither.

## Decisions to know about

| Decision | Detail |
|---|---|
| "Flagged" means a rule score of 1.0 or more, or a gap in the record | `flagged_score` in `backend/app/services/flags/config.py`. A lone focus loss (0.5) does not enter the queue. Not yet confirmed with Cytonn |
| Every flag threshold is in one file | `flags/config.py`, explained in the comments beside each value. They were set on a made-up honest cohort, never on cheaters alone. Changing one and running `compute_flags` again replaces the earlier rule flags |
| Score, pace, reloads, drops, self-report and muted microphone stretches are context, never flags | They show beside the flags and add no points |
| The AI ranks and explains. It gives no verdict, sets no threshold, removes no one | Every queued candidate reaches a reviewer. Its answer is fact-checked against the packet, retried once, and replaced by the rule order if it still fails. Default model `gemma4:e2b`, chosen by [measurement](spikes/ollama-benchmark.md) |
| Leaving full screen is logged and shown, never flagged | A page cannot stop it, and honest candidates leave by accident |
| Only the camera and microphone gate the start | The notification confirmation and the full-screen result are stored and shown to the reviewer |
| The 30 days run from the latest decision | A newer decision supersedes an older one. A recording with **no** decision is never deleted automatically; it is listed after 60 days for a person to decide |
| Video is visible only for queued or shortlisted candidates | Others get 403. Deleted video gives 410. Reviewer video links are signed, last 4 hours, and stop when the reviewer's account is switched off |
| Every decision needs a written reason | 20 to 2000 characters. Outcomes are `no_concern`, `concern_noted`, `refer_for_follow_up`, **placeholders** until Cytonn names its own |
| Candidate ID only, no names | Copy and cut keep the length, never the text. The self-report note is shown to reviewers and never goes into a packet or to the AI |
| All time goes through an injected clock | `backend/app/clock.py`, never `datetime.now()`, so timers, heartbeat gaps and the 30-day deletion are testable |
| Papers are a random sample, balanced by section | `select_questions` in `test_flow.py`. The paper is built per candidate from a seed, and the answer options are shuffled |
| One question at a time | The question route returns the current question and its options, with no correct answer. Browser developer tools are still available to a candidate |

## Known limits

From the proposal:

- A candidate photographing the screen with a phone, using a second monitor, another application or a screenshot. A web page cannot stop any of these.
- A second device or person kept out of frame, or help through a hidden earpiece.
- A microphone muted in a way the three checks do not catch, and steady low-level cheating that avoids timing outliers.
- Questions memorised and shared after the test.
- Notifications and pop-ups that take focus make an honest candidate look as if they left the page. Candidates are told to turn them off and confirm; the reviewer sees focus loss as evidence, not a verdict.

Found while building:

- **A reload or closed tab loses the last few seconds of video**, about 5 seconds in the test run. A flag in that window shows "no video at that moment" in the reviewer app.
- **A reload leaves full screen**, and a page may only re-enter it on a click, so the question stays covered until the candidate presses a button. The clock keeps running.
- **Without IndexedDB** (a private window, site data blocked) the test runs and uploads while the page lives, but nothing survives a reload and the resume page has nothing to send.
- **Nothing deletes a recording that has no decision.** See the decisions above.
- **The focus-loss cap.** The code always caps focus-loss points at 2.0; the master plan says "unless there are 3 or more losses". Decide which is intended.
- **What the page can and cannot see is not fully measured.** The D2 browser checklist ([spikes/browser-findings.md](spikes/browser-findings.md)) is still blank, and the real-browser run ([eval/reports/scripted-run-browser.md](../eval/reports/scripted-run-browser.md)) is a template. Print Screen, some operating-system shortcuts and a second device are expected to be invisible to a page.

## Not tested

- **Edge, a Mac, a physically muted microphone and a real poor connection.** The whole candidate journey has run in Chromium with a fake camera and a generated tone, against the real server, with the strict gate on and with uploads failing on purpose. Only Windows with Chrome and Edge is in scope; nothing was run on a Mac.
- **The Claude adapter against the live API.** No key was available. It is tested with a stand-in client and, through the real SDK, with the network mocked. That shows the shape of the call and how failures come back, not that a key, the model or the schema are accepted. Cost estimate: [plan/claude-api-cost-estimate.md](plan/claude-api-cost-estimate.md).
- **HTTPS hosting.** nginx serves the app and proxies `/api`, but terminates no TLS. Cytonn's HTTPS goes in front of the `web` container, with `Strict-Transport-Security` added there. The camera does not work without HTTPS anywhere except `localhost`.
- **Scale beyond a pilot.** Nothing larger than about 16 people has been planned for, and nothing was load tested.
- **Tests that need ffmpeg or the `anthropic` package are skipped on a machine without them.** This laptop has neither on its Python path, so the 10 skipped tests in the backend suite are the video pipeline tests and the real-SDK Claude tests. The API image has ffmpeg, so the video steps do run there, but those tests have not been run against it.
- **The microphone thresholds** (`MIC_FLAT_PEAK` 0.0005 and 60 seconds in the browser, -65 dB on the server) were set from the plan, not tuned against a real quiet room and a muted microphone.

Not built, by decision: the blueprint paper generator (it was a stretch item in the proposal, and
it was removed from the plan on 21 October 2026, so its success criterion does not apply), and the
items the proposal lists as not part of this layer.

## Real data

Everything made up is labelled and removable: 60 placeholder questions (`Q001` to `Q060`),
per-question statistics marked `synthetic`, a simulated sitting (`sim-001` to `sim-016`) and the
invited test candidates (`cand-001` to `cand-020`). Load the real question bank first (`fetch_cytonn_bank`, see the README). The question-bank export's columns
(`BANK_COLUMNS` in `backend/app/services/question_import.py`) and the rule that gives a question
a difficulty from its success rate are this project's guesses, to confirm against Cytonn's files.
No flag rule uses past candidates' statistics (the history rule was removed on 23 Oct 2026), so
importing real statistics changes nothing in the flags.

## Hosting checklist

- [ ] A server with Docker, and Ollama on the same machine (or `OLLAMA_BASE_URL` pointing at it).
- [ ] A domain and HTTPS in front of the `web` container.
- [ ] `ENV=production`, `PRECHECK_GATE=recording`, a real `SESSION_SECRET`, `AI_PROVIDER=ollama`.
- [ ] The `pgdata` and `videodata` volumes backed up.
- [ ] A first admin account (`create_reviewer`), then the others from the command line.
- [ ] The worker running. It deletes video 30 days after a decision and notes uploads that never finished. Stop it while working with the simulated cohort, because that cohort has no video and the worker marks every one of its sessions as an incomplete upload.
- [ ] The made-up data removed once Cytonn's data is in.
- [ ] `frontend/public/spike/` deleted, after the D2 checklist has been filled in using it.

## Open sign-offs from Cytonn

These do not block the volunteer pilot. They block production.

- Data protection impact assessment, and the consent wording.
- Storage location and the retention period, including what deletes the video of candidates who are never reviewed.
- The complaints process: who reads them, how fast, and what a complaint can change.
- The reviewers' decision outcomes, and how a decision reaches the recruitment team.
- A route for candidates who cannot use a webcam or a desktop browser.
- The approved candidate-facing wording: [candidate notice](candidate-notice.md), the integrity statement, the self-report question and the microphone notice.
- The definition of "flagged" (a rule score of 1.0 or more), and whether the muted-microphone handling is accepted.
- Who owns the open items after handover.

## The pilot **[after the pilot]**

Results: [eval/reports/pilot-report.md](../eval/reports/pilot-report.md). How it was run:
[eval/pilot/runbook.md](../eval/pilot/runbook.md). Last measured before it, on 19 October 2026: with
the default thresholds, 16.5% of 400 simulated honest candidates were queued by a rule other than a
lone focus loss, against a target of at most 1 in 10. The thresholds have not been changed. Proposed
changes from the pilot belong in the report, not in the code.
