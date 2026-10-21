# Which local model ranks and explains the flagged candidates

> **Status (19 Oct 2026): measured. Chosen model: `gemma4:e2b`.** This is the D11 benchmark from
> [week 3](../plan/week-03.md), done on the real `rank` job. It answers one question: which Ollama
> model should be the default for the AI step on this laptop, given the plan's limits.

## The limits a model has to meet

From the master plan (§7.7) and the week 3 criteria:

1. Every answer is valid JSON in the `Assessment` shape.
2. It passes the fact check (nothing cited that is not in the packet, no verdict words), at the first
   try or the single retry. A candidate whose answer cannot be trusted falls back to the rule order,
   so a model that falls back often is not doing the job.
3. **Under 2 minutes per flagged candidate**, retries included.

## Result: the real pipeline

16 flagged candidates from two simulated sittings, each model run alone over both, through
`python -m scripts.jobs rank --provider ollama` (real packets, the real `OllamaRanker`, the real fact
check and retry, `think` off, temperature 0, seed 7, `num_ctx` 4096). The model was loaded before its
run, so the load time is not counted.

| Model | Passed first time | Retried | Fell back to rules | Median | 90th percentile | Slowest | Over 2 min | Cheater above honest | Cheaters in top third |
|---|---|---|---|---|---|---|---|---|---|
| **`gemma4:e2b`** | **16** | 0 | 0 | **38 s** | 67 s | 74 s | **0** | 16 of 20 | 5 of 5 |
| `qwen3.5:4b` | 14 | 1 | 1 | 83 s | 136 s | 157 s | 4 | 17 of 20 | 5 of 5 |
| `llama3.1:latest` (the old default) | 14 | 1 | 1 | 94 s | 317 s | 408 s | 4 | 12 of 20 | 4 of 5 |
| Rule order only, no AI | | | | | | | | 16 of 20 | 5 of 5 |

"Cheater above honest" counts, over every pair in the queue with one planted cheater (tab lookup,
copier, answer runner, fast correct) and one honest candidate (honest, quick honest, honest with a
technical problem), how often the cheater was ranked higher. "Top third" counts planted cheaters among
the first third of the queue. The simulator knows who is who.

`gemma4:e2b` is the only model that met all three limits. Its slowest candidate was 74 s. The two
others had candidates over 2 minutes, a fallback each, and the old default once took 408 s, which was
a retry on top of a slow first answer.

## An earlier, wider run (10 hand-built packets, 21 models)

Run on 13 to 15 Oct with `eval/metrics/ai_benchmark.py` on stand-in packets and a lighter fact
check. Raw results are in `data/ai_benchmark/`. Ten models passed every check on all ten packets:

| Model | Median | Slowest | Strong vs weak packets ordered right |
|---|---|---|---|
| `gemma4:e2b` | 32 s | 45 s | 100% |
| `ministral-3:8b` | 95 s | 171 s | 100% |
| `granite4.1:8b` | 102 s | 170 s | 100% |
| `llama3.1:latest` | 80 s | 148 s | 93% |
| `qwen3:8b` | 106 s | 184 s | 93% |
| `qwen3.5:4b` | 71 s | 101 s | 87% |
| `gemma4:e4b` | 65 s | 89 s | 83% |
| `nemotron-3-nano:4b` | 87 s | 119 s | 83% |
| `granite4:1b` | 41 s | 65 s | 80% |
| `qwen3:4b` | 67 s | 119 s | 80% |

Eleven others broke the fact check at least once (verdict words, invented question numbers or
counts), among them `qwen2.5:7b`, `mistral:7b`, `llama3.2:3b` and `phi4-mini` (6 of 10 answers
had a problem). Only `gemma4:e2b` was both the fastest of the clean ones and perfectly ordered, which is why
it went into the real run.

## What this does not show

- **A small sample.** 16 candidates and 20 cheater-honest pairs per model. 17 of 20 against 16 of 20
  is one pair, so only the large gaps count: the old default's 12 of 20, and the time limits.
- **The AI did not order better than the rules.** `gemma4:e2b` matches the rule order exactly on this
  data (16 of 20, 5 of 5). The simulated cheaters are the kind the rules were written for, so this is
  the easy case. What the AI step adds here is an explanation and a second opinion, not a better
  queue. The real pilot is the test of that.
- **The explanations are thin.** All pass the fact check, but `gemma4:e2b` writes things like "these
  flags support each other in suggesting performance anomalies", which says less than the rule text
  beside it ("question 4 took 205 s against the candidate's own median of 55 s and was answered
  correctly"). `qwen3.5:4b` writes the fullest prose and `llama3.1:latest` the tersest accurate
  lines. The reviewer page shows the AI's explanation when it passed the fact check, so this is
  worth a decision (see below).
- **One machine.** The dev laptop: 15.7 GB of RAM, no GPU, Ollama 0.35.0. All times are CPU
  times. Cytonn's server will differ in both directions. Times include a retry when there was one.
  The first `gemma4:e2b` sitting overlapped some other work on the laptop, so its numbers lean
  pessimistic if anything.
- **Made-up history.** The per-question history in these packets is the synthetic baseline, as the
  packets say, until Cytonn's statistics replace it.

## Decision

Default `OLLAMA_MODEL` is now `gemma4:e2b` (in `backend/app/config.py`, `.env.example` and
`docker-compose.yml`). It is already pulled here; elsewhere: `ollama pull gemma4:e2b`.

**Open question for the team:** should the reviewer see the AI's explanation in place of the rule
explanation, or both? With this model the rule text is often the more useful of the two, and the
flags with their times are on the page either way. If the pilot shows the same, the cheap change is
to show the rule explanation first and the AI's as a second line labelled advisory. Switching to
`qwen3.5:4b` for better prose costs about double the time and would miss the 2-minute limit on some
candidates.

## To repeat it

A scratch database keeps the dev data clean. `seed_synthetic` must be told to write its invitation
file somewhere else, or it overwrites `data/invites.csv`.

```powershell
docker exec <db container> psql -U integrity -c "create database integrity_bench"
$env:DATABASE_URL = "postgresql+psycopg://integrity:integrity@localhost:5433/integrity_bench"
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m scripts.jobs seed_synthetic --seed 42 --invites $env:TEMP\bench-invites.csv
# a second cohort needs its own candidate prefix, which only the function takes:
#   from scripts.simulate_cohort import simulate
#   simulate(db, seed=43, name="Simulated cohort 2 (made up)", prefix="simb")
.\.venv\Scripts\python.exe -m scripts.jobs simulate_cohort --seed 42
.\.venv\Scripts\python.exe -m scripts.jobs process_sitting --sitting 2 --provider rules --skip-video
$env:OLLAMA_MODEL = "gemma4:e2b"
.\.venv\Scripts\python.exe -m scripts.jobs rank --sitting 2 --provider ollama
```

The job prints each candidate's status and seconds, and the median and slowest at the end. This run's
raw per-candidate results (answers, attempts, seconds) were saved to
`data/ai_benchmark/rank_pipeline/` on the dev laptop; `data/` is not committed.
