# Entry page, staff sign-in and navigation

> **Status (14 Oct 2026):** decisions below are settled with the user. Backend (migration `0002`,
> login, `me`, role dependencies, jobs) and the frontend routing step (entry page, sign-in pages,
> layout, breadcrumbs, route-specific fixtures) are built. Still to do: the candidate dead ends,
> the admin setup strip and the visual pass.
>
> Deviations from the plan as written: breadcrumbs live in `staff/crumbs.ts` (a component file may
> not also export functions); `staffPathForError` became `staffRecovery`, which says what to do
> instead of returning a path, because the right sign-in page now depends on where the person was;
> the fixture router accepts a real server token by matching it to the stored session; a reviewer
> who uses the admin sign-in is told so and nothing is stored.
> Builds on the screens in [ui-screens-and-invite-codes.md](ui-screens-and-invite-codes.md) and
> brings the reviewer login (week-03 D13 step 1) forward, with an `admin` role added.

## Context

The pages work one at a time but do not connect. `/` is the candidate code page and nothing
leads from it to staff; staff have to know `/review/login`. Reviewers and admins share one form,
the header title is not a link, sign-out always lands on the reviewer login, and the dead ends
(`/not-seb`, errors) give the candidate no next step. The staff login is also still a mock: the
backend has no staff accounts, no login endpoint and no `require_*` dependency.

## Decisions (settled)

1. **Entry page.** `/` is a chooser for everyone. The page does no SEB detection (no user-agent
   or version check); the server's config-key check stays the only gate. The SEB config's start
   URL becomes `<site>/candidate`, so candidates in SEB land straight on code entry. The config
   is still being built, so no key has to be re-issued.
2. **Separate cards.** Candidate, Reviewer and Admin each have their own card and sign-in page.
3. **Real login now.** Staff accounts, login endpoint, token checks and the admin dependency are
   built in this task, not left for D13.
4. **Navigation set (my pick, as asked):** brand link and a home that depends on role, breadcrumbs
   and back links on staff pages, a setup-steps strip on the admin Sittings page, and next steps on
   the candidate dead ends. Mid-test stays one-way for candidates. No separate admin dashboard
   page: the Sittings page already carries the counts.
5. **Look and feel.** Apply the Emil Kowalski skills (installed in `.agents/skills`, linked from
   `.claude/skills`; mainly `emil-design-eng`). CSS only, no animation library, so the
   candidate's download stays small. Sora is for documents and does not apply to the app.

## Routes

| Route | Who | What |
|---|---|---|
| `/` | all | Chooser with three cards. `/?t=...` forwards to `/candidate?t=...` so old links work |
| `/candidate` | candidate | Code entry (what `/` is today); `?t=` still auto-starts. The SEB start URL |
| `/login/reviewer` | reviewer, admin | Reviewer sign-in; lands on `/review` |
| `/login/admin` | admin | Admin sign-in; lands on `/admin`; a reviewer account is refused with a clear message |
| `/review/login` | | Redirects to `/login/reviewer`, keeping `?next=` |
| `/review/*`, `/admin/*` | staff | As today; signed-out visitors go to the matching login with `?next=` |

An admin account may sign in on the Reviewer card (it can see the review pages anyway); a
reviewer account on the Admin card is told to use the Reviewer sign-in.

