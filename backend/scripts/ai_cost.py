"""What the Claude API costs this project: an estimate to plan with, and the exact figure to check
it against.

    python -m scripts.jobs ai_cost estimate [--fixtures | --sitting X] [--candidates 1000]
                                            [--thinking-tokens 1500] [--usd-kes 129] ...
    python -m scripts.jobs ai_cost actual --sitting X [--usd-kes 129]

`estimate` measures real prompts (the benchmark's hand-built packets with --fixtures, or the packets
stored for a sitting), turns characters into tokens at the documented ratio, adds the answer and an
assumed amount of thinking, and prices it at the published rate. It also prints the ceiling, the
most a candidate can possibly cost, which follows from two limits in the code (the output cap per
call and two attempts per candidate) and holds however the model behaves.

`actual` adds up the tokens the API itself reported for every call stored with a sitting's ranking
(Ranking.ai_attempts[].usage), so after a real run the cost is measured, not estimated.

Prices live in app/services/ranking/pricing.py. Thinking tokens are billed as output tokens.
"""

import argparse
import math
import statistics
import sys
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import REPO_ROOT, get_settings
from app.models import Packet, Ranking
from app.services.ranking import prompts
from app.services.ranking.claude import MAX_OUTPUT_TOKENS
from app.services.ranking.pricing import UnknownModel, cost_usd
from app.services.ranking.runner import MAX_ATTEMPTS
from scripts.common import resolve_sitting

# Anthropic documents 1M tokens as about 2.5M Unicode characters on the current tokenizer. A packet
# is JSON, which has more punctuation and numbers than prose, so this is the safe end of the range.
CHARS_PER_TOKEN = 2.5
ANSWER_TOKENS = 250  # a full Assessment: about 600 characters of JSON
THINKING_TOKENS = 1500  # an assumption: low effort may think far less, or none at all
ATTEMPTS_PER_CANDIDATE = 1.3  # an assumption: how often the fact check forces the one retry
USD_KES = 129.0  # an assumption: set it to the Central Bank of Kenya rate on the day
QUEUED_SHARES = (0.2, 0.3, 0.4)  # the share of candidates who are queued, so sent to the AI
THINKING_SENSITIVITY = (0, 500, 1500, 3000, 6000)


def tokens_from_chars(chars: int, chars_per_token: float = CHARS_PER_TOKEN) -> int:
    return math.ceil(chars / chars_per_token)


def call_chars(packet: dict, violations: list[str] | None = None) -> int:
    """Characters in the whole prompt for one packet: system prompt, packet and schema."""
    return sum(len(m["content"]) for m in prompts.build_messages(packet, violations))


def largest_call_chars() -> int:
    """The longest prompt the code can send: everything fixed, a retry's list of problems, and a
    packet at the size `prompts.compact` trims to (MAX_PACKET_CHARS)."""
    retry_notes = [f"unknown_flag_id: F{n}" + "x" * 40 for n in range(6)]
    return call_chars({}, retry_notes) + prompts.MAX_PACKET_CHARS


@dataclass
class PerCandidate:
    model: str
    input_tokens: int  # one attempt, the typical packet
    input_tokens_largest: int  # one attempt, the largest packet measured
    output_tokens: int  # one attempt: the answer plus thinking
    attempts: float
    per_attempt_usd: float
    per_candidate_usd: float


def per_candidate(
    chars: list[int],
    model: str,
    *,
    chars_per_token: float = CHARS_PER_TOKEN,
    answer_tokens: int = ANSWER_TOKENS,
    thinking_tokens: int = THINKING_TOKENS,
    attempts: float = ATTEMPTS_PER_CANDIDATE,
) -> PerCandidate:
    typical = tokens_from_chars(int(statistics.median(chars)), chars_per_token)
    largest = tokens_from_chars(max(chars), chars_per_token)
    output = answer_tokens + thinking_tokens
    one = cost_usd(model, typical, output)
    return PerCandidate(model, typical, largest, output, attempts, one, one * attempts)


