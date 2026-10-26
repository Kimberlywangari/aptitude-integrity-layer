# CLAUDE.md

Guidance for Claude Code, and for any engineer picking this repo up.

## What this is

A layer around Cytonn's aptitude test: the test runs in a normal browser (Chrome or Edge), full
screen, after the candidate has been asked for camera, microphone and full-screen permission and
told to turn off notifications. Camera and microphone are recorded, actions are logged, rules raise
flags and a person reviews them. It gives reviewers evidence and
never decides anything about a candidate. Start with [docs/proposal.md](docs/proposal.md), the
[master plan](docs/plan/00-master-plan.md) and the weekly files in `docs/plan/`. The `docs/` folder
is kept locally and is git-ignored, so a fresh clone does not have it.

## Run and test (Windows, PowerShell)

Docker Desktop must be running. Use Python 3.13 via `py -3.13`; this laptop's default `python` is
3.14, which we avoid. Call the venv's Python directly (`.\.venv\Scripts\python.exe`), not
`Activate.ps1`. Copy `.env.example` to `.env` first.

```powershell
docker compose up -d db                     # Postgres on host port 5433

cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,claude]" -c constraints.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m scripts.jobs seed_synthetic --seed 42   # writes ..\data\invites.csv
.\.venv\Scripts\python.exe -m scripts.jobs create_reviewer --email you@cytonn.com --role admin   # asks for a password
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

cd ..\frontend                              # second terminal
npm install
npm run dev                                 # http://localhost:5173 (proxies /api to :8000)
```

Open `http://localhost:5173/?t=<token>` with a token from `data/invites.csv`.

```powershell
cd backend;  .\.venv\Scripts\python.exe -m pytest -q                  # uses the integrity_test database
cd backend;  .\.venv\Scripts\python.exe -m ruff check app scripts tests
cd frontend; npm test                                                 # Vitest
cd frontend; npm run lint                                             # oxlint
cd frontend; npm run e2e    # a real browser, whole journey; needs a stack, E2E_TOKEN (see README)
```

## Working method

- One branch per task, named `<type>/<short-task>` (`feat`, `fix`, `chore`, `docs`, `test`,
  `spike`). Merge into `main` with `git merge --no-ff` once the task's tests pass.
- Claude must ask, and show the branch name and the commit message, before running any commit
  or the merge into `main`.
- No `Co-Authored-By` or other attribution lines in commits or PR descriptions.
- Every plan goes in `docs/plan/`, never in a scratch or home-folder location. Name it for the
  task, for example `docs/plan/hosting-supabase-vercel.md`.
- Commit only when tests are green. More detail in master plan section 5.

## Hard rules

- No candidate names in packets: the candidate ID only. A candidate's name and email are stored for
  the invitation and result emails and the admin's list, and nowhere else may they appear: not in
  packets, model prompts, review screens, events, flags or audit text. `test_privacy_of_names.py`
  guards it; keep it passing and extend it when a new screen or prompt is added.
- Copy and cut events store the length only, never the text.
- The AI never gives a verdict. It ranks and explains; it sets no threshold and sets no one aside.
- Time always goes through the injected clock (`backend/app/clock.py`), never `datetime.now()`.

The full list is in master plan section 1.

## Results, the pass mark and the outcomes

- A person decides every result, and the system sends the email: `services/outcomes.py` holds the one
  status function (`status_of`) that the outcomes list, its counts, the result panel and the emails all
  read, and the routes that record a result (`/api/review/candidates/{id}/result`, both roles; the server
  checks the role). A flagged candidate has no result until a decision is recorded; once an email is
  queued or sent the result is final, and a resend needs the person to confirm.
- The pass mark (`sittings.pass_mark`, correct answers) is the only automatic outcome, and only for a low
  score: it runs when a sitting is closed and when a closed sitting's mark is changed (previewed first), and
  it never reads flags or touches anyone already emailed or decided by a person. A turned-down-after-review
  email carries a reason a person chose (never AI text, a rule name or a threshold) and the appeal address.
- The outcomes list has two routes so a reviewer's response can never carry a name: `/api/review/outcomes`
  (IDs only) and `/api/admin/outcomes` (names, masked addresses, CSV). `test_privacy_of_names.py` covers both.
- Uploads (invite list, question import) go through `POST /api/admin/extract-text`, which decides the file
  kind from its bytes. Only `pypdf` is a dependency of it; everything else is the standard library. Legacy
  `.doc`/`.xls`/`.ppt` and scanned PDFs are refused with a reason, never guessed at.

## After a sitting closes, and running it for real

