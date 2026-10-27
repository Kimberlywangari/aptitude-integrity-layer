# Browser capture spike findings (D2)

**Status: NOT YET RUN.** Fill this in after running the checklist in Chrome **and** Edge with the
spike page (`frontend/public/spike/index.html`, opened at `http://localhost:5173/spike/index.html`).
This was deliverable D2 of the first week.

> Do not start the recorder (D7) until the **Decision** block below is filled in.

## Decision

| Item | Value |
|---|---|
| Recording in Chrome and Edge | GO / NO-GO  *(fill in)* |
| Resume-upload plan | `/resume` page within 48 h, or `upload_incomplete` plus the complaint path  *(rule: check 4 passes means `/resume`; if it fails, `upload_incomplete`)* |
| Wording for what is "logged" | *(fill in from checks 6-10)* |
| Mic mute visibility (check 11) | `mute` event: yes/no · flat level: yes/no · starting `MIC_FLAT_PEAK`: ___ · `MIC_SILENCE_SECONDS`: ___ |
| Private (incognito) window | *(fill in from check 5: how the pre-check refuses it)* |

## Checklist

| # | Check | Chrome | Edge | Evidence | Decision |
|---|---|---|---|---|---|
| 1 | Camera and mic permission prompt works; a denied or later-revoked permission is detectable | | | | |
| 2 | `MediaRecorder` records, chunks arrive every ~10 s | | | | |
| 3 | Bitrate (extrapolated MB per hour; about 80 expected, 150 kbit/s video + 24 kbit/s audio) | | | | |
| 4 | **IndexedDB survives closing the tab and the browser** (chunks present at page load after reopening) | | | | |
| 5 | A private (incognito) window: do chunks persist, can the page tell? | | | | |
| 6 | Full screen starts from a button press; `fullscreenchange` fires when the candidate leaves (Esc, F11, Alt+Tab) | | | | |
| 7 | Copy, cut, paste and context menu reach the page (length only) | | | | |
| 8 | Print Screen: does the page see anything? | | | | |
| 9 | Alt+Tab, Windows key, and a **Windows notification or chat pop-up**: does focus loss reach the page as `blur` or `visibilitychange`? | | | | |
| 10 | Clicking on a second monitor while full screen: does `blur` fire? | | | | |
| 11 | Mute the mic at OS level, then unmute: does the track fire `mute` / `unmute`? Does the peak level go flat when muted and stay above a small floor when unmuted in a quiet room? Are the three audio constraints honoured (`getSettings()`)? | | | peak values: | |
| 12 | CPU and RAM while recording (Task Manager) | | | | |

## Notes

*(anything surprising: permission prompts, codec support, settings that had to be changed)*
