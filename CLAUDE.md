# CLAUDE.md

Guidance for Claude Code, and for any engineer picking this repo up.

## What this is

A layer around Cytonn's aptitude test: Safe Exam Browser lock-in, camera and microphone
recording, action logging, rule-based flags and human review. It gives reviewers evidence and
never decides anything about a candidate. Start with [docs/proposal.md](docs/proposal.md), the
[master plan](docs/plan/00-master-plan.md) and the weekly files in `docs/plan/`.

## Run and test (Windows, PowerShell)

Docker Desktop must be running. Use Python 3.13 via `py -3.13`; this laptop's default `python` is
3.14, which we avoid. Call the venv's Python directly (`.\.venv\Scripts\python.exe`), not
`Activate.ps1`. Copy `.env.example` to `.env` first.

```powershell
docker compose up -d db                     # Postgres on host port 5433

cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m scripts.jobs seed_synthetic --seed 42   # writes ..\data\invites.csv
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
```

## Working method

- One branch per task, named `<type>/<short-task>` (`feat`, `fix`, `chore`, `docs`, `test`,
  `spike`). Merge into `main` with `git merge --no-ff` once the task's tests pass.
- Claude must ask, and show the branch name and the commit message, before running any commit
  or the merge into `main`.
- No `Co-Authored-By` or other attribution lines in commits or PR descriptions.
- Commit only when tests are green. More detail in master plan section 5.

## Hard rules

- No candidate names in packets: the candidate ID only.
- Copy and cut events store the length only, never the text.
- The AI never gives a verdict. It ranks and explains; it sets no threshold and sets no one aside.
- Time always goes through the injected clock (`backend/app/clock.py`), never `datetime.now()`.

The full list is in master plan section 1.

## Where things live

- `backend/`: FastAPI app (`app/`), Alembic migrations, scripts (seed and jobs) and tests.
- `frontend/`: React and Vite app. `public/spike/` is the plain-JavaScript SEB spike page.
- `docs/`: proposal, plan (`plan/`) and spike findings (`spikes/`).
- `docker/`: init SQL for the Compose Postgres. `docker-compose.yml` at the root runs the database.
- `seb/`: how to build the SEB config and how request keys are verified. The `.seb` files are
  git-ignored.
- `data/`: runtime files (invite tokens, spike log, server logs). Git-ignored, never commit.
- `.claude/`: local Claude Code settings. Git-ignored.

## Style

- Font for documents: **Sora**. Use it for documents people read, such as reports, PDFs and
  slides. It does not apply to anything people interact with, such as the web app.
