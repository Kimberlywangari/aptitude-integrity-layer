# Flag rules in plain words

A flag is a fact a reviewer can look at. It is never a verdict: nothing here decides anything
about a candidate. Flags and their points only put the queue in order.

The values below are the starting defaults in
[backend/app/services/flags/config.py](../backend/app/services/flags/config.py). They are tuned
on honest candidates, never on cheaters alone.

## The eight flags

| Flag | What it means | Fires when | Points |
|---|---|---|---|
| `FOCUS_LOSS` | Left the test window | The window lost focus for **1 second or more**. One flag per loss | 0.5 each, **2.0 at most** in total |
| `COPY_ATTEMPT` | Tried to copy or cut a question | Any copy or cut on question text. Only the length is kept, never the text | 3 each |
| `LONG_HOLD_CORRECT` | Sat on a question far longer than usual, then got it right | Time is more than the larger of **3 x** their own median or their own median **+ 45 s**, and the answer is correct. Needs **5 other answers** to compare against | 3, plus 1 if focus was lost during it |
| `CORRECT_RUN_AFTER_GAP` | Stepped away, came back and got several right | **3 correct answers in a row** straight after a focus loss of **5 s or more**, or an idle stretch of **60 s or more**. Skipped questions are ignored, so a skip does not break the run | 2 |
| `FAST_CORRECT_VS_HISTORY` | Right answers much faster than past candidates | Correct and quicker than **0.5 x** the question's p25 time (**x 1.5** for hard questions), on **at least 2** questions, counting only questions with **30 or more** past candidates. One flag per candidate | 2 |
| `PACE_OUTLIER` | Average time per question unlike the rest of the sitting | The sitting is **closed**, has **8 or more** candidates (each with at least 2 answered questions), and their average is **3 or more** robust-z away from the middle, fast or slow | 1.5 |
| `SPREAD_OUTLIER` | Answer times unusually even or uneven | Same rule as pace, applied to the standard deviation of their times. A very narrow spread is the interesting one | 1.5 |
| `LOGGING_PROBLEM` | The record has a hole | No heartbeat for **more than 35 s**, and no dropped connection or page reload explains it | 0 |

`LOGGING_PROBLEM` says "we are missing data", not "the candidate did something". It sits in its own
lane, below everyone who has real evidence.

## Who is queued

A candidate enters the reviewer queue at a rule score of **1.0 or more**, or with any
`LOGGING_PROBLEM`. A lone focus loss (0.5) does not: it is still recorded as a flag and still shows
on the candidate's page, but they are not queued, get no packet and are not sent to the AI. The
threshold is `flagged_score` in `config.py`.

## The rule score

Add up the points of all flags, then:

- **+1** for each extra kind of flag beyond the first (not counting `LOGGING_PROBLEM`).
- **+1** if any two flags are **120 s or less** apart.

The reviewer screen always shows this breakdown, so nobody is ranked by a number they cannot take
apart.

**Example, a score of 13:** 2 focus losses (1.0) + 1 copy (3) + 1 long hold with focus lost (4) +
1 correct run after a gap (2) = 10. That is 4 kinds of flag, so +3 for the extra kinds = **13**.
Had two of those flags been within 2 minutes of each other, it would be 14.

## How the queue is ordered, and which model is used

**Rule order (always worked out, with or without AI).** Candidates with evidence come first, a
candidate whose only flag is `LOGGING_PROBLEM` comes last. Within each group: higher rule score
first, then whoever was flagged first, then candidate ID, so the order is the same every time.

**Strength, 1 to 5.** The AI gives each candidate a strength. When the AI is not used, or its answer
fails the fact check, the rule score is turned into a strength instead:

| Rule score | Strength |
|---|---|
| under 2 | 1 |
| 2 to under 4 | 2 |
| 4 to under 6 | 3 |
| 6 to under 9 | 4 |
| 9 or more | 5 |

A candidate whose only flag is `LOGGING_PROBLEM` is always 1. The final order is strength, then rule
score, then who was flagged first.

**The AI step.** It reads one candidate's evidence packet (candidate ID, never a name) and writes a
strength and a short explanation. It runs only on queued candidates, one at a time.

