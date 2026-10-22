# Pilot runbook

For the person running the pilot sitting on Wednesday 28 October 2026 (the operator). Read it the
day before and keep it open on the day.

The pilot measures the project's success criteria with 12 to 16 volunteers. At that size the
rates are a rough guide and not proof, and the report says so.

## People

- **Operator (one):** runs the stack, watches it, and processes the sitting afterwards. Does not
  change code during the sitting. A bug found on the day goes on a list.
- **Observers (at least one, two is better):** each watches up to four seats and writes down the
  clock time of every marked action on the [observer sheet](observer-sheet.md).
- **Volunteers (16 if possible):** 10 honest and 6 following the [cheater scripts](cheater-scripts.md)
  (C1 to C6). The proposal asks for 12 to 16, with at least 8 honest and 6 scripted. The cohort
  checks need 8 finished sessions; with fewer they do not run and the report must say so.
- Two of the honest volunteers go offline for two minutes (the chunk-loss check).

Roles stay private. Everyone gets the [volunteer brief](volunteer-brief.md), which says some people
will act out cheating. Each cheater gets only their own card.

## Definitions the report uses

- **Flagged:** rule score of 1.0 or more (a candidate whose only flag is a logging problem is
  queued but counted separately). A lone focus loss, 0.5, is not flagged.
- **Top third:** the top third of the *queued* candidates, not of everyone who sat.
- Small numbers are indicative. Say so next to every rate.

## Decide first

These are the plan's open questions to Cytonn. The day cannot be run as written until each has
an answer. Fill the right column in.

| Item | Why it matters | Answer |
|---|---|---|
| The address volunteers open | A browser only gives a page the camera on `https://` or on `localhost`. Volunteers on their own laptops cannot use `localhost` on yours, so Cytonn's server with HTTPS (or something else serving `https://`) has to sit in front of the `web` container on port 8080 | |
| Venue and Wi-Fi | Each recording is up to 80 MB an hour, over the venue's network | |
| Date, start time, volunteer list | | |
| Observer(s) | | |
| Number of questions and test length | The sitting on this laptop today is 12 questions in 120 seconds, a testing value. The cheater scripts need about 30 minutes for 12 questions | |
| Candidate-facing wording | Placeholder until Cytonn approves it: [candidate notice](../../docs/candidate-notice.md) | |
| What happens to pilot recordings nobody reviews | Nothing deletes a recording without a decision ([master plan R9](../../docs/plan/00-master-plan.md)) | |

## The day before

After the dry run and the freeze.

- [ ] Take a backup and copy it off this laptop as well:

  ```powershell
  docker compose exec -T db pg_dump -U integrity -Fc integrity -f /tmp/pilot-eve.dump
  docker compose cp db:/tmp/pilot-eve.dump data/pilot-eve.dump
  ```

- [ ] Put the pilot settings in `.env` at the repository root:

  ```
  ENV=production
  PRECHECK_GATE=recording
  AI_PROVIDER=ollama
  OLLAMA_MODEL=gemma4:e2b
  PUBLIC_BASE_URL=https://<the pilot address>
  SESSION_SECRET=<a long random value, not the default>
  ```

  `ENV=production` makes the API refuse to start unless `PRECHECK_GATE=recording`, and it
  switches off the fault injection. This laptop's `.env` currently says
  `OLLAMA_MODEL=llama3.1:latest`, which the benchmark found far slower than `gemma4:e2b` (one
  candidate took 408 seconds, against a slowest of 74). Change it.

- [ ] Rebuild and check the settings reached the container:

  ```powershell
  docker compose up -d --build
  docker compose exec api printenv ENV PRECHECK_GATE AI_PROVIDER OLLAMA_MODEL
  ```

- [ ] Run the false-flag measurement now, while there is no pilot data. It simulates its own
  sittings, measures them and rolls them back:

  ```powershell
  docker compose exec api python -m scripts.jobs measure_false_flags --cohorts 40
  ```

  Last measured on 19 October: 16.5% of honest candidates queued, against a target of at most
  1 in 10. Write the new figure in the report. Do not change a threshold to improve it.

- [ ] Disk: 16 volunteers for an hour take about 0.7 GB at the usual 40 to 50 MB an hour each,
  and 1.3 GB at the 80 MB maximum. Check `docker system df` and the free space on the drive.
- [ ] Charge everything. Plug the laptop in and switch off sleep.

## Before volunteers arrive (45 minutes)

- [ ] Health: `curl.exe https://<the pilot address>/api/health` returns `{"status":"ok","db":true}`.
- [ ] Ollama is running and `gemma4:e2b` is pulled (`ollama list`). From the API container:

  ```powershell
  docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/tags', timeout=5).status)"
  ```

  It should print `200`. Load the model once so the first candidate's time is not the loading
  time: `ollama run gemma4:e2b "ready"`.
- [ ] ffmpeg is in the API image (`docker compose exec api ffmpeg -version`). The video and
  silence steps need it.
- [ ] A staff account for the review step:

  ```powershell
  docker compose exec api python -m scripts.jobs create_reviewer --email you@cytonn.com --role admin
  ```

  It asks for a password twice.
- [ ] Sign in at `/login/admin`.
  - **Close any old open sitting** (the made-up "Synthetic sitting 1" is open on this laptop). A
    link opened before the new sitting's opening time lands in the newest *open* sitting that is
    inside its window, which would be the old one.
  - Create the sitting, for example "Pilot 28 Oct", with its opening time, closing time, number
    of questions and test length.
  - Generate invitations: one per volunteer **plus two spare**. The codes are shown once. Download
    the CSV straight away.
