"""Benchmark local Ollama models on evidence packets: speed, valid JSON, fact check, ordering.

Run from the repo root, naming the models to compare:

    backend\\.venv\\Scripts\\python.exe -m eval.metrics.ai_benchmark qwen3.5:4b granite4:3b

Raw results go to data/ai_benchmark/results.json (git-ignored). This is the D11 step 7 harness in
early form: the packets are hand-built stand-ins and the fact check is a light version of the one
D12 builds, so the numbers are a guide, not the final choice.
"""

import argparse
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

import httpx

from eval.fixtures.synthetic_packets import PACKETS

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidate_id": {"type": "string"},
        "flags_support_each_other": {"type": "string", "enum": ["yes", "partly", "no"]},
        "innocent_explanation": {
            "type": "object",
            "properties": {
                "present": {"type": "boolean"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["present", "evidence_ids"],
        },
        "strength": {"type": "integer", "minimum": 1, "maximum": 5},
        "explanation": {"type": "string"},
        "cited": {
            "type": "object",
            "properties": {
                "flag_ids": {"type": "array", "items": {"type": "string"}},
                "question_numbers": {"type": "array", "items": {"type": "integer"}},
                "times_s": {"type": "array", "items": {"type": "integer"}},
                "counts": {"type": "object", "additionalProperties": {"type": "integer"}},
            },
            "required": ["flag_ids", "question_numbers", "times_s", "counts"],
        },
    },
    "required": [
        "candidate_id",
        "flags_support_each_other",
        "innocent_explanation",
        "strength",
        "explanation",
        "cited",
    ],
}

SYSTEM_PROMPTS = {
    # The D11 step 5 wording, as first specified.
    "v1": (
        "You are helping a human reviewer. You only rank and explain; you never give a verdict, "
        "never say anyone cheated, never recommend rejecting or disqualifying. Use only facts in "
        "the packet and cite flag IDs. Mention an innocent explanation if the packet has one. "
        "Answer with the JSON schema only; explanation at most 80 words."
    ),
    # v1 plus an explicit word ban, a strength scale taken from the proposal and master plan, and
    # a rule against guessing at reasons or methods.
    "v2": (
        "You are helping a human reviewer. You only rank and explain. You never give a verdict "
        "and never recommend rejecting or disqualifying anyone.\n"
        "Never use the words cheat, cheating, cheated, guilty, dishonest, fraud, misconduct, "
        "disqualify or reject, not even to deny them. Describe behaviour instead, for example "
        "'a copy attempt on Q11' or 'a 212 s hold on Q22'.\n"
        "Say only what the flags show. Do not guess at reasons or methods (no 'answer key', "
        "'external material', 'automated' or similar). Use only numbers that appear in the "
        "packet, and use each number for what it is: score is a score, not a count of "
        "questions.\n"
        "Cite flag IDs (F1, F2, ...) and innocent signal IDs (I1, M1, ...). If the packet has an "
        "innocent signal that could explain the flags, say so and set innocent_explanation.\n"
        "Strength scale: 5 = several different kinds of flag close together in time with nothing "
        "innocent explaining them; 4 = several flags that support each other, little innocent "
        "explanation; 3 = two flags, or flags that are far apart or partly explained; 2 = one "
        "flag, or flags that an innocent signal explains; 1 = nothing beyond routine context. "
        "A cohort-only outlier (PACE_OUTLIER or SPREAD_OUTLIER on its own) is context and is "
        "never above 2. A high score or a fast pace is not evidence on its own.\n"
        "Answer with the JSON schema only; explanation at most 80 words."
    ),
}

VERDICT_WORDS = re.compile(r"cheat|guilty|disqualif|reject|fraud|dishonest|misconduct", re.I)
ID_TOKEN = re.compile(r"\b[FIM]\d+\b")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
MAX_WORDS = 80
TARGET_SECONDS = 120
OPTIONS = {"temperature": 0, "num_ctx": 4096, "seed": 7}


def build_messages(packet: dict[str, Any], prompt: str = "v1") -> list[dict[str, str]]:
    user = "Evidence packet:\n" + json.dumps(packet) + "\n\nSchema:\n" + json.dumps(SCHEMA)
    return [
        {"role": "system", "content": SYSTEM_PROMPTS[prompt]},
        {"role": "user", "content": user},
    ]


