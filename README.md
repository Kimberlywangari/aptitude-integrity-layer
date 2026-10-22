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
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
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

Switches for testing (put them in `frontend/.env.development.local`, which git ignores; every one is
on unless set to `off`, and all must be on for the pilot): `VITE_MIC_CHECK=off` leaves out the
microphone level check, `VITE_FULLSCREEN=off` leaves out the full-screen step (for automated browser
runs). `API_URL=http://localhost:8001 npm run dev` points the proxy at another API.

## Tests

```powershell
cd backend;  .\.venv\Scripts\python.exe -m pytest -q     # uses the integrity_test database
cd frontend; npm test; npm run lint; npm run build   # Vitest, oxlint, type-check and build
```

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

## Layout

`backend/` FastAPI app, migrations, seed and jobs · `frontend/` Vue 3 app and the D2 browser
capture spike page (`public/spike/`, open `/spike/index.html` in dev) · `docs/` proposal, plan,
spike findings.
