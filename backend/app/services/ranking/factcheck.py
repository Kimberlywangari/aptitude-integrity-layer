"""The fact check: the AI can never put a wrong fact in front of a reviewer.

A pure function over an assessment and the packet it was given. Every claim in the assessment must
be something the packet contains: ids, question numbers, times, counts, and every number written in
the explanation. Words that pass a verdict are refused outright. Each violation says which rule
failed and what value was not in the packet, so it can be fed back to the model on the retry.
"""

import re
from dataclasses import dataclass
from typing import Any

from app.services.ranking.base import Assessment

VERDICT_WORDS = re.compile(r"cheat|guilty|disqualif|reject|fraud|dishonest|misconduct", re.I)
ID_TOKEN = re.compile(r"\b[FIM]\d+\b")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
QUESTION_REF = re.compile(r"\bQ(\d+)\b|\bquestions?\s+(\d+)\b", re.I)


@dataclass(frozen=True)
class Violation:
    rule: str
    value: str

    def __str__(self) -> str:
        return f"{self.rule}: {self.value}"


def _numbers_in(value: Any) -> set[str]:
    """Every number in a structure, as text, so a decimal such as 3.4 can be matched too."""
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, int | float):
        return {str(abs(value))}
    if isinstance(value, dict):
        return set().union(*(_numbers_in(v) for v in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_numbers_in(v) for v in value), set())
    return set()


def fact_check(assessment: Assessment, packet: dict[str, Any]) -> list[Violation]:
    facts = packet["facts"]
    problems: list[Violation] = []

    if assessment.candidate_id != packet["candidate_id"]:
        problems.append(Violation("wrong_candidate_id", assessment.candidate_id))

    flag_ids = {f["id"] for f in packet["flags"]}
    evidence_ids = {s["id"] for s in packet["innocent_signals"] + packet["mic_silence"]}
    question_numbers = set(facts["question_numbers"])
    cited = assessment.cited

    for flag_id in cited.flag_ids:
        if flag_id not in flag_ids:
            problems.append(Violation("unknown_flag_id", flag_id))
    for evidence_id in assessment.innocent_explanation.evidence_ids:
        if evidence_id not in evidence_ids:
            problems.append(Violation("unknown_evidence_id", evidence_id))
    for number in cited.question_numbers:
        if number not in question_numbers:
            problems.append(Violation("unknown_question_number", str(number)))
    for seconds in cited.times_s:
        if seconds not in set(facts["times_s"]):
            problems.append(Violation("unknown_time", str(seconds)))
    for key, value in cited.counts.items():
        if facts["counts"].get(key) != value:
            problems.append(Violation("count_mismatch", f"{key}={value}"))

    text = assessment.explanation
    if VERDICT_WORDS.search(text):
        problems.append(Violation("verdict_word", VERDICT_WORDS.search(text).group(0)))

    for match in QUESTION_REF.finditer(text):
        number = int(match.group(1) or match.group(2))
        if number not in question_numbers:
            problems.append(Violation("unknown_question_reference", f"Q{number}"))

    allowed = (
        {str(n) for n in facts["question_numbers"]}
        | {str(n) for n in facts["times_s"]}
        | {str(n) for n in facts["counts"].values()}
        | _numbers_in(packet["flags"])
    )
    cleaned = ID_TOKEN.sub(" ", text.replace(packet["candidate_id"], " "))
    for number in NUMBER.findall(cleaned):
        if number not in allowed:
            problems.append(Violation("number_not_in_facts", number))

    return _unique(problems)


def _unique(problems: list[Violation]) -> list[Violation]:
    seen: set[Violation] = set()
    out = []
    for problem in problems:
        if problem not in seen:
            seen.add(problem)
            out.append(problem)
    return out
