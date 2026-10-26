# aptitude-integrity-layer

A layer around Cytonn's aptitude test: the test runs in a normal browser (Chrome or Edge), full
screen, after the candidate has been asked for camera, microphone and full-screen permission and
told to turn off notifications. Camera and microphone are recorded, actions are logged, rules raise
flags and a person reviews them. It gives reviewers evidence and
never decides anything about a candidate. See [docs/proposal.md](docs/proposal.md) and the
[master plan](docs/plan/00-master-plan.md).

## Run it locally (Windows, PowerShell)

Needs Docker Desktop running, Python 3.13 and Node 20+. Copy `.env.example` to `.env` first.

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

Open `http://localhost:5173/candidate?t=<token>` in Chrome or Edge with a token from
`data/invites.csv`. The first screens ask for the camera, the microphone and full screen.

### A sitting, its invitations, and where its questions come from

On the admin page (`/admin`) a new sitting takes its questions from one of three places, with its
own count per section and its own time:

- **Cytonn's questions**: the seven sections of Cytonn's bank. Load them once (they carry pictures,
  which are copied into our database, so the test never depends on Cytonn's website):
  `python -m scripts.jobs fetch_cytonn_bank` (needs `X-API-KEY` in `.env`), or from a saved copy
  `... fetch_cytonn_bank --file ..\data\aptitude-sections-raw.json`.
- **Written by AI for each candidate**: needs Ollama running (or Claude; see `.env.example`). Try a
  small paper first, the local model writes about a question a minute. "Try the writer" shows one.
- **Practice questions**: the made-up bank, for trying things out.

Every invitation code is made *for one sitting* and opens that sitting's paper, whichever other
sittings are open: Invitations page (pick the sitting, download the CSV), or
`python -m scripts.jobs create_invites --sitting "<name or id>" --count 20`, which writes
`data\invites-sitting-<id>.csv` with the links.

### The whole thing in containers (what the pilot runs)

```powershell
docker compose up -d --build                # db, api, worker and web (nginx)
```

Open `http://localhost:8080`. nginx serves the built app and proxies `/api` to the API, so there is
one address for the page and the server, as the camera needs once it is on HTTPS. This is a
production build: no `VITE_*` switches from `.env.development*`. The API is also
on `127.0.0.1:8000` for this machine only. Stop the local `uvicorn` first; they share that port.

The `worker` runs the hourly housekeeping (delete video 30 days after a decision, note uploads that
never finished). Against the made-up cohort it marks every session as an incomplete upload, because
those sessions have no video: `docker compose stop worker` while working with simulated data.

On Docker Desktop for Windows every browser appears to the API as one address (the Docker
gateway), so the limit of 20 wrong invitation codes per five minutes is shared between them. On a
Linux host the real addresses come through.

### On a server (HTTPS)

`docker-compose.prod.yml` adds a Caddy proxy that gets the HTTPS certificate, closes every port but
80 and 443, and sets `ENV=production` (the API then refuses to start with a weak secret, an `http://`
address or the camera gate off). Fill in `.env` from `.env.example`, then
`docker compose -f docker-compose.prod.yml up -d --build`. The full steps are in
`docs/plan/hosting-cytonn-server.md`, and moving the AI from a local model to Claude is in
`docs/plan/ai-provider-switch.md` (both local; `docs/` is not committed).

#### Backups, restoring, and knowing when it is down

- **Back up** with `sh deploy/backup.sh` (cron: `0 2 * * * cd /srv/aptitude && sh deploy/backup.sh`). It
  writes a dated database dump and a recordings archive into `./backups` (git-ignored: the dump holds
  candidate names and addresses), checks both, keeps the last 14, and stops with an error rather than
  leave an empty file. Copy `./backups` off the machine as well; that part is not automated, because
  where the copies go is Cytonn's choice.
- **Restore** with `sh deploy/restore.sh backups/db-<stamp>.sql.gz backups/video-<stamp>.tar.gz` into a
  database that is empty (a new server: `up -d db` first, the rest after). It refuses a database that
  already has tables; the top of the script says how to replace a live one. Rehearsed on 26 Oct 2026
  against a throwaway copy of the production stack: back up, delete every container and volume,
  restore, start the API. All 23 tables had the same row counts, and a recording came back byte for byte.
- **Watch it.** Point a free uptime monitor (for example UptimeRobot) at `https://<host>/api/health` and
  have it look for the text `"status":"ok"`. A stopped API or database fails the request. Under 10 GB
  free where recordings are kept, the reply changes to `"status":"low_disk"` (still a 200, so Docker does
  not restart the API), and the staff Overview page shows a warning under "System checks".

#### After a sitting closes

Closing works out the flags and the pass-mark emails. The reviewers' queue then has the rule order only
until someone presses **Prepare for review** on the sitting's page (admin), which joins the recordings,
scans the audio, builds the evidence packets and ranks the flagged candidates with the provider in
`AI_PROVIDER`. It is not automatic on purpose: recordings go on arriving for up to 48 hours after the
test, and the run should come after they have. It is safe to run again. The same run from a terminal:
`python -m scripts.jobs process_sitting --sitting <id or name>`.

#### Checks on every push

`.github/workflows/checks.yml` runs ruff, the backend tests (Postgres, ffmpeg and the pinned packages,
nothing skipped) and the frontend lint, tests, type-check and build, on every push to `main` and every
pull request. The browser journeys (Playwright) need a running stack and stay manual.

### Invitations and emails

On a sitting, the admin pastes `name, email` lines (or chooses a file in any common format: PDF, Word,
Excel, PowerPoint, OpenDocument, RTF, HTML or plain text; the server reads the words out of it); each person
gets one code and is emailed their link. Sending uses one mail connection for the whole batch. The first time, the candidate types the code and their email and then chooses
a password (8 or more characters, kept only as a bcrypt hash); after that, email and password are
enough and the code is not needed. A forgotten password is fixed by the admin's **Resend link**, which
clears it and sends a new link. A second device cannot take over a test that is running unless the
first has been silent for a minute. Nothing is sent until mail is set up in `.env` (`SMTP_*`,
guide in `docs/plan/email-setup.md`); until then emails wait in a queue. Names and emails never reach
the AI or the review screens.

**Automated runs must never send real mail.** The API reads `.env`, so a scratch API started for the
browser tests would send invitations through your real mail account. Start it with a mail server that
is not there: `SMTP_HOST=127.0.0.1 SMTP_PORT=1 SMTP_USER=x SMTP_PASSWORD=x MAIL_FROM=a@b.invalid`
(an *empty* value does not work on Windows: an empty environment variable is deleted, not set).

### Results, the pass mark and the outcomes list

A person decides every result and the system sends the email. On a candidate's page a reviewer or an admin
picks pass or fail (a fail is given a short reason: one of three fixed ones or one typed line) and presses
**Send result email**. A flagged candidate cannot be sent a result until a decision is recorded. The
**Outcomes** page (both roles) lists everyone by where they stand: not started, sitting now, waiting for
review, reviewed, ready for a result, passed, below the pass mark, failed after review, under appeal, did not
finish; it filters, searches and pages, and several candidates who can be passed are passed at once from it.
Reviewers see candidate IDs only; the admin's copy adds names and a masked address and can be downloaded as CSV.

The admin can set a **pass mark** on a sitting (correct answers needed; empty switches it off). Changing it
is previewed first. When the sitting is closed, anyone who finished below it is sent a short email with
their score and the mark, and nobody else is touched; flags are never part of that. A candidate turned down
after a review is told the reason and how to appeal: `APPEAL_EMAIL` in `.env`, or `MAIL_FROM` if it is empty.

### How a test is timed

Every question gets 1.75 minutes (105 s). A sitting's time is its question count times that, and
a question that is not answered in time is closed by the server (it counts as skipped) and the next
one opens. A screenshot key press (PrintScreen, Win+Shift+S, Cmd+Shift+3/4/5) is logged as the key
combination only and flagged at 2 points; a browser cannot see the screenshot itself. When the page has
just recorded something that can raise a flag (leaving the page, copying, a screenshot key) the candidate sees
a short notice that a reviewer will see it and nothing has been decided. A reviewer sees each question's time
beside what the rest of the sitting took.

Switches for testing (put them in `frontend/.env.development.local`, which git ignores; every one is
on unless set to `off`, and all must be on for the pilot): `VITE_MIC_CHECK=off` leaves out the
microphone level check, `VITE_FULLSCREEN=off` leaves out the full-screen step (for automated browser
runs). `API_URL=http://localhost:8001 npm run dev` points the proxy at another API.

## Tests

```powershell
cd backend;  .\.venv\Scripts\python.exe -m pytest -q     # uses the integrity_test database
cd frontend; npm test; npm run lint; npm run build   # Vitest, oxlint, type-check and build
```

Without `claude` in the install, the 7 tests for the Claude client are skipped; without ffmpeg (set
`FFMPEG_BIN` in `.env`, or put it on PATH) the 9 video tests are skipped. A run that skips them is not
a full run.

### Pinned versions

`backend/constraints.txt` holds the exact version of every Python package the tests were run against, and
the Docker image installs with it, so a rebuild cannot pick up a newer release. The frontend does the same
through `package-lock.json`. To upgrade on purpose: make a fresh Python 3.13 venv, run
`pip install -e ".[dev,claude]"` (no `-c`), run the whole suite, then regenerate the file with
`pip freeze --exclude-editable`, keeping its header and adding `uvloop` (a Linux-only extra of
`uvicorn[standard]`; check the Linux set with `pip install -c constraints.txt ".[dev,claude]"` in a
`python:3.13-slim` container).

One whole candidate journey in a real browser (Chromium with a fake camera and a generated tone), against a
running stack: invitation, permissions, the recording, a reload, a spell offline, the finish and the
upload to the last chunk. It uses up the invitation and leaves a recording behind, so point it at a
scratch database, and start the API with `PRECHECK_GATE=recording` (what production requires):

```powershell
cd frontend
$env:E2E_BASE_URL = "http://localhost:8080"   # where the app is served (the default)
$env:E2E_TOKEN    = "<an unused invitation code>"
npm run e2e
```

`e2e/sittings.spec.ts` does the other half in a real browser: an admin makes a sitting (Cytonn's,
practice, and with `E2E_AI=1` an AI one) and a code for it on the real screens, and a candidate who
opens that code sits exactly that sitting, with its sections, its number of questions, its pictures
and its time. It needs an admin account and Cytonn's questions loaded:

```powershell
$env:E2E_ADMIN_EMAIL = "you@cytonn.com"; $env:E2E_ADMIN_PASSWORD = "<its password>"
npm run e2e -- sittings
```

`e2e/sitting-page.spec.ts` checks a sitting's own page the same way: the admin clicks a sitting in the
list, sees who has opened their link and who has not, filters by it, deletes the sitting by typing its
name, and the codes made for it stop working. Same two settings; run it with `npm run e2e -- sitting-page`.

`e2e/results.spec.ts` covers the staff side of results in a real browser: the outcomes list, passing
several people at once, failing one after a review, the pass mark on a closed sitting, the CSV download, and
uploading a list as a PDF, RTF or HTML file. It needs the made-up cohort with addresses that cannot receive
mail (`python -m scripts.jobs simulate_cohort --with-emails`), the same two admin settings, and works once per
cohort. Start the API with `SMTP_HOST=127.0.0.1 SMTP_PORT=1 ...` as above so nothing can be sent.

## Layout

`backend/` FastAPI app, migrations, seed and jobs · `frontend/` Vue 3 app and the D2 browser
capture spike page (`public/spike/`, open `/spike/index.html` in dev) · `docs/` proposal, plan,
spike findings.