def _numbers_in(value: Any) -> set[str]:
    """Every number in the packet as a string, so floats like -3.4 can be matched too."""
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, (int, float)):
        return {str(abs(value))}
    if isinstance(value, dict):
        return set().union(*(_numbers_in(v) for v in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_numbers_in(v) for v in value), set())
    return set()


def check_assessment(packet: dict[str, Any], content: str) -> tuple[dict | None, list[str]]:
    """Return the parsed assessment (or None) and the list of violations."""
    try:
        assessment = json.loads(content)
    except json.JSONDecodeError:
        return None, ["not_json"]
    if not isinstance(assessment, dict):
        return None, ["not_json"]
    problems: list[str] = []
    facts = packet["facts"]
    try:
        if assessment["candidate_id"] != packet["candidate_id"]:
            problems.append("wrong_candidate_id")
        strength = assessment["strength"]
        if not isinstance(strength, int) or not 1 <= strength <= 5:
            problems.append("strength_out_of_range")
        if assessment["flags_support_each_other"] not in {"yes", "partly", "no"}:
            problems.append("bad_support_value")
        explanation = str(assessment["explanation"])
        if len(explanation.split()) > MAX_WORDS:
            problems.append("explanation_too_long")
        if VERDICT_WORDS.search(explanation):
            problems.append("verdict_word")

        cited = assessment["cited"]
        flag_ids = {f["id"] for f in packet["flags"]}
        evidence_ids = {s["id"] for s in packet["innocent_signals"] + packet["mic_silence"]}
        if not set(cited["flag_ids"]) <= flag_ids:
            problems.append("unknown_flag_id")
        if not set(assessment["innocent_explanation"]["evidence_ids"]) <= evidence_ids:
            problems.append("unknown_evidence_id")
        if not set(cited["question_numbers"]) <= set(facts["question_numbers"]):
            problems.append("unknown_question_number")
        if not set(cited["times_s"]) <= set(facts["times_s"]):
            problems.append("unknown_time")
        if any(facts["counts"].get(k) != v for k, v in cited["counts"].items()):
            problems.append("count_mismatch")

        allowed = (
            {str(n) for n in facts["question_numbers"]}
            | {str(n) for n in facts["times_s"]}
            | {str(n) for n in facts["counts"].values()}
            | _numbers_in(packet["flags"])
        )
        text = explanation.replace(packet["candidate_id"], " ")
        text = ID_TOKEN.sub(" ", text)
        if any(n not in allowed for n in NUMBER.findall(text)):
            problems.append("number_not_in_facts")
    except (KeyError, TypeError):
        return assessment, [*problems, "schema_violation"]
    return assessment, problems


def call_ollama(
    client: httpx.Client, model: str, packet: dict[str, Any], prompt: str = "v1"
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": build_messages(packet, prompt),
        "stream": False,
        "format": SCHEMA,
        "think": False,
        "options": OPTIONS,
        "keep_alive": "10m",
    }
    response = client.post("/api/chat", json=body)
    if response.status_code == 400 and "think" in response.text.lower():
        body.pop("think")  # a model with no thinking mode may reject the switch
        response = client.post("/api/chat", json=body)
    response.raise_for_status()
    return response.json()


def _per_second(count: int, duration_ns: int | None) -> float:
    return round(count / max((duration_ns or 0) / 1e9, 1e-9), 1)


def unload(client: httpx.Client, model: str) -> None:
    try:
        client.post("/api/generate", json={"model": model, "keep_alive": 0})
    except httpx.HTTPError:
        pass