- [ ] Fill in [truth.csv](truth.csv): one row per volunteer, with the candidate ID from the
  invitation CSV, the role (`honest` or `C1` to `C6`) and the seat. No names. Keep the list that
  says who sits where on paper only.
- [ ] Walk the whole candidate path yourself once on a spare code, through the real address, in
  Chrome. Check the microphone step appears: the `VITE_MIC_CHECK=off` switch only affects
  `npm run dev`, never this build. Then note that spare code as used.
- [ ] Clock check with the observers (see the [observer sheet](observer-sheet.md)).
- [ ] Brief the six cheaters and the two offline volunteers privately.
- [ ] Hand each volunteer their code. Read out what is recorded and for how long (and the consent
  wording, once Cytonn has approved it).

## During the sitting

The sitting takes about 60 to 90 minutes. Do not fix code. Watch these:

- The Sittings page in the admin area shows finished, in progress and not started.
- One query shows whether each person is recording and sending heartbeats. Each running candidate
  gains a chunk about every 10 seconds, and the last heartbeat is no more than about 15 seconds old:

  ```powershell
  docker compose exec db psql -U integrity -d integrity -c "select s.candidate_id, s.status, (select count(*) from video_chunks c where c.session_id = s.id) as chunks, (select max(h.server_ts) from heartbeats h where h.session_id = s.id) as last_heartbeat from sessions s where s.sitting_id = <sitting id> order by 1;"
  ```

- `docker compose logs api --tail 50` if something looks wrong.

The two offline volunteers will show a stalled heartbeat for about two minutes. That is expected,
and it is explained by a dropped connection, so it is not a flag.

### If something goes wrong

| What you see | What to do |
|---|---|
| "That code is not valid" | Check it against the CSV. Capital letters, dashes and spaces do not matter. |
| 429 "too many attempts" | 20 wrong codes in 5 minutes from one address. Wait 5 minutes. Behind nginx with `TRUST_FORWARDED_FOR=true` the address is the volunteer's own; on Docker Desktop for Windows every browser looks like one address and shares the limit. |
| "This test is not open right now" | The sitting window. Check its opening and closing times in the admin area. |
| Camera or microphone blocked | The pre-check tells the volunteer how to unblock it, in the browser and then in the system privacy settings. |
| "This address is not secure" | The link is not `https://`. Stop and fix the address; no camera will work. |
| Tab closed or browser crashed mid-test | Open the same link again. It returns the same test and the clock has kept running. Note the time on the observer sheet. |
| The upload page is stuck at the end | Keep the tab open. If it was closed, open the link again on the same computer and browser within 48 hours; the rest is sent from there. |
| The API is down | `docker compose ps`, then `docker compose up -d`. The browsers keep the recording on the device and send it when the server is back. |

## After the sitting

Run these from the repository root. The jobs run inside the `api` container because the video is
in its volume, so the files they read or write are copied in and out with `docker compose cp`.

1. **Wait for the uploads.** Check that nothing is missing, for everyone:

   ```powershell
   docker compose exec api python -m scripts.jobs chunk_integrity --sitting "Pilot 28 Oct"
   ```

   It exits with an error if any chunk is missing or changed. For anyone whose upload is not
   complete, write down who and why. Do not close the sitting early to hide it.

2. **Close the sitting.** It refuses while anyone is still in progress or has not started. A
   forced close (`--force`) works and is written to the audit log; say in the report if you used it.

   ```powershell
   docker compose exec api python -m scripts.jobs close_sitting --sitting "Pilot 28 Oct"
   ```

3. **Process it, timing every step.** This computes flags (the cohort checks too), joins the
   video, scans the audio, builds the packets and ranks with Ollama:

   ```powershell
   docker compose exec api python -m scripts.jobs process_sitting --sitting "Pilot 28 Oct" --provider ollama
   ```

   Copy the printed times into the report.

4. **Measure.**

   ```powershell
   docker compose cp eval/pilot/truth.csv api:/tmp/truth.csv
   docker compose exec api python -m scripts.jobs pilot_metrics --sitting "Pilot 28 Oct" --truth /tmp/truth.csv
   ```

   This gives honest candidates flagged, planted cheaters caught, cheaters in the top third and
   the AI seconds per candidate.

5. **Check the AI explanations.** The automatic check should pass 100%. Then read each explanation
   beside its numbers and tick it off by hand:

   ```powershell
   docker compose exec api python -m scripts.jobs ai_explanations --sitting "Pilot 28 Oct" --csv /tmp/handcheck.csv
   docker compose cp api:/tmp/handcheck.csv eval/reports/ai-explanations-handcheck.csv
   ```

6. **Check where the flags land in the video.** Follow the end of the [observer sheet](observer-sheet.md).

7. **Look at the misses.** For every cheater not caught and every honest volunteer flagged, write
   down which flag is responsible and what you would change. Do not change a threshold today to
   make the numbers look better. Put proposed changes in the report for the handover.

8. **Write the report** in [eval/reports/pilot-report.md](../reports/pilot-report.md). Every
   criterion gets a result, including the ones that miss.

9. **Wrap up.** Take a backup of the database and copy the report and the video volume somewhere
   safe. Decide with Cytonn what happens to the pilot recordings (nothing deletes unreviewed ones).
   Make sure every task branch is merged into `main` and `week-3` is tagged.