- Closing works out flags and the pass-mark rule. Video joining, the audio scan, packets and the AI
  ranking are one run, `services/processing.py`, started by the admin's "Prepare for review" panel or
  `scripts.jobs process_sitting`. It is deliberately not triggered by closing: recordings keep arriving
  for up to 48 h (`RESUME_WINDOW_S`), and a run before that ranks partial video. Its progress is in
  memory (a restart forgets a run under way; repeating it is safe), and tests stub `processing.launch`
  in `conftest.py` and call `_work` inline.
- `/api/health` stays a 200 when the recordings disk is low (`status: "low_disk"`), because Docker's own
  health check reads the code. `services/disk.py` is the one threshold the health route and the staff
  overview share.
- `backend/constraints.txt` pins every Python package; the Docker image and CI install with it. Change it
  only on purpose, by the steps in the README ("Pinned versions").
- `deploy/backup.sh` and `deploy/restore.sh` are a pair, rehearsed together. `backups/` is git-ignored.

## Candidate sign-in

- A candidate with an email signs in with the code and email, then chooses a password at their first
  sign-in (`services/login.py`); after that, email and password. Candidates made without an email use
  the code alone. Passwords are bcrypt hashes (`core/passwords.py`), never logged, never in an error
  body, audit text, event or email: `test_candidate_passwords.py` asserts it.
- Every way of being wrong at sign-in returns the same `invalid_invitation` after the same bcrypt
  work. Keep it that way; do not add a message that says which part was wrong.
- A running test is not taken over from a second device unless its heartbeat has been silent for
  `TAKEOVER_QUIET_S` (60 s).
- Tests pin the mail settings to empty in `tests/conftest.py`, and a scratch API for browser tests must
  be started with `SMTP_HOST=127.0.0.1 SMTP_PORT=1` (see README): never let automated runs send mail.

## Test timing and flags

- Every question gets 105 s (`QUESTION_SECONDS` in `backend/app/services/test_flow.py`); a sitting's
  time is its question count times that, set by the server. Tests that move the fake clock past 105 s
  inside one question will see it close.
- The notice on the test screen ("recorded and a reviewer will see it") is driven by the server: the reply
  to `POST /api/events` carries `warn`, true for a fresh event whose type is in
  `flags/rules.py: WARN_EVENT_TYPES`, which the rules themselves read, so the notice and the rules cannot
  disagree. It names no rule and no number, fades only, never touches the question clock.
- `SCREENSHOT_KEY` (weight 2.0) comes from the `screenshot_attempt` event, which carries only a key
  combination from a fixed list. Do not describe it as detecting a screenshot: the page sees keys.
- Tests pin `precheck_gate`, `ai_provider` and `chunk_fail_rate` in `tests/conftest.py`, so a
  developer's own `.env` does not change them.

## Optimisation

Speed and efficiency matter in every part of this project, not only the parts that look slow.

- Think about speed, memory and storage while writing code, not afterwards. A slow query, an
  oversized payload or a wasteful loop is a bug.
- Keep what goes to the candidate's browser small. Candidates may be on a weak connection
  while the camera is recording.
- Keep database access lean: fetch only what is needed, and index the lookups we actually do.
- If a change makes something slower, say so and why, so we can discuss whether it is worth the
  tradeoff.

## Where things live

- `backend/`: FastAPI app (`app/`), Alembic migrations, scripts (seed and jobs) and tests.
- `frontend/`: Vue 3 and Vite app. The candidate screens are in the main bundle and the staff
  screens are lazy chunks. `public/spike/` is the plain-JavaScript browser capture spike page.
- `docs/`: proposal, plan (`plan/`, where every plan lives) and spike findings (`spikes/`).
  Git-ignored, kept locally, never commit.
- `docker/`: init SQL for the Compose Postgres. `docker-compose.yml` at the root runs the database.
- `data/`: runtime files (invite tokens, spike log, server logs). Git-ignored, never commit.
- `.claude/`: local Claude Code settings. Git-ignored.

## Frontend rules

- Every page has the light and dark toggle. It is mounted once in `src/App.vue`, outside the routes,
  and `tests/App.theme.test.ts` guards that. Colours come from the tokens in
  `src/styles/tokens.css` only; do not hard-code colours.
- Keep the candidate's download small: no UI library, icon font or web font. Staff, reviewer and
  admin code (and TanStack Vue Query) stay in lazy chunks. Check the size when adding a dependency.
- Motion: the test screen is used under a clock, so it only fades the question in (about 120 ms);
  staff screens change colour only; the entry, pre-check and finish screens may rise in. Only
  `transform`, `opacity` and colour are animated, hover is gated to a mouse, and reduced motion is
  respected.
- A candidate is asked for everything the exam needs in the pre-check (notification warning, camera
  and microphone, full screen). Do not add permissions the proposal does not mention, such as screen
  recording.

## Style

- Font for documents: **Sora**. Use it for documents people read, such as reports, PDFs and
  slides. It does not apply to anything people interact with, such as the web app.
