# Replacing the made-up data with Cytonn's

Everything below is made up on purpose, so the screens and rules could be built and checked before
real data exists. All of it is labelled, and each piece can be removed or replaced on its own.

| What is made up | How to recognise it | How to replace it |
|---|---|---|
| The 60 questions | IDs `Q001` to `Q060`; statistics with source `synthetic` | Import Cytonn's per-question summary (and bank export), then retire the placeholders (below) |
| Per-question statistics (median time, share correct, p25, p75) | `question_stats.source = 'synthetic'` | The same import replaces them and marks them `cytonn` |
| The simulated sitting | Name "Simulated cohort 1 (made up)", candidates `sim-001` to `sim-016` | `python -m scripts.jobs simulate_cohort --purge` |
| The invited test candidates | `cand-001` to `cand-020`, sitting "Synthetic sitting 1" | Create a real sitting and invitations in the admin screens |

## Order to follow when Cytonn's data arrives

1. **Remove the simulated sitting first.** The retire step keeps any placeholder question that a
   session has drawn, so the simulated sessions would otherwise keep all sixty alive.

   ```powershell
   cd backend
   .\.venv\Scripts\python.exe -m scripts.jobs simulate_cohort --purge
   ```

2. **Close the sitting that is open.** The import and retire actions refuse while one is open.
3. **Import** Cytonn's summary CSV and, if they send one, the question-bank export, from the admin
   Questions screen. Imported rows replace question text, options, answer and statistics in place
   and mark the statistics `cytonn`.
4. **Retire the placeholders** from the same screen. A placeholder that a real session already drew
   is kept, because that session's paper still points at it.
5. **Recompute flags** for any sitting that has data, so the cohort rules use the new statistics:

   ```powershell
   .\.venv\Scripts\python.exe -m scripts.jobs compute_flags --sitting "<sitting name or id>"
   ```

## Checking the thresholds

The rule thresholds are the plan's proposed defaults (`app/services/flags/config.py`). To see how
often they flag an honest candidate and whether they still find the scripted cases:

```powershell
.\.venv\Scripts\python.exe -m scripts.jobs measure_false_flags --cohorts 40
.\.venv\Scripts\python.exe -m scripts.jobs measure_false_flags --cohorts 40 --set run_length=4 --set run_gap_focus_s=10
```

It simulates, measures and rolls everything back. Treat the result as a property of the
simulator's assumptions until the same rules have been run over real sittings.
