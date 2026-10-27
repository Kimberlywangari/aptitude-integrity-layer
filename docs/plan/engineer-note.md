# A note for the engineer reading this repository

Written 24 Oct 2026 for Cytonn's senior software engineer. It says where things are, what must not be
broken, what was traded for what, what was measured, and what has **not** been run for real.

## What it is

A layer around Cytonn's aptitude test. Candidates take the test in Chrome or Edge, full screen, with
camera and microphone recording. The page logs actions, rules raise flags, and a person reviews them.
It gives reviewers evidence. It decides nothing about a candidate, with one narrow exception (below).

## Where things live

| Where | What |
|---|---|
| `backend/app/api/` | Thin FastAPI routes. `session.py` (the candidate), `events.py`, `chunks.py` (video upload), `review.py` (reviewers and admins), `admin.py` (admins only). |
| `backend/app/services/` | The logic. `test_flow.py` (timing, answers), `flags/` (pure rules in `rules.py`, storage in `engine.py`), `outcomes.py` (the one status function and every result action), `mail.py` + `results.py` (outbox and result emails), `documents.py` (reads uploaded files), `qgen/` (AI-written questions), `ranking/` (the AI ranker and its fact check), `video/`. |
| `backend/app/models/`, `backend/migrations/` | SQLAlchemy models; 14 Alembic migrations, tested from an empty database. |
| `backend/tests/` | 1,000+ tests: unit (pure rules, readers) and integration (the real API against a throwaway Postgres schema, each test in a rolled-back transaction). |
| `frontend/src/candidate/` | The candidate's screens, in the main bundle on purpose (a chunk fetched mid-test can fail on a weak connection). |
| `frontend/src/reviewer/`, `frontend/src/admin/` | Staff screens, lazy chunks. |
| `frontend/tests/mock/` | An in-memory stand-in for the server, for screen tests only. The app never imports it. |
| `frontend/e2e/` | Playwright: the whole candidate journey with a fake camera, and the staff side of results. |
| `deploy/`, `docker-compose.prod.yml` | HTTPS in front (Caddy), backups. |

## The rules that must not break (and what guards each)

1. **No candidate names outside the invitation and result emails and the admin's list.** Not in
   packets, model prompts, review screens, events, flags or audit text. `test_privacy_of_names.py`
   walks all of them with a name planted on every candidate. Reviewers get their own outcomes route
   (`/api/review/outcomes`) so a response can never carry a name by accident.
2. **The AI never decides.** It ranks and explains. It sets no threshold and sends no email. A fact
   check rejects any explanation that cites something not in the stored log.
3. **Copy and cut events keep the length only**, never the text (the payload allow-list in
   `services/events.py`).
4. **Time goes through an injected clock** (`app/clock.py`), so every time-dependent rule is tested with
   a fake one.
5. **The one automatic outcome that is new this week:** a score under a pass mark an admin chose is
   turned down, with a short email, **when the sitting is closed** (and when a closed sitting's mark is
   changed). The master plan lists automatic rejection as out of scope and says the camera gate is the
   only automatic thing; this was added deliberately at the project owner's request and is limited to
   the score: it never reads a flag, never touches anyone a person has decided or anyone already
   emailed, and the change is previewed before it is applied. Everything else (a pass, a fail after
   review) is a person pressing a button.
6. **An email cannot be taken back**, so every result email is one outbox row per candidate (a unique
   key), a resend needs a confirmation, and a flagged candidate cannot be sent a result until a person
   has recorded a decision.

## Trade-offs made, in plain words

- **Statuses are derived, not stored.** One function (`outcomes.status_of`) turns a candidate's data into
  where they stand; the list, its counts, the result panel and the emails all read it. Cost: the list
  works the whole sitting out in a fixed number of queries (not one per row), so it is linear in the
  sitting's size. Fine for hundreds, not load-tested for thousands.
- **Mail is a database queue**, sent by a background thread after the request and again by the worker, so
  a restart or a mail outage loses nothing. One SMTP connection serves a whole batch (measured below).
- **Document reading is the standard library plus one dependency (`pypdf`).** Content decides the kind,
  never the file name. No OCR, no legacy `.doc`/`.xls`/`.ppt`; those are refused with a reason.
- **The candidate bundle is small:** no UI library, no icon or web font. This week added 1.2 kB of
  JavaScript to it (117.9 to 119.1 kB, 42.3 kB gzipped).
- **Flag thresholds are tuned on simulated cohorts**, not real ones (there are none yet). Today's
  measurement is below. Treat the recall figure as flattering: the scripted cases are stark by
  construction.

## Numbers measured on 24 Oct 2026

| What | Result |
|---|---|
| Backend tests | see `readiness-check.md` (run from a clean copy) |
| Frontend unit tests | 46 files, 612 tests |
| Browser tests | candidate journey (1 min, real Chromium, fake camera); results spec; sitting-page spec |
| Honest candidates flagged beyond a lone focus loss | 15 of 440 (3.4%) over 40 simulated cohorts of 16 |
| Scripted cheating cases found | 100% of 200 (answer runner, copier, logging blocker, tab lookup) |
| Making 50 invitations | request 0.15 s; sending used 50 SMTP connections, now 1 |
| Candidate JavaScript | 119.1 kB (42.3 kB gzipped) |
| Migrations | 0001 to 0014 run cleanly on an empty database |

## Not run for real (do not assume these work)

- **Real SMTP.** Every test uses a fake mailer or a closed port. Sending through Cytonn's provider
  (STARTTLS, a real account, real delivery) has never been tried from this code since the connection
  reuse was added.
- **The Claude paths** (writing questions, ranking) are covered by tests with a stand-in client and have
  not run against the live API. The local-model (Ollama) paths ran on the development laptop only.
- **Document readers on real files.** The PDF, Word, Excel, PowerPoint and OpenDocument readers are
  tested on files built byte by byte in the tests, not on files saved by Word, Excel or Acrobat.
- **A real Edge, a Mac, a physically muted microphone, a genuinely bad network.** The browser test uses
  Chromium's fake devices.
- **The production stack** (`docker-compose.prod.yml` with HTTPS) has not been brought up on Cytonn's
  server. The backup and restore drill was run on a throwaway copy, unencrypted. The encrypted path
  was only drilled in pieces (`sh deploy/check.sh`), never on a whole stack.
- **The staff network lock** (`STAFF_ALLOWED_IPS`) was tested against the real pinned Caddy from this
  laptop (`sh deploy/check.sh`), not from Cytonn's network, and not behind any load balancer. Caddy sees
  the address that reached it; if Cytonn's server sits behind another proxy the rule needs `client_ip`
  with `trusted_proxies` or it will judge the proxy's address.
- **A pilot with people.** The pilot materials exist (`eval/pilot/`) and the report is blank.
- **Load.** No test with hundreds of candidates at once.
