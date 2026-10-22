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
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
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

- No candidate names in packets: the candidate ID only.
- Copy and cut events store the length only, never the text.
- The AI never gives a verdict. It ranks and explains; it sets no threshold and sets no one aside.
- Time always goes through the injected clock (`backend/app/clock.py`), never `datetime.now()`.

The full list is in master plan section 1.

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