def ceiling_usd(
    model: str,
    *,
    chars_per_token: float = CHARS_PER_TOKEN,
    attempts: int = MAX_ATTEMPTS,
    max_output: int = MAX_OUTPUT_TOKENS,
) -> float:
    """The most one candidate can cost: every attempt used, each with the largest possible prompt
    and the output cap spent in full. The model's behaviour cannot move this number."""
    longest = tokens_from_chars(largest_call_chars(), chars_per_token)
    return attempts * cost_usd(model, longest, max_output)


@dataclass
class Actual:
    candidates: int = 0
    attempts: int = 0
    unmetered_attempts: int = 0  # calls with no recorded usage (an API error before any answer)
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    local_input_tokens: int = 0  # Ollama: counted, but free
    local_output_tokens: int = 0
    by_model: dict[str, float] = field(default_factory=dict)


def actual_for_sitting(db: Session, sitting_id: int) -> Actual:
    """The measured spend: every attempt's reported tokens, priced at the model's published rate."""
    result = Actual()
    for ranking in db.scalars(select(Ranking).where(Ranking.sitting_id == sitting_id)):
        if ranking.ai_status == "not_run" or not ranking.ai_attempts:
            continue
        result.candidates += 1
        for attempt in ranking.ai_attempts:
            result.attempts += 1
            usage = attempt.get("usage")
            if not usage:
                result.unmetered_attempts += 1
                continue
            tokens_in, tokens_out = usage["input_tokens"], usage["output_tokens"]
            if ranking.provider == "claude":
                result.input_tokens += tokens_in
                result.output_tokens += tokens_out
                spent = cost_usd(ranking.model or "", tokens_in, tokens_out)
                result.usd += spent
                result.by_model[ranking.model] = result.by_model.get(ranking.model, 0.0) + spent
            else:
                result.local_input_tokens += tokens_in
                result.local_output_tokens += tokens_out
    return result


# ------------------------------------------------------------------------------------ output


def _fixture_calls() -> list[int]:
    sys.path.insert(0, str(REPO_ROOT))  # the benchmark's packets live beside the backend
    from eval.fixtures.synthetic_packets import PACKETS

    return [call_chars(item["packet"]) for item in PACKETS]


def _stored_calls(db: Session, sitting_id: int) -> list[int]:
    packets = list(
        db.scalars(
            select(Packet.json)
            .join(Ranking, Ranking.session_id == Packet.session_id)
            .where(Ranking.sitting_id == sitting_id)
        )
    )
    return [call_chars(p) for p in packets]


def _money(usd: float, rate: float) -> str:
    return (
        f"${usd:,.2f} (KSh {usd * rate:,.0f})"
        if usd >= 1
        else f"${usd:.4f} (KSh {usd * rate:,.2f})"
    )


def run_estimate(args: argparse.Namespace) -> None:
    from app.db import SessionLocal

    model = args.model or get_settings().claude_model
    if args.sitting:
        with SessionLocal() as db:
            sitting = resolve_sitting(db, args.sitting)
            chars = _stored_calls(db, sitting.id)
        source = f"{len(chars)} packets stored for sitting {sitting.id} ({sitting.name})"
    else:
        chars = _fixture_calls()
        source = f"{len(chars)} hand-built benchmark packets (eval/fixtures)"
    if not chars:
        raise SystemExit("no packets to measure: run build_packets for that sitting first")

    est = per_candidate(
        chars,
        model,
        chars_per_token=args.chars_per_token,
        answer_tokens=args.answer_tokens,
        thinking_tokens=args.thinking_tokens,
        attempts=args.attempts,
    )
    rate = args.usd_kes
    cap = ceiling_usd(model, chars_per_token=args.chars_per_token)

    print(f"model: {model}   measured: {source}")
    print(
        f"prompt characters per call: min {min(chars)}, median {int(statistics.median(chars))}, "
        f"max {max(chars)}   (largest the code can send: {largest_call_chars()})"
    )
    print(
        f"tokens per call at {args.chars_per_token} characters per token: input "
        f"{est.input_tokens} typical, {est.input_tokens_largest} largest measured; "
        f"output {est.output_tokens} "
        f"(answer {args.answer_tokens} + thinking {args.thinking_tokens})"
    )
    print(
        f"one attempt: {_money(est.per_attempt_usd, rate)}   "
        f"per queued candidate at {est.attempts} attempts: {_money(est.per_candidate_usd, rate)}"
    )
    print(
        f"CEILING per queued candidate ({MAX_ATTEMPTS} attempts, {MAX_OUTPUT_TOKENS} output tokens "
        f"each, largest prompt): {_money(cap, rate)}"
    )
    print()
    print(
        f"per {args.candidates:,} candidates who sit the test (exchange rate KSh {rate:g} per $):"
    )
    print(f"  {'queued':>7} {'AI calls':>9} {'expected':>24} {'ceiling':>26}")
    for share in args.queued_share:
        n = round(args.candidates * share)
        print(
            f"  {share:>7.0%} {n:>9,} {_money(n * est.per_candidate_usd, rate):>24} "
            f"{_money(n * cap, rate):>26}"
        )
    print()
    print("thinking tokens per call -> cost per queued candidate (the biggest unknown):")
    for thinking in THINKING_SENSITIVITY:
        row = per_candidate(
            chars,
            model,
            chars_per_token=args.chars_per_token,
            answer_tokens=args.answer_tokens,
            thinking_tokens=thinking,
            attempts=args.attempts,
        )
        print(f"  {thinking:>6} -> {_money(row.per_candidate_usd, rate)}")


