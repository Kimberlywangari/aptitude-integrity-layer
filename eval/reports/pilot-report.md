# Pilot report

> **Status: template. The pilot has not been run.** Nothing below is a result until it is filled
> in from the sitting. Delete this note when it is.

Pilot date: ____ · Venue and network: ____ · Operator: ____ · Observers: ____
Address volunteers used: ____ · Sitting name and ID: ____ · Build tag: ____

## What was run

| | |
|---|---|
| Volunteers who sat | ____ (honest ____, scripted ____) |
| Finished sessions | ____ (the cohort checks need 8 or more, and a closed sitting) |
| Cohort checks ran? | yes / no |
| Question statistics used | Cytonn's / made up (`history_source` in the flag detail) |
| Questions and test length | ____ questions, ____ minutes |
| AI model | `gemma4:e2b` through Ollama / other: ____ |
| Browsers | Chrome ____, Edge ____ |
| Settings | `ENV=production`, `PRECHECK_GATE=recording`, mic check on |

## Caveats that go with every number

- 12 to 16 people give indicative rates, not proof.
- "Flagged" means a rule score of 1.0 or more. "Top third" means the top third of the *queued*
  candidates, not of everyone who sat.
- If fewer than 8 sessions finished, the pace and spread checks did not run, and any cheater
  meant to be caught by them (C4, C5) was judged without them.
- The honest volunteers' behaviour on the day is the only honest behaviour measured. The
  synthetic honest cohort is the simulator's assumption.

## Results

| Criterion | Target | Result | Pass? | How measured |
|---|---|---|---|---|
| Rule-based checks catch scripted actions | 100% | | | [eval/scripted_actions.md](../scripted_actions.md), the scenario tests, and [scripted-run-browser.md](scripted-run-browser.md) |
| Honest volunteers wrongly flagged | at most 1 in 10 | pilot: ____ of ____; synthetic: ____% (run on ____) | | `pilot_metrics`, `measure_false_flags --cohorts 40` |
| Planted cheating caught | at least 8 in 10 | ____ of ____ | | `pilot_metrics` |
| Planted cheaters in the top third | at least 8 in 10 | ____ of ____ | | `pilot_metrics` |
| Flag lands near the moment in the video | within 2 s | ____ of ____ rows within 2 s; largest error ____ s | | `video_offset` on the observer sheet |
| AI explanations match the logs | 100% | automatic ____%; by hand ____ of ____ | | `ai_explanations` and the hand-check sheet |
| No video chunks lost after upload | 0 missing | ____ missing across ____ candidates (including the 2 offline) | | `chunk_integrity` |
| Deletion works | video gone 30 days after the decision | | | `tests/integration/test_retention.py`, run on ____ |
| AI step runs on the available laptop | under 2 min per flagged candidate | median ____ s, slowest ____ s, ____ fell back to rules | | `process_sitting` and `pilot_metrics` |

The blueprint paper criterion from the proposal does not apply: the generator was not built.

## Processing times

From `process_sitting`.

| Step | Seconds | Note |
|---|---|---|
| Compute flags | | |
| Assemble video | | |
| Scan audio | | |
| Build packets | | |
| Rank | | |

## Misses

For every planted cheater not caught and every honest volunteer flagged. Name the rule, not the
person.

| Candidate | Role | What happened | Rule responsible | Script followed as written? | What would change |
|---|---|---|---|---|---|
| | | | | | |

A planted cheater whose script was not followed (wrong answers, a step skipped) is a script
failure, listed here but not counted as a detection miss without saying so.

## Things that went wrong on the day

| Time | What | What was done | Fix for later |
|---|---|---|---|
| | | | |

## Proposed changes

Changes to thresholds or behaviour that the results suggest. None were made on the day.

| Change | Evidence | Effect expected |
|---|---|---|
| | | |
