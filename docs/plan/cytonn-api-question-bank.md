# Loading Cytonn's questions from their aptitude API

Branch: `feat/cytonn-api-question-bank`. Written 2026-10-22, before the API key worked, from the
integration guide Cytonn sent. Nothing here has seen a real response yet; the first real run is a
dry run (see "First real run").

## What the guide gives us

`GET https://hr.cytonn.com/api/aptitude/sections` with an `X-API-KEY` header returns every section,
its questions and each question's answers with `is_correct`. It carries no difficulty tag and no
timing per question. `GET /latest` returns candidates' names and scores; this task does not use it.

## What is not changed

- Candidates, sessions, events, video, the flag rules and the reviewer screens.
- `/latest`, candidate names and `pass_mark` (we decide nothing about a candidate).
- A `sections` table for `time_per_question`. The job prints it, so whoever creates a sitting can
  work out the duration (questions × minutes).

## Changes

1. **A question knows where it came from.** `questions.source` (`cytonn` or `synthetic`). Before this,
   "is this question real" was guessed from the statistics row, which breaks for a real question that
   has no statistics. Three places used the guess and now read the column: the bank summary (and so
   the admin setup checklist), and "Retire placeholders", which deletes `synthetic` questions that no
   session has drawn. Without this, one click would have deleted every question loaded from the API.
   The migration marks questions whose statistics came from Cytonn as `cytonn`; the rest stay
   `synthetic`. The CSV import now marks what it imports `cytonn`.
2. **Cytonn's ids are kept.** `questions.cytonn_id` and `options.cytonn_id` (unique, nullable). A
   question's own id is `C<cytonn id>` (for example `C10`), which cannot clash with `Q001`. Options
   are matched by their Cytonn id, never by letter, because the API returns answers in no fixed order.
3. **Any number of options, 2 to 8.** Letters A, B, C… follow the answers sorted by Cytonn's answer
   id. The candidate screen never shows letters, so nothing changes there. The authored-bank loader
   and the CSV import stay at four options: their file formats are ours.
4. **Questions that cannot be scored are skipped and reported**, never guessed: no answer marked
   correct (no marking scheme yet), more than one marked correct, fewer than 2 or more than 8
   answers, blank text, a section name over 32 characters, a repeated id.
5. **No statistics row for API questions.** The API has no per-question timing, and made-up numbers
   would feed the "far faster than past candidates" flag. The flag already skips a question with no
   statistics. The reviewer's note now says so (`history_source: none`) instead of calling the data
   synthetic.
6. **Re-running is safe.** Unchanged questions are left alone. A question that a session has already
   drawn is never changed (its answer key must stay what the candidate was scored against) and is
   reported. Questions Cytonn has dropped are reported, not deleted. The job refuses while a session
   is in progress, like the authored-bank loader.
7. **Sitting creation checks each section.** A paper spreads its questions over the sections, so any
   section may be asked for `ceil(count / sections)`. Creation used to check only the total, and a
   small section failed later, when a candidate started. It now answers `section_too_small` with the
   section names.

## The job

```powershell
cd backend
.\.venv\Scripts\python.exe -m scripts.jobs fetch_cytonn_bank --dry-run --save-raw ..\data\aptitude-sections-raw.json
.\.venv\Scripts\python.exe -m scripts.jobs fetch_cytonn_bank
.\.venv\Scripts\python.exe -m scripts.jobs fetch_cytonn_bank --file ..\data\aptitude-sections-raw.json
```

- The key is `APTITUDE_API_KEY` in `.env` (git-ignored). It is sent in the header only, and is never
  printed, logged or put in an error message.
- One request per run, so the 60 requests a minute limit is not a concern. The candidate's browser
  never talks to Cytonn.
- The raw response is saved only when `--save-raw` is given. Keep it under `data/` (git-ignored).
- Question text is plain text on the candidate screen. The job warns about HTML-looking text,
  very long text and duplicate options, so we see it before a candidate does.

## First real run

1. `--dry-run --save-raw` and read the report: sections, counts, minutes per question, what was
   skipped and why, and the warnings.
2. Look at the saved JSON for anything the guide did not say (HTML or images in the text, more than
   one correct answer, answer counts).
3. If the report is sound, run it without `--dry-run`, then follow
   `docs/replacing-synthetic-data.md` to retire the placeholders.

## Still open with Cytonn

- Are timers per question or only a total? (Today a sitting has one timer.)
- What timezone are the `/latest` test dates in?
- How do scores get back to Cytonn? The API cannot take them, and a link into Cytonn's recruitment
  system is out of scope in the proposal.
- Will the per-question summary (times, share correct) still arrive? It is the only source of real
  statistics for the speed check. Not worked out: the CSV importer overwrites a question's correct
  option with the file's letter, and the letters of API questions follow Cytonn's answer ids. If it
  does arrive, the importer needs a way to add statistics without touching the answer key.
