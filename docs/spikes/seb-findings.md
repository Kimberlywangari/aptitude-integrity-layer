# SEB spike findings (D2)

**Status: NOT YET RUN in real SEB.** The spike page and echo route are built and were exercised
in headless Chromium with a fake camera/mic (recording → IndexedDB → reload survival → echo, no
page errors). That proves the page works, not that SEB allows it. Fill this file in after running
the checklist inside SEB 3.10.2 (see `seb/README.md`).

> Do not start D3's SEB gate for real (`SEB_MODE=enforce`) until the **Decision** block below is
> filled in.

## Decision

| Item | Value |
|---|---|
| Recording inside SEB | GO / NO-GO  *(fill in)* |
| Resume-upload plan | A / B / C  *(fill in; rule: check 4 passes → B; check 4 fails and 10 passes → A; both fail → C)* |
| Key type that verifies | Config Key / Browser Exam Key  *(fill in; put the value in `.env` `SEB_ALLOWED_KEYS`)* |
| Wording for "every blocked attempt is logged" | *(fill in from checks 7-9)* |
| Mic mute visibility (check 12) | `mute` event: yes/no · flat level: yes/no · starting `MIC_FLAT_PEAK`: ___ · `MIC_SILENCE_SECONDS`: ___ |

## How to run

1. `docker compose up -d db`; API: `cd backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000`;
   UI: `cd frontend; npm run dev`.
2. Open `seb/exam.seb` (start URL `http://localhost:5173/spike/index.html`).
3. Work down the table. After each check press **Send log to server**; the lines go to
   `data/spike-log.jsonl`, which is your evidence if SEB blocks screenshots.

## Checklist

| # | Check | Result | Evidence | Decision |
|---|---|---|---|---|
| 1 | Camera and mic prompt or permission setting works inside SEB | | | |
| 2 | `MediaRecorder` records, chunks arrive every ~10 s | | | |
| 3 | Bitrate (extrapolated MB per hour; about 80 expected, 150 kbit/s video + 24 kbit/s audio) | | | |
| 4 | **IndexedDB survives quit and relaunch** (chunks present at page load after a restart) | | | |
| 4b | localStorage / sessionStorage / cookie markers survive quit and relaunch (context for Plan B) | | | |
| 5 | Echo route shows `X-SafeExamBrowser-*` headers on a `fetch()` call | | | |
| 6 | Which key reproduces the header for the rebuilt URL (Config Key or Browser Exam Key) | | | |
| 7 | Copy/paste blocked? Does the page still see a `copy` / `cut` / `paste` event? | | | |
| 8 | Print Screen blocked? Does the page see anything? | | | |
| 9 | Alt+Tab, Win key, Ctrl+Alt+Del: does focus loss (`blur`, `visibilitychange`) reach the page? | | | |
| 10 | Quit URL quits SEB when the page navigates to it | | | |
| 11 | ~~OBS Virtual Camera~~ | n/a | Out of scope: virtual-camera testing is not part of this build | skip |
| 12 | Mute the mic at OS level (Windows privacy toggle; hardware switch or headset button if available), then unmute: does the track fire `mute`/`unmute`? Does peak go flat when muted and stay above a small floor when unmuted in a quiet room? Are the three audio constraints honoured in `getSettings()`? | | peak values: | |
| 13 | CPU and RAM while recording (Task Manager) | | | |

## Notes

*(anything surprising: dialogs, permission prompts, SEB version quirks, settings that had to be
changed)*
