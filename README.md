# aptitude-integrity-layer

A layer around Cytonn's aptitude test: Safe Exam Browser lock-in, camera and microphone
recording, action logging, rule-based flags and human review. It gives reviewers evidence and
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
                                            # reviewer, admin, pre-check, upload and complaint
                                            # screens run on fixtures (frontend/.env.development)
```

Open `http://localhost:5173/?t=<token>` with a token from `data/invites.csv`.

## Tests

```powershell
cd backend;  .\.venv\Scripts\python.exe -m pytest -q     # uses the integrity_test database
cd frontend; npm test
```

## Layout

`backend/` FastAPI app, migrations, seed and jobs · `frontend/` React app and the D2 SEB spike
page (`public/spike/`) · `seb/` SEB setup notes · `docs/` proposal, plan, spike findings.
