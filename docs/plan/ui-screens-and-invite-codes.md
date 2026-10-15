# Build every UI, and how invites reach candidates in SEB

> **Status (14 Oct 2026):** all screens in the inventory below are built and run on fixtures
> (`VITE_MOCK_API=1` in `frontend/.env.development`); the backend half of Option C (short codes,
> normalisation before hashing, wrong-code limit) is built and tested. Still to do on the server,
> per the days named in the table: the admin backend (week-03 D13 step 7), the reviewer endpoints
> (D13), pre-check (D6), upload manifest and complaints (D8). Each is switched on by removing its
> prefix from `MOCKED_PREFIXES` in `frontend/src/lib/api.ts`.
>
> Deviations from the plan as written: the upload manifest returns counts only (`expected`,
> `received`, `missing`, `bytes`, `complete`) instead of lists of sequence numbers, to keep the
> candidate's polling payload small; the sittings list carries its progress counts inline instead
> of a separate status endpoint; the microphone check counts one second of speech in total within
> ten seconds rather than one unbroken second, so a pause between words does not fail an honest
> candidate; the wrong-code limit counts failures only, so a venue of honest candidates behind
> one address cannot lock itself out.


## Context

You are finishing the SEB config and want all the project's screens built today, with a brief
explanation of how, plus a proper explanation of the invite options so you can choose. The
earlier workflow (questions import, sitting, jobs, review) is unchanged; this file covers the
UI work and the invite decision.

**State today:** the backend has only health, spike and session endpoints (`backend/app/api`:
`health.py`, `spike.py`, `session.py`). Events, flags, packets, ranking, chunks, precheck,
complaints and review endpoints do not exist yet (D5-D13). Candidate screens built:
Start, Integrity, TestRunner, Done (self-report is inside it), NotSeb. Nothing exists for
reviewers or recruiters.

**Consequence:** "all UI today" is realistic for plain-styled screens, but they will run on mock
data until the matching backend day lands. Screens built today are demonstrable, not yet
end-to-end functional. That is the honest scope.

## Part 1: Screen inventory

| # | Screen | Route | Status | Needs (not built yet) |
|---|---|---|---|---|
| 1 | Start (code entry) | `/` | built | |
| 2 | Integrity statement | `/integrity` | built | |
| 3 | Test runner | `/test` | built | MicBanner overlay needs `micWatch` |
| 4 | Done + self-report | `/done` | built | |
| 5 | Not in SEB | `/not-seb` | built | |
| 6 | **Pre-check** (camera, mic, level meter, device labels, blocks start until OK) | `/precheck` | to build | `POST /api/precheck/result` (D6) |
| 7 | **Mic banner** (non-blocking `role="status"` above the question) | component in `/test` | to build | `micWatch.ts` (D6) |
| 8 | **Upload status** ("keep SEB open until finished", then Quit URL) | `/uploading` | to build | chunk manifest (D8) |
| 9 | **Complaint form** (camera / upload / other, up to 1000 chars) | `/complaint` | to build | `POST /api/complaints` (D8) |
| 10 | Resume page | `/resume` | **conditional** | only if SEB spike check 4 passes (Plan B); skip until decided |
| 11 | **Reviewer login** | `/login/reviewer` and `/login/admin` (was `/review/login`, which still forwards) | built; real server login | see [staff-login-and-navigation.md](staff-login-and-navigation.md) |
| 12 | **Reviewer queue** (rank, candidate ID, flag chips, "AI advisory" badge or "rules only", decision status, sitting filter, low-rank logging-problem lane) | `/review` | to build | `GET /api/review/queue` |
| 13 | **Candidate detail** (packet summary, flags with times and question numbers, cohort comparison, score and pace labelled context only, innocent signals, mic-silence stretches, AI explanation labelled advisory, complaints, past decisions) | `/review/candidates/:id` | to build | `GET /api/review/candidates/{id}` |
| 14 | **Video player** (jump to flag − 5 s, handles no-video-at-moment, video deleted notice) | inside 13 | to build | Range video endpoint |
| 15 | **Decision form** (outcome, reason of at least 20 chars, confirm; shortlist toggle) | inside 13 | to build | `POST /api/review/decisions` |
| 16 | Audit view (decisions, video views, logins) | `/review/audit` | optional | audit endpoint |
| 17 | **Setup/admin: sittings** (list, create: name, window, duration, question count; close) | `/admin` | **new, not in plan** | admin endpoints and auth (today these are CLI jobs) |
| 18 | **Setup/admin: invites** (generate candidate IDs, download invite CSV) | `/admin/invites` | new, not in plan | same |
| 19 | **Setup/admin: question import** (upload CSV, show import report) | `/admin/questions` | new, not in plan | same |

Rows 17-19 are the "recruiter page". **They are required, not optional.** They are not in the
original 15-day plan, so they are added to it: UI today on mock data, and a small admin backend
(see "Admin backend" below) scheduled right after the reviewer login on D13, because both share
the same login and `require_*` dependency.

## How to build it today (brief)

1. **Foundation (small).** Add routes in `frontend/src/App.tsx`. Lazy-load `/review` and `/admin`
   so the candidate's bundle stays small (CLAUDE.md optimisation rule: candidates may be on a
   weak connection while recording). Reuse `frontend/src/lib/api.ts`, `index.css` and the
   `copy.ts` pattern for wording placeholders.
2. **Contract first.** Type the request and response shapes from master plan section 7.2 and
   the packet shape in 7.5, so every screen codes against the final API.
3. **Mock layer.** A switchable fixture mode (one env flag) that serves data shaped like
   `eval/fixtures/synthetic_packets.py`. Each screen is demonstrable now; flipping a screen to
   the real endpoint is a one-line change when its backend day lands.