def run_actual(args: argparse.Namespace) -> None:
    from app.db import SessionLocal

    with SessionLocal() as db:
        sitting = resolve_sitting(db, args.sitting)
        result = actual_for_sitting(db, sitting.id)
    rate = args.usd_kes
    print(
        f"sitting {sitting.id} ({sitting.name}): {result.candidates} candidates sent to the AI, "
        f"{result.attempts} calls"
    )
    if result.input_tokens or result.output_tokens:
        print(
            f"Claude tokens as the API reported them: {result.input_tokens:,} in, "
            f"{result.output_tokens:,} out"
        )
        print(
            f"SPEND: {_money(result.usd, rate)}"
            + (
                f", {_money(result.usd / result.candidates, rate)} per candidate"
                if result.candidates
                else ""
            )
        )
    else:
        print("no Claude calls are recorded for this sitting, so nothing was spent on it")
    if result.local_input_tokens or result.local_output_tokens:
        print(
            f"local model tokens (free): {result.local_input_tokens:,} in, "
            f"{result.local_output_tokens:,} out"
        )
    if result.unmetered_attempts:
        print(
            f"note: {result.unmetered_attempts} calls reported no usage (an error before any "
            f"answer), so they are not in the total; the console's own usage page is the check"
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="mode", required=True)

    est = sub.add_parser("estimate", help="plan: measure prompts and price them")
    group = est.add_mutually_exclusive_group()
    group.add_argument("--fixtures", action="store_true", help="the benchmark packets (default)")
    group.add_argument("--sitting", help="packets stored for this sitting (id or name)")
    est.add_argument("--model", default=None, help="default: CLAUDE_MODEL from the settings")
    est.add_argument("--candidates", type=int, default=1000)
    est.add_argument("--queued-share", type=float, nargs="+", default=list(QUEUED_SHARES))
    est.add_argument("--chars-per-token", type=float, default=CHARS_PER_TOKEN)
    est.add_argument("--answer-tokens", type=int, default=ANSWER_TOKENS)
    est.add_argument("--thinking-tokens", type=int, default=THINKING_TOKENS)
    est.add_argument("--attempts", type=float, default=ATTEMPTS_PER_CANDIDATE)
    est.add_argument("--usd-kes", type=float, default=USD_KES)

    act = sub.add_parser("actual", help="check: add up the tokens the API reported")
    act.add_argument("--sitting", required=True)
    act.add_argument("--usd-kes", type=float, default=USD_KES)

    args = parser.parse_args(argv)
    try:
        run_estimate(args) if args.mode == "estimate" else run_actual(args)
    except UnknownModel as problem:
        raise SystemExit(f"{problem}: add its published price to pricing.py") from problem


if __name__ == "__main__":
    main()
