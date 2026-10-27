# AI provider: running on a local model now, switching to Claude later

Status, 27 Oct 2026. `.env`, `.env.example` and both compose files now default to Claude
(`AI_PROVIDER=claude`, `QUESTION_PROVIDER=claude`, `QUESTION_SOLVES=3`, `QUESTION_WORKERS=4`,
`QUESTION_TIMEOUT_S=120`, `AI_TIMEOUT_S=90`, `QUESTION_WAIT_LIMIT_S=120`). The key is in `.env` and
both paths ran live on 27 Oct 2026 (a pilot capped at $1, total spent $0.071):

- Question writer, 2 numerical questions: 3 calls, 15 s, $0.0124, both correct, nothing thrown away.
- Ranking, 3 made-up benchmark packets (no database, no real candidate): 6 calls, $0.0498 (about 1.7
  cents a packet, 290 output tokens a call, so thinking is small: the plan assumed 1,750). **All three
  first answers failed the fact check** (an id the packet does not list, a number not in the facts) and
  all three retries passed. That is a 100% retry rate where the plan assumed 30%; it doubles the calls but
  the cost stays in pennies. Worth tightening the prompt before a real sitting, with a bigger sample.

The Claude code paths were audited against the installed SDK (anthropic 2.3.0: `output_format` merges
into `output_config`; no `thinking`, `temperature`, `tool_choice` or prefill, which Sonnet 5.5 rejects).
Not done: a real sitting, the admin page's "Try the writer", logic-puzzle categories.

Nothing in the code changes when you move to Claude. It is a settings change in
`.env`, one package, and one live check. This page says exactly what.

## Today (no cost, runs on this laptop)

| Job | Setting | Value | Why this model |
|-----|---------|-------|----------------|
| Writing a candidate's questions | `QUESTION_PROVIDER` / `QUESTION_OLLAMA_MODEL` | `ollama` / `qwen3:8b` | On 24 Oct it wrote numerical questions that passed the checks (qwen2.5:7b failed one after four rounds). Logic puzzles still often fail the independent check on both, so a whole paper is not reliable |
| Ranking and explaining flagged candidates | `AI_PROVIDER` / `OLLAMA_MODEL` | `ollama` / `gemma4:e2b` | Passed every check on all ten benchmark packets (`docs/spikes/ollama-benchmark.md`) |

Both need Ollama running (`ollama serve`) and the models pulled (`ollama pull qwen3:8b`,
`ollama pull gemma4:e2b`). A laptop CPU writes about one question a minute, so an AI sitting of 20
questions takes a candidate about 20 minutes of waiting at the start, which is why the page shows
"Preparing your questions: n of m". `rules` (no AI at all) is always available as a fallback for
ranking: set `AI_PROVIDER=rules`.

The AI never decides anything about a candidate. It writes questions and it ranks and explains
flags. Both providers go through the same checks, so the safeguards do not change with the model.

## When the Claude API is paid for

Do these in order. Nothing else needs to change.

1. **Get a key** from the Anthropic Console (console.anthropic.com), with billing set up. Set a
   monthly spend limit there first.
2. **Install the client** (one small package, already in the Docker image):
   `cd backend; .\.venv\Scripts\python.exe -m pip install -e ".[claude]"`
3. **Edit `.env`** (never commit it, never paste the key into chat):

   ```
   ANTHROPIC_API_KEY=<the key>
   CLAUDE_MODEL=claude-sonnet-5-5
   QUESTION_PROVIDER=claude
   AI_PROVIDER=claude
   ```

   `claude-sonnet-5-5` is the default. Other models that are priced in the code:
   `claude-haiku-5-5` (cheapest), `claude-opus-5-5`, `claude-fable-5-1` (dearest).
4. **Tune for speed.** Claude answers in seconds, so the waits and the strictness can change:

   | Setting | Local model | With Claude | Effect |
   |---------|-------------|-------------|--------|
   | `QUESTION_SOLVES` | 2 | 3 | Each question is solved 3 times and kept only if all agree. Stricter, still fast |
   | `QUESTION_WORKERS` | 2 | 4 to 8 | More candidates' papers written at once |
   | `QUESTION_TIMEOUT_S` | 300 | 60 | A call that takes a minute is a failure |
   | `AI_TIMEOUT_S` | 150 | 60 | Same, for ranking |
   | `QUESTION_WAIT_LIMIT_S` | 600 | 120 | A candidate is offered "ask again" sooner |

5. **Restart the API** (and the worker if you use Docker: `docker compose up -d --build`).
6. **Check it live before any real sitting**, one command each, both print what they wrote and cost:
   - `.\.venv\Scripts\python.exe -m scripts.jobs try_question_writer --category numerical --count 2`
   - `.\.venv\Scripts\python.exe -m scripts.jobs rank --sitting <name> --provider claude`
   - Admin page, New sitting, "Written by AI", "Try the writer".
7. **See what it cost.** `.\.venv\Scripts\python.exe -m scripts.jobs ai_cost actual --sitting <name>`
   adds up the tokens Anthropic reported. `ai_cost estimate --candidates 1000` plans ahead. Prices
   live in `backend/app/services/ranking/pricing.py`; if Anthropic changes a price, change it there
   and nowhere else.

### What you can expect to change

- **Speed:** questions in seconds instead of a minute each, so candidates barely wait.
- **Quality:** fewer thrown-away questions and fewer ambiguous ones. The checks stay on.
- **Cost:** pennies per candidate for ranking (only flagged candidates are ranked), a few cents per
  AI paper. `ai_cost estimate` gives the figure for your numbers.
- **Privacy:** with Claude, packets (candidate IDs, no names, no copied text) and the question
  prompts leave your network to Anthropic. Local models keep everything on the machine. Tell
  Cytonn's data protection contact before switching a real sitting.
- **If the key is wrong or the API is down:** an AI sitting cannot be created (the admin page says
  so), and ranking falls back to the rule order for that candidate. Nobody is dropped.

### Going back

Set `AI_PROVIDER=ollama` and `QUESTION_PROVIDER=ollama` and restart. Papers already written stay.

## On the hosted server

The server has no GPU, so do not plan on a local model there. Either install Ollama on the server
host and accept about a minute a question, or use Claude. See `hosting.md`.
