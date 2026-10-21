# What the Claude API will cost, with proof

> **Status (19 Oct 2026): estimate written, to be replaced by a measured figure after the 28 Oct
> pilot.** Answers the founders' question: *an approximate or exact amount for the Claude API, with
> proof.* An exact figure cannot exist before real use, so this gives three things: an estimate
> with every input shown, a **ceiling that cannot be exceeded** (it follows from two limits in the
> code), and a **meter** that turns the first real run into the exact number.

## The answer

| | Expected | Ceiling (cannot be exceeded) |
|---|---|---|
| **One candidate sent to the AI** | **KSh 3.50** (range KSh 1 to 11) | KSh 43 |
| **The 28 Oct pilot** (about 10 candidates queued) | **KSh 35** | KSh 432 |
| **Everything up to the 29 Oct handover** (pilot, three simulated sittings, 200 development calls) | **KSh 630** | KSh 5,500 |
| **Production, per 1,000 candidates who sit the test** (20% to 40% queued) | **KSh 690 to 1,390** | KSh 8,650 to 17,300 |

All at **KSh 129 to the dollar** (an assumption, see section 8) and the model in the settings,
**Claude Sonnet 5.5**.

**Recommended ask:** approve **KSh 2,000** (about $15.50) for the pilot and development, bought as
prepaid credit or capped with a spend limit in the Claude Console so that it is a real cap. It is
about three times the expected cost and still covers four times the thinking I assumed. After the
pilot, replace this estimate with the measured figure (section 9) and set the production budget from
that. Until then, plan production at **KSh 1,400 per 1,000 candidates**.

"Expected" is a planning figure built from stated assumptions. "Ceiling" is arithmetic that holds
whatever the model does. They are different kinds of number on purpose: founders asked for
approximate or exact, and a number is only exact once it has been measured.

## 1. What the money buys

Exactly one thing calls the API: the AI step that **orders and explains the flagged candidates**
after a sitting closes. It runs when `AI_PROVIDER=claude`; the default is `rules` (no AI) and a free
local model (Ollama) is the other option.

- It is called **once per queued candidate**, never per answer, per event or per candidate who sat.
  A candidate is queued only at a rule score of 1.0 or more, or with a gap in the record.
- It sends **text only**: a packet of numbers and flag names under the candidate ID. No video, no
  audio, no names, no free text the candidate wrote.
- If the first answer fails the fact check there is **one retry**. If that fails too, the rule order
  stands for that candidate and nothing more is spent. Nobody is dropped.

Nothing else in the backend uses a paid API: flags, packets, video, the reviewer screens and the
database all run on our own code.

## 2. The price (proof)

From Anthropic's own pages, read on 19 Oct 2026:

