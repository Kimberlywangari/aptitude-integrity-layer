# Browser-only test, permissions, and the Vue frontend

> **Status (16 Oct 2026): built and verified.** Decided by the project owner. Covers three linked
> changes: the test runs in a normal browser (no locked-down browser), the candidate is asked for
> every permission the exam needs and told to turn off notifications, and the whole frontend is
> rebuilt in Vue 3 with a new look. The earlier "browser only" comparison note is folded into this
> file.
>
> Verified on 16 Oct: backend 238 tests, frontend 230 tests, lint and type-check clean; a full
> candidate journey in Chromium against the real API and a scratch database (invitation link,
> permissions, real full screen, 12 questions with one skipped, self-report, finish), with the
> server holding opened and answered times for every question; light and dark at desktop and phone
> width. A candidate downloads about 59 KB gzipped (React was about 86 KB). Not yet done by a
> person: the same journey in real Edge, on a Mac, and with a physically muted microphone.

## What changes

1. **Browser only.** Candidates open a personal link in desktop Chrome or Edge. Nothing to install.
   The server no longer checks where a request came from. Every document, setting, test and
   screen that depended on a locked-down browser is gone (proposal, master plan, weekly plans,
   backend module, settings, an unused `sessions` column, the spike page).
2. **Permissions and a notification warning.** The pre-check asks for everything the exam needs,
   one step at a time (see "Pre-check steps").
3. **Vue 3 frontend** with a redesigned, interactive UI. Same routes, same API, same wording rules.

## Decisions and defaults

| Topic | Decision | Why |
|---|---|---|
| Permissions asked | Camera and microphone (one prompt), full screen (a click) | These are what the proposal records and what the exam needs |
| Screen recording, second-monitor detection | **Not asked, not built** | Not in the proposal; it would collect more data than the proposal tells candidates. Ask Cytonn first if wanted |
| Notifications | A written warning plus a confirmation checkbox. The page does **not** ask for the browser's notification permission | A page cannot read the operating system's notification or Do Not Disturb settings; asking for the permission would be the opposite of the goal |
| Leaving full screen | Logged as context for the reviewer (`fullscreen_exited`, `fullscreen_entered`), never a flag | A page cannot stop it, and honest candidates leave by accident |
| Gate | Only the camera and microphone gate the start (the proposal's one automatic outcome). The notification confirmation and the full-screen result are stored in `precheck_report` for the reviewer | Keeps "only one thing is automatic" true |
| Device requirement | Windows or Mac laptop or desktop, current Chrome or Edge. Phones, tablets, Chromebooks and private windows are not supported | Recording and full screen are reliable there; only Windows is tested |
| Stack | Vue 3 (`<script setup>`), Vue Router, TypeScript, Vite, Vitest + Vue Test Utils. TanStack Vue Query in the staff chunk only | Small candidate bundle: staff code is a lazy chunk |
| Styling | Plain CSS with design tokens, light and dark. No UI library | Candidates may be on a weak connection while recording |
| Proposal PDF | `docs/proposal.pdf` is the old export and still describes the old design. Re-export it from `docs/proposal.md` | A PDF cannot be edited in place |

## Pre-check steps (candidate)

1. **Before you start**: what is recorded, the data use, the device requirement, the microphone notice.
2. **Turn off notifications**: how to (Windows Focus Assist or Do Not Disturb, macOS Focus, close
   chat and email, pause notifications from other sites) and a checkbox. Stored as
   `notifications_off_confirmed`.
3. **Allow camera and microphone**: one button, one prompt, with the four states (not asked,
   waiting, allowed, blocked) and plain steps to unblock.
4. **Camera check**: live picture.
5. **Microphone check**: level meter and "say your name" (switchable off while testing with
   `VITE_MIC_CHECK=off`, which must be removed before the pilot).
6. **Full screen**: one click; the step passes once the browser reports full screen.
7. **Continue** only when every step has passed.

In the test: leaving full screen covers the question with a "Return to full screen" panel. The
server clock keeps running and the panel says so.

## Frontend structure

```
frontend/
  src/
    main.ts  router.ts  App.vue
    lib/        api.ts routes.ts session.ts staffSession.ts theme.ts features.ts wait.ts
                devices.ts micCheck.ts micStatus.ts fullscreen.ts permissions.ts browser.ts
                format.ts inviteCode.ts csv.ts reviewTypes.ts adminTypes.ts mock/
    components/ ThemeToggle.vue BaseButton.vue Banner.vue Icon.vue (+ icons.ts) BrandMark.vue
                LevelMeter.vue ProgressBar.vue SuccessMark.vue
    composables/ useFullscreen.ts useMicSilent.ts
    candidate/  Start.vue PreCheck.vue StepCard.vue Integrity.vue TestRunner.vue Done.vue
                UploadStatus.vue Complaint.vue MicBanner.vue FullscreenGate.vue copy.ts
    entry/      Entry.vue
    staff/      StaffLayout.vue SignIn.vue Breadcrumbs.vue crumbs.ts queryClient.ts
    reviewer/   Queue.vue QueueTable.vue CandidateDetail.vue VideoPlayer.vue DecisionForm.vue
                Audit.vue copy.ts
    admin/      Sittings.vue Invites.vue Questions.vue SetupSteps.vue setup.ts
    styles/     tokens.css base.css staff.css (staff chunk only)
  public/spike/ the D2 browser capture spike page
  tests/
```

## Standing rules this keeps

- A light and dark toggle on every page; colours only from the tokens in `styles/tokens.css`.
- Time per question and for the whole test is recorded on every path (server side, unchanged).
- Wording stays plain, with a next step under every dead end.
- No candidate names; copy events carry a length only.
- Candidate bundle stays small: staff and admin screens are lazy chunks, no icon or UI library.

## Order of work

1. [x] Remove everything that depended on the locked-down browser: documents, backend, settings,
   migration `0005` (drops an unused column), tests.
2. [x] Build the Vue app beside the running one (port 5174), port the framework-free `lib/` code,
   then each screen.
3. [x] Redesign: tokens, type, spacing, motion, mobile, light and dark.
4. [x] Port the tests; add tests for the permission steps, the notification confirmation and the
   full-screen cover.
5. [x] Swap it into `frontend/`, rebuild, run every suite, check each route in light and dark and at
   phone width in a real browser, and run one full journey against the real API.

## Not part of this change

The action logger and heartbeat, the recorder and upload, the real pre-check endpoint, video
serving and deletion, packets and the AI step. The screens for them exist and run on fixtures
(`MOCKED_PREFIXES` in `src/lib/api.ts`) exactly as before.

## Risks specific to a plain browser

1. **HTTPS and a domain.** No camera without them outside localhost. Needed from Cytonn before the pilot.
2. **Video left behind when a tab closes.** Chunks stay in IndexedDB; the `/resume` page finishes the upload.
3. **Honest focus loss goes up** (chat, Windows pop-ups). The simulated false-flag rate is already
   above the target at the default thresholds, so measure it in real browsers before the pilot.
4. **Browser differences.** The requirement names Chrome and Edge only.
5. **Developer tools are available.** The question route serves one question at a time; confirm it
   never returns the whole paper.
6. **Wording.** Nobody can promise "locked down". The camera, the log and the human reviewer are
   the deterrent, and every document says so.