def run_model(
    client: httpx.Client, model: str, entries: list[dict[str, Any]], prompt: str = "v1"
) -> list[dict]:
    rows: list[dict[str, Any]] = []
    for entry in entries:
        packet = entry["packet"]
        row: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "packet": entry["id"],
            "band": entry["band"],
        }
        try:
            out = call_ollama(client, model, packet, prompt)
        except httpx.HTTPError as exc:
            row.update(error=f"{type(exc).__name__}: {exc}"[:200], violations=["request_failed"])
            rows.append(row)
            print(f"  {entry['id']:<3} ERROR {row['error']}", flush=True)
            continue
        ns = 1e9
        warm = (out["total_duration"] - out.get("load_duration", 0)) / ns
        assessment, violations = check_assessment(packet, out["message"]["content"])
        row.update(
            seconds=round(warm, 1),
            load_s=round(out.get("load_duration", 0) / ns, 1),
            prompt_tokens=(prompt_n := out.get("prompt_eval_count", 0)),
            prompt_tok_s=_per_second(prompt_n, out.get("prompt_eval_duration")),
            gen_tokens=(gen_n := out.get("eval_count", 0)),
            gen_tok_s=_per_second(gen_n, out.get("eval_duration")),
            violations=violations,
            strength=assessment.get("strength") if assessment else None,
            support=assessment.get("flags_support_each_other") if assessment else None,
            explanation=assessment.get("explanation") if assessment else None,
            raw=None if assessment else out["message"]["content"][:500],
        )
        rows.append(row)
        flags = ",".join(violations) or "ok"
        print(
            f"  {entry['id']:<3} {warm:6.1f}s  strength={row['strength']}  "
            f"support={row['support']}  {flags}",
            flush=True,
        )
    unload(client, model)
    return rows


def ordering_accuracy(rows: list[dict[str, Any]]) -> float | None:
    """Share of (strong, weak) pairs where the strong packet got the higher strength."""
    scored = [r for r in rows if r.get("strength") is not None]
    strong = [r["strength"] for r in scored if r["band"] == "strong"]
    weak = [r["strength"] for r in scored if r["band"] == "weak"]
    if not strong or not weak:
        return None
    points = [1.0 if s > w else 0.5 if s == w else 0.0 for s in strong for w in weak]
    return sum(points) / len(points)


def band_mean(rows: list[dict[str, Any]], band: str) -> str:
    values = [r["strength"] for r in rows if r["band"] == band and r.get("strength") is not None]
    return f"{statistics.mean(values):.1f}" if values else "-"


def summarise(results: dict[str, list[dict[str, Any]]]) -> None:
    header = (
        f"{'model':<18}{'n':>3}{'json':>6}{'facts':>7}{'verdict':>8}{'med s':>7}{'max s':>7}"
        f"{'>120s':>6}{'read t/s':>9}{'write t/s':>10}{'order':>7}{'S/M/W':>13}"
    )
    print("\n" + header)
    for model, rows in results.items():
        n = len(rows)
        answered = [r for r in rows if "seconds" in r]
        parsed = [r for r in answered if "not_json" not in r["violations"]]
        clean = [r for r in answered if not r["violations"]]
        verdicts = sum("verdict_word" in r["violations"] for r in rows)
        secs = [r["seconds"] for r in answered]
        over = sum(s > TARGET_SECONDS for s in secs)
        order = ordering_accuracy(rows)
        read = statistics.median(r["prompt_tok_s"] for r in answered) if answered else 0
        write = statistics.median(r["gen_tok_s"] for r in answered) if answered else 0
        bands = "/".join(band_mean(rows, b) for b in ("strong", "medium", "weak"))
        print(
            f"{model:<18}{n:>3}{len(parsed):>6}{len(clean):>7}{verdicts:>8}"
            f"{statistics.median(secs) if secs else 0:>7.1f}{max(secs, default=0):>7.1f}"
            f"{over:>6}{read:>9.0f}{write:>10.1f}"
            f"{(f'{order:.2f}' if order is not None else '-'):>7}{bands:>13}"
        )
    print(
        "\njson = parsed as JSON; facts = JSON that also passes every check; order = share of "
        "strong-vs-weak pairs ranked the right way (1.00 best, 0.50 chance); S/M/W = mean "
        "strength for strong, medium, weak packets."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("models", nargs="+", help="Ollama model tags, e.g. qwen3.5:4b")
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--timeout", type=float, default=300, help="seconds per request")
    parser.add_argument("--prompt", choices=sorted(SYSTEM_PROMPTS), default="v1")
    parser.add_argument("--limit", type=int, default=0, help="only the first N packets")
    parser.add_argument("--out", default="data/ai_benchmark/results.json")
    args = parser.parse_args()

    entries = PACKETS[: args.limit] if args.limit else PACKETS
    results: dict[str, list[dict[str, Any]]] = {}
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        for model in args.models:
            print(f"{model} (prompt {args.prompt})", flush=True)
            results[model] = run_model(client, model, entries, args.prompt)
            out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    summarise(results)
    print(f"\nraw results: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