| Fact | Source |
|---|---|
| Model ID `claude-sonnet-5-5`: **$2 per million input tokens, $10 per million output tokens** | [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview) and the [pricing table](https://platform.claude.com/docs/en/about-claude/pricing) (row "Claude Sonnet 5.5: $2 / MTok ... $10 / MTok") |
| The Batch API is 50% off both ($1 and $5 for Sonnet 5.5) | Pricing page, batch table |
| Long prompts cost the same per token: "A 900k-token request is billed at the same per-token rate as a 9k-token request" | Pricing page, long context |
| Thinking is billed as output: "the tokens Claude spends reasoning are billed as output tokens, even when the thinking text isn't returned to you, and they count toward `max_tokens`" | [Thinking](https://platform.claude.com/docs/en/build-with-claude/thinking) |
| Low effort is the economical setting: "Most efficient. Significant token savings with some capability reduction", and "At lower effort levels, Claude can skip thinking entirely for simpler problems" | [Effort](https://platform.claude.com/docs/en/build-with-claude/effort) |
| 1M tokens is about 2.5M Unicode characters on the current tokenizer | Models overview, "Context window" |

The code uses these prices from one file, [pricing.py](../../backend/app/services/ranking/pricing.py),
and a test pins them ([test_ai_cost.py:25](../../backend/tests/unit/test_ai_cost.py#L25)).

## 3. The size of one call (proof: measured)

The prompt is a fixed instruction (1,345 characters), the JSON schema the answer must follow (1,590
characters) and the candidate's packet. I measured the real prompt the code builds for the ten
benchmark packets (`eval/fixtures`, the same shape as real ones):

| Packet | Flags | Packet chars | Whole prompt (chars) |
|---|---|---|---|
| Strong, 3 packets | 4 | 1,712 to 1,889 | 4,674 to 4,851 |
| Medium, 2 packets | 2 | 961 to 1,143 | 3,923 to 4,105 |
| Weak, 5 packets | 1 to 2 | 633 to 1,017 | 3,595 to 3,979 |

Median **3,951 characters**, largest **4,851**. At the documented 2.5 characters per token that is
**1,581 tokens typical, 1,941 for the largest measured**. (Packets are JSON, so this is the safe end:
at 4 characters per token the typical call would be 988.)

The longest prompt the code can send is **9,473 characters (3,790 tokens)**: the fixed parts, a
retry's list of problems, and a packet trimmed to its 6,000-character limit
([prompts.py:35](../../backend/app/services/ranking/prompts.py#L35)).

## 4. The size of one answer

The answer is strict JSON with an explanation of at most 80 words: **about 250 tokens**. On top of
that the model may think, and that is billed as output. At `effort: low`
([claude.py:72](../../backend/app/services/ranking/claude.py#L72)) the model thinks little and can skip
it, but I have no measurement of how much, so it is the one real unknown. I assume **1,500 thinking
tokens per call** and show the whole range:

| Thinking tokens per call | Cost per queued candidate |
|---|---|
| 0 | KSh 0.95 |
| 500 | KSh 1.79 |
| **1,500 (assumed)** | **KSh 3.47** |
| 3,000 | KSh 5.98 |
| 6,000 | KSh 11.01 |

Output is **85% of the cost** at the assumed level, input only 15%, which is why thinking is the
number that matters.

## 5. Cost of one candidate

```
one attempt   = 1,581 input x $2/M  +  1,750 output x $10/M  = $0.0207   (KSh 2.67)
one candidate = one attempt x 1.3 attempts                    = $0.0269   (KSh 3.47)
```

The 1.3 allows for the fact-check retry (the first answer failing 3 times in 10); I have no measured
retry rate yet.

## 6. Volume

How many candidates are queued is what moves the production figure. On the simulated sitting 6 of 16
were queued (37%), and the honest false-flag rate at the default thresholds measured 16.5% on
simulated data, so I use 20%, 30% and 40%. Real candidates will differ, and tuning the flag
thresholds changes this directly.

**Production, per 1,000 candidates who sit the test:**

| Queued | Candidates sent to the AI | Expected | Ceiling |
|---|---|---|---|
| 20% | 200 | $5.37 (KSh 693) | $67.03 (KSh 8,647) |
| 30% | 300 | $8.06 (KSh 1,040) | $100.55 (KSh 12,971) |
| 40% | 400 | $10.74 (KSh 1,386) | $134.06 (KSh 17,294) |

**Up to handover:** the pilot (10 queued), the plan's read-through of three simulated sittings (18
queued) and 200 development calls (benchmarking, prompt changes, re-runs):

| Thinking per call | Expected total |
|---|---|
| 0 | $1.34 (KSh 173) |
| **1,500 (assumed)** | **$4.88 (KSh 630)** |
| 6,000 | $15.52 (KSh 2,002) |

The KSh 2,000 ask is the 6,000-thinking-token row: four times the assumption.

## 7. The ceiling (proof by construction)

The most a candidate can cost follows from two numbers in the code:

| Limit | Where | Value |
|---|---|---|
| Attempts per candidate | `MAX_ATTEMPTS` in [runner.py:29](../../backend/app/services/ranking/runner.py#L29) | 2 |
| Output tokens per call, thinking included | `MAX_OUTPUT_TOKENS` in [claude.py:21](../../backend/app/services/ranking/claude.py#L21), sent as `max_tokens` | 16,000 |

`max_tokens` is a hard limit the API enforces on thinking plus text, so a call cannot write more.

```
one attempt, worst case = 3,790 input x $2/M  +  16,000 output x $10/M = $0.1676  (KSh 21.62)
one candidate, worst   = 2 attempts                                    = $0.3352  (KSh 43.24)
```

A test fails if either limit changes without this document being revisited
([test_ai_cost.py:101](../../backend/tests/unit/test_ai_cost.py#L101)). The ceiling rows above are that
figure times the number queued. They are not predictions (a real call would have to think for 16,000
tokens, twice, on every candidate); they are what cannot be exceeded. One honest limit: it assumes
the packet stays near its trimmed size. A packet with thousands of flags would add input tokens, but
even 100,000 extra input tokens add only $0.20 per attempt.

## 8. Exchange rate and other charges

The dollar rate is the second unknown. My search returned conflicting figures (about 117 to 129), none
from the Central Bank of Kenya, so I used 129, the high end. Use the CBK rate on the day of purchase;
the figures scale directly:

| KSh per $ | Per 1,000 candidates at 30% queued |
|---|---|
| 117.5 | KSh 947 |
| **129 (used)** | **KSh 1,040** |
| 140 | KSh 1,128 |

Not included: card or bank currency-conversion fees and any tax on the purchase (these depend on how
the account is paid for), the Claude Code subscription (separate), hosting and video storage.

## 9. How the estimate becomes exact

1. **Now, before any spend.** `python -m scripts.jobs ai_cost estimate --fixtures` reproduces every
   figure above. Run it with `--sitting <id>` to measure the real packets of a sitting instead.
2. **Exact input tokens, once an API key exists.** Anthropic's token-counting endpoint
   (`messages.count_tokens`) counts a prompt's tokens without running the model, which replaces the
   2.5 characters-per-token assumption with the real count.
3. **After the pilot, the exact cost.** Every call now stores the token counts the API itself reports
   (`Ranking.ai_attempts[].usage`, retries and refusals included). `python -m scripts.jobs ai_cost
   actual --sitting <id>` adds them up at the published price. Cross-check it against the usage
   page in the Claude Console.
4. Replace the assumptions in sections 4 to 6 with the measured thinking tokens and retry rate, and
   set the production budget from the result.

Until a real key is used, the Claude adapter has been exercised only against the SDK with a mocked
transport (so the request shape is right), not against the live API.

## 10. Ways to spend less

Costs per queued candidate, from the same calculator:

| Option | Per candidate | Per 1,000 sat at 30% queued | What it needs |
|---|---|---|---|
| **As planned:** Sonnet 5.5, low effort | KSh 3.47 | KSh 1,040 | Nothing |
| Thinking off on Sonnet 5.5 (`thinking: {type: "between_tools"}`, works at low effort) | KSh 0.95 | KSh 285 | A quality check on the benchmark packets; the fact check still guards every answer |
| Batch API (50% off) | KSh 1.73 | KSh 520 | Ranking is run after the sitting closes, so the wait is fine; the retry needs a second batch |
| Claude Haiku 5.5 | KSh 0.17 | KSh 52 | The same quality check and a hand check of the explanations |
| Claude Opus 5.5 | KSh 6.93 | KSh 2,079 | Nothing, but double the cost |
| Local model (Ollama), now the default (`gemma4:e2b`) | KSh 0 | KSh 0 | Time only: median 38 s, slowest 74 s per packet on this CPU-only laptop over 16 real packets, inside the 2-minute target. Its explanations are thinner than Claude's; see the [benchmark](../spikes/ollama-benchmark.md) |
| Fewer candidates queued | proportional | proportional | Tuning the flag thresholds on honest data |

Prompt caching is not worth it: input is only 15% of the cost and the repeated part is small.

## 11. Assumptions and what would change them

| Assumption | Basis | If wrong | How we find out |
|---|---|---|---|
| Sonnet 5.5 at $2 and $10 | Official pages, 19 Oct 2026 | Linear in any change | `pricing.py` is the one place to edit |
| 2.5 characters per token | Anthropic's documented ratio | Tokens up to 1.6x lower at 4 characters per token, so cost falls | `count_tokens`, then the pilot's metered usage |
| 1,500 thinking tokens per call | **No measurement** | Section 4 table: KSh 1 to 11 per candidate | The pilot's metered usage |
| 1.3 attempts per candidate | **No measurement** | At most 2 (the ceiling) | The pilot: `ai_attempts` |
| 20% to 40% queued | Simulated data only | Proportional | The pilot sitting |
| KSh 129 per $ | Conflicting search results | Section 8 table | CBK rate on the day |
| 200 development calls | My guess | Proportional, about KSh 2.7 each | `ai_cost actual` |

## Reproduce

```powershell
cd backend
.\.venv\Scripts\python.exe -m scripts.jobs ai_cost estimate --fixtures            # these figures
.\.venv\Scripts\python.exe -m scripts.jobs ai_cost estimate --fixtures --thinking-tokens 6000 --usd-kes 140
.\.venv\Scripts\python.exe -m scripts.jobs ai_cost actual --sitting <id>          # after a real run
.\.venv\Scripts\python.exe -m pytest tests/unit/test_ai_cost.py tests/integration/test_ai_cost.py
```

Sources: [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview),
[Pricing](https://platform.claude.com/docs/en/about-claude/pricing),
[Thinking](https://platform.claude.com/docs/en/build-with-claude/thinking),
[Effort](https://platform.claude.com/docs/en/build-with-claude/effort). The exchange-rate searches
(Trading Economics, MoneyConvert) were inconsistent and are not relied on; use the
[Central Bank of Kenya](https://www.centralbank.go.ke) rate.