4. **Order:** reviewer app (rows 11-15, the biggest) → admin screens (17-19) → remaining
   candidate screens (6-9). Admin comes before the small candidate screens because it is
   entirely new and the largest unknown; the candidate screens are small and well specified.
5. **Tests:** Vitest + Testing Library per screen for the logic that matters (decision needs a
   20-char reason, pre-check blocks start, no-video states). `npm test` and `npm run lint`.
6. **Working method:** one branch per task, for example `feat/ui-reviewer-app`,
   `feat/ui-candidate-screens`, `feat/ui-admin`; I show branch name and commit message and ask
   before any commit or merge.

Not UI, so not part of "today": `media.ts`, `recorder.ts`, `chunkQueue.ts`, `uploader.ts`,
`eventLogger.ts`, `heartbeat.ts` (D4, D6-D8). The screens above only show their state.

## Part 2: How the invite code reaches a candidate inside SEB

The constraint: a `.seb` file holds one start URL, and the invite token is per candidate.

### Option A: one shared `.seb`, candidate types a code (what the Start page does today)

- **How:** one `exam.seb` for everyone, start URL = the site root. Each candidate gets that file
  once (download link or attachment) and their personal code by email. They open the file, SEB
  loads Start, they enter the code.
- **For:** one Config Key and one Browser Exam Key, so `SEB_ALLOWED_KEYS` holds a single value
  and the server check is simple. Any edit to the file changes the key, so a tampered config is
  rejected. Build and test the config once. Re-issuing a lost code is just a new token.
  Already works in `Start.tsx`.
- **Against:** typing. Your config turns clipboard use off (seb/README step 4), so the
  candidate cannot paste and has to type the code. The seeded codes are 24 hex characters,
  which is error-prone to type by hand, so you would want shorter, human-friendly codes
  (for example 8 characters in an alphabet without 0/O or 1/l, grouped as XXXX-XXXX). Shorter
  codes mean less entropy, so add a rate limit on the start call.

### Option B: one `.seb` per candidate, token baked into the start URL

- **How:** a script writes one config per candidate with start URL `/?t=<token>`, and each
  person gets their own file (or a `sebs://` link that serves their config).
- **For:** no typing at all; one double-click starts the test with the token filled in.
- **Against:** N files to generate, send and track. The start URL is a setting inside the
  config, so each file very likely has its **own** Config Key and Browser Exam Key. The server
  would then need an allowed-key list per candidate, and you would have to obtain each key
  (open each file in the Config Tool, or implement SEB's key calculation). You also lose the
  clean "any edit changes the one known key" property. A forwarded file carries the token, the
  same risk as a forwarded link.
- **Quick check you can do right now in the Config Tool:** change only the start URL, save, and
  see whether the displayed Config Key changes. If it does, Option B means N keys.

### Option C (hybrid, my suggestion): shared `.seb` plus short typed codes

Option A's single key and single config, with codes short enough to type reliably on a
keyboard. The `?t=` link stays for testing in a normal browser. This changes only how invite
codes are generated (a later small change to the seed), not the SEB config you are building.

## Decisions (settled)

1. **Invites: Option C.** One shared `.seb`, short human-friendly typed codes.
2. **Admin/recruiter screens (rows 17-19): required**, part of the plan.
3. **Mock mode: approved.** Screens run on fixtures today; real wiring as each backend day lands.

### What Option C changes (small, all outside the SEB config)

- **Code format:** replace the 24-hex token with a short code (8 characters, no look-alike
  characters, shown as XXXX-XXXX). Change in `backend/scripts/seed_synthetic.py`
  (`_invite_token`) and the admin invite generator; the stored value stays a hash
  (`hash_token`), so the schema does not change. Update `test_seed.py`.
- **Start page:** `frontend/src/candidate/Start.tsx` accepts the code case-insensitively and
  ignores dashes and spaces, and maps look-alike characters, so a typing slip costs nothing.
- **Rate limit:** `POST /api/session/start` gets a per-IP and per-code attempt limit, because a
  short code has less entropy than 24 hex characters. It must be cheap (in-memory counter or
  one indexed lookup) so it does not slow the start path.
- **SEB config:** one `exam.seb`, start URL = site root. Nothing per candidate.

### Admin backend (needed by rows 17-19; built, see staff-login-and-navigation.md)

- **Auth:** reuse the reviewer login (D13). Add an `admin` role so reviewers cannot create
  sittings or invites; one `require_admin` dependency on `/api/admin/*`.
- **Endpoints**, thin wrappers over what the CLI jobs already do, so no logic is duplicated:
  `GET/POST /api/admin/sittings`, `POST /api/admin/sittings/{id}/close`,
  `POST /api/admin/invites` (generate IDs, return the CSV), `POST /api/admin/questions/import`
  (upload CSV, return the import report), `GET /api/admin/sittings/{id}/status`
  (finished, in progress, not started).
- **Keep the CLI.** The jobs stay runnable from the command line; the admin page calls the same
  service functions.
- **Safeguards:** admin actions go in the audit log; importing questions refuses to run if a
  sitting is open; invite CSV is generated on request and never stored on the server.

## Verification

- `npm test` and `npm run lint` pass after each branch.
- With the mock flag on, click through: candidate pre-check → upload status → complaint;
  reviewer login → queue → candidate → jump to flag → decision (blocked below 20 characters);
  admin: create sitting → import questions (report shown) → generate invites → close sitting.
- Start page: a code typed in lower case, with a dash or a space, still works.
- Admin backend (when built): non-admin token → 403; importing during an open sitting → refused;
  each admin action creates an `audit_log` row.
- Candidate bundle size before and after (the lazy-loaded `/review` and `/admin` should not
  add to it); report any increase and why.
- Real endpoints replace mocks screen by screen as D6, D8, D10-D13 land.