**No SEB detection in the page.** An earlier idea (skip the chooser when the user agent says SEB)
is dropped: the SEB version is not factored in, and the config key already decides who may start
a test. A candidate who reaches `/` anyway just presses Candidate. `seb/README.md` ("start URL
set to the site root") changes to `/candidate` with the frontend step below.

## Frontend work

- `frontend/src/entry/Entry.tsx`: chooser with three cards, plus the `?t=` forward. Small and in
  the main chunk, so keep it dependency-free.
- Split `reviewer/Login.tsx` into a shared `staff/SignIn.tsx` that takes the area (`reviewer` or
  `admin`); `safeNext` stays, and now allows `/review` and `/admin` only.
- `StaffLayout`: brand is a `Link` to the role's home; `Sign out` goes to `/`; admin sees the
  area switch it has today.
- `staff/Breadcrumbs.tsx`: Review > Candidate C-0042, Admin > Invites, and so on, driven from the
  route; the candidate detail page keeps its "Back to the queue".
- Admin Sittings: a setup strip (1 Questions, 2 Sitting, 3 Invites, 4 Close) with links, built
  from data the page already has.
- Candidate dead ends: `/not-seb` says how to open the exam file and how to get help; expired
  or unknown code, and "not open right now", say what to do next.
- Visual pass with the Emil Kowalski guidance: transitions on named properties only, a strong
  ease-out curve, a pressed state on buttons, `prefers-reduced-motion` respected, visible focus,
  no animation on repeated actions (queue navigation, form submit).

## Backend work

- **Migration `0002_staff_and_audit`:** `reviewers` (`id`, `email` unique and stored lower-case,
  `password_hash`, `role` `reviewer|admin`, `is_active`, `created_at`) and `audit_log`
  (`id`, `reviewer_id` nullable, `action`, `session_id` nullable, `ts`, `detail`), with an index
  on `audit_log(ts)`, the lookup the audit view will use. `decisions` stays on D13.
- **Passwords:** `bcrypt` (already a dependency). A login for an unknown email still runs one
  bcrypt check against a dummy hash, so response time does not reveal which emails exist.
- **Token:** `itsdangerous` signed token (`sub` = reviewer id, `role`), 8 hours, as the master
  plan says. itsdangerous reads `time.time()`, so a `TimestampSigner` subclass takes its time
  from the injected clock (`app/clock.py`); a test with the fake clock proves expiry. The
  reviewer row is re-read on each request (one primary-key lookup), so a deactivated account
  stops working at once. Sign-out is client-side; the token is not revoked server side and
  simply expires. That is the trade-off for no extra table.
- **Endpoints:** `POST /api/review/login` (`{email, password}` to `{token, email, role}`) and
  `GET /api/review/me` (`{email, role}`), the first real route behind the new dependencies.
  Errors use the codes the frontend already reads: `invalid_credentials` 401, `unauthorized` 401,
  `forbidden` 403, `too_many_attempts` 429.
- **Dependencies:** `require_reviewer` (any active staff, admins included) and `require_admin`
  in `app/api/deps.py`.
- **Rate limit:** reuse `AttemptLimiter` (failures only), keyed by client address and by email;
  `login_max_failures` 10 and `login_window_s` 60 in `Settings`: a wrong password costs a reviewer at most a minute.
- **Audit:** a successful login writes an `audit_log` row (`action = login`).
- **CLI:** `python -m scripts.jobs create_reviewer --email ... [--password ...] [--role admin]`.
  Without `--password` it prompts, so the password stays out of shell history. Minimum 12
  characters. This is how the first admin is created.
- **Mock layer:** `MOCKED_PREFIXES` in `frontend/src/lib/api.ts` currently covers all of
  `/api/review`; it becomes route-specific so login and `me` hit the real server while the queue,
  detail and decisions stay mocked. The mock must accept a real token for those routes (check).

## Order of work

One branch, `feat/staff-login-and-nav`, one commit per step, each with green tests:

1. Backend: migration, models, security helpers, deps, login and me, create_reviewer, tests.
2. Frontend: routes, Entry, shared SignIn, layout, breadcrumbs, mock switch-over, tests; update
   the start URL in `seb/README.md`.
3. Candidate dead ends and the admin setup strip.
4. Visual pass; bundle-size comparison for the candidate chunk.

## Verification

- `pytest` (login ok, wrong password, unknown email, deactivated account, rate limit,
  expired token with the fake clock, tampered token, reviewer on an admin route is 403, audit
  row written, `create_reviewer` rejects a short password) and `ruff check`.
- `npm test` and `npm run lint` (chooser, SEB skip, `?t=` passthrough, role mismatch message,
  old `/review/login` redirect, sign-out destination, breadcrumbs).
- By hand with the real backend and the mock flag on: `/` shows three cards; `/?t=<code>` lands
  on `/candidate` and starts; SEB opened with start URL `/candidate` shows code entry; reviewer and
  admin sign in on their own cards; a signed-out visit to `/admin/invites` returns there after
  sign-in.
- Candidate bundle size before and after; any increase is reported with the reason.
- Migration applies cleanly on top of `0001` and downgrades.