- **Model:** `gemma4:e2b`, run locally through Ollama. It was chosen by measurement on 19 Oct 2026
  (median 38 s, slowest 74 s, 16 of 16 passed the fact check first time; the old default
  `llama3.1:latest` once took 408 s). See [spikes/ollama-benchmark.md](spikes/ollama-benchmark.md).
- **Claude is the other option:** `claude-sonnet-5-5`, switched on with `AI_PROVIDER=claude` and an
  API key. It has only been tested with mocked replies, never live.
- **Off by default:** `AI_PROVIDER` is `rules`, which means no AI at all and the rule order stands.
  Use `ollama` to turn the model on.
- **Fact check:** every number, question and time in the explanation must be in the packet, and
  words like "cheated", "guilty", "disqualify" or "reject" are refused. A failed answer is retried
  once. If the retry fails too, that candidate keeps the rule order and the rule explanation.
- **No verdicts, no removals:** the AI can move a candidate up or down. It cannot remove anyone,
  set a threshold or decide anything, and every queued candidate reaches a reviewer.

## What the numbers mean

| Kind of number | Meaning |
|---|---|
| **Points** (0.5, 1.5, 2, 3) | How much a flag adds to the rule score. A bigger number means a stronger signal. Points only order the queue |
| **Seconds** (1, 5, 35, 45, 60, 120) | Time limits. A focus loss under **1 s** is ignored. **5 s** and **60 s** are how long a focus loss or idle stretch must be to count as "stepping away". **35 s** is the heartbeat gap. **45 s** is the extra time on a question. **120 s** is how close two flags must be to count as clustered |
| **Counts** (2, 3, 5, 8) | **2** fast answers, **3** correct in a row, **5** other answers to compare against, **8** candidates in a sitting before the group comparisons run |
| **Multipliers** (3 x, 0.5 x, 1.5 x) | **3 x** their own usual time; **0.5 x** the quick time for that question; **1.5 x** makes the fast rule less strict on hard questions |
| **Median** | The middle value. Used instead of the average so one odd answer does not distort it |
| **p25** | The time the fastest quarter of past candidates beat on that question |
| **Robust z (3)** | How far someone is from the middle of the group, measured in typical-spread units. **3** is far enough that it is rare in an ordinary group |

In the reviewer queue: **Rank** is the position in the list, **Flags** is how many flags the
candidate has, **Rule score** is the total above, and **Order set by** says whether the rules or the
AI set the order.

## Not flags

These are shown as context next to the flags and never add points: the test score, pace, page
reloads, connection drops, the candidate's own self-report, and microphone silence or muting of
a minute or more.

## Things to know

- **Focus-loss cap:** the code always caps focus-loss points at 2.0. The master plan says "unless
  there are 3 or more losses", which the code does not do. Decide which one is intended.
- **Question history:** `FAST_CORRECT_VS_HISTORY` compares against estimated times until Cytonn's
  real statistics are imported. Its detail says `history_source: synthetic` or `cytonn`, so a
  reviewer knows how much to lean on it. Questions loaded from Cytonn's aptitude API have no
  statistics at all (the API has no per-question timing), so the rule skips them; a paper made only
  of such questions shows `history_source: none` and the reviewer page says the check could not run.
- **False flags are above the target.** Measured on 19 Oct 2026 with the defaults above, over 40
  simulated sittings of 16 (400 honest candidates): **66 were queued by a rule other than a lone
  focus loss, 16.5%**. The target is at most 1 in 10. What fired on them: `LONG_HOLD_CORRECT` 37,
  `CORRECT_RUN_AFTER_GAP` 18, `FAST_CORRECT_VS_HISTORY` 14, `SPREAD_OUTLIER` 3, `PACE_OUTLIER` 2. The
  scripted cheating cases were found 99 to 100% of the time, but those cases are stark by
  construction and the honest behaviour is the simulator's assumption, so tuning on this alone would
  be partly circular. Nothing has been changed. Repeat the measurement with
  `python -m scripts.jobs measure_false_flags --cohorts 40`, and try a value with `--set name=value`.
- **Changing a value:** edit `config.py`, then run `python -m scripts.jobs compute_flags` again.
  Recomputing replaces the earlier rule flags, so it is safe to repeat.
