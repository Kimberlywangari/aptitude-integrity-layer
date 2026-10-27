"""What the writer and the solver are told. The only place the wording lives.

The writer is asked for several questions at once because that is cheaper and varies them; the
solver is shown the finished questions with the answer left out. Neither is told what the other
said, so the solver is an independent check and not an echo.
"""

from typing import Any

from app.services.qgen.categories import Category
from app.services.qgen.check import LABELS, OPTION_COUNT
from app.services.qgen.schema import RawBatch, SolvedBatch

WRITE_RULES = f"""You write multiple-choice questions for a graduate aptitude test used by a \
financial firm in Nairobi. Candidates are recent graduates.

Rules for every question:
- Exactly {OPTION_COUNT} options and exactly one correct option. `correct_index` is the position \
of the correct option in `options`, counting from 0.
- The correct answer must be certain. A careful person working it out must reach the same answer \
you marked, and no other option may also be defensible. Check your own working before you answer.
- Plain text only: no markdown, no HTML, no LaTeX. Write powers as 2^3 and fractions as 3/4.
- Everything needed is in the question text. Never refer to a picture, chart, graph or diagram. If \
data is needed, put it in the text as a few short lines.
- Do not put letters or numbers in front of the options. Do not use "all of the above", "none of \
the above" or "both of these".
- Wrong options must be plausible mistakes, similar in length and style to the right one.
- Do not need a calculator for anything beyond simple arithmetic. Do not rely on knowledge of a \
particular country's law, history or current events.
- `explanation` is the short working that shows why the marked option is right (one to three \
sentences). Candidates never see it. Fill the fields in the order shown below: work the answer out \
in `explanation` first, and only then write the options, so that the correct option is exactly the \
result of your working.
- Make each question different in setting and wording from every other question.

Difficulty: easy is one step. medium is two or three steps, or has a tempting wrong option. hard \
has several steps or a trap that careless reading falls into, and is still fair and has one answer.

Reply with JSON only, in this shape:
{{"questions": [{{"difficulty": "easy", "question": "...", "calculation": "", \
"explanation": "...", "options": ["...", "...", "...", "..."], "correct_index": 2}}]}}"""

NUMERIC_RULE = """
This is a numerical category, so also fill `calculation` for every question, before the options: \
one arithmetic expression for the answer to the question. Use only digits, + - * / ^ and \
brackets, with no words, units, percent signs or commas (write 15% of 2400 as 0.15*2400). A \
computer works it \
out, and exactly one of your options must be that number, so write that option from the result of \
the expression and make the other three options clearly different numbers."""

SOLVE_RULES = f"""You are taking an aptitude test. For each question, work out the answer and \
choose the single best option, labelled {", ".join(LABELS[:OPTION_COUNT])}. Do not assume that any \
letter is more likely than another.

Reply with JSON only, in this shape:
{{"answers": [{{"n": 1, "working": "one or two sentences", "letter": "B"}}]}}
Give one entry for every question, using the question's number. Keep every `working` under 40 \
words, in plain text without double quotes, and always finish the JSON: an answer that stops \
part-way is thrown away."""


def write_messages(
    category: Category, count: int, difficulties: list[str], avoid: list[str]
) -> list[dict[str, str]]:
    system = WRITE_RULES + (NUMERIC_RULE if category.numeric else "")
    lines = [
        f'Write {count} question{"" if count == 1 else "s"} for the category "{category.label}".',
        f"What this category is: {category.brief}",
    ]
    if category.rule:
        lines.append(f"How to build this kind of question: {category.rule}")
    lines.append("Difficulty of each question, in order: " + ", ".join(difficulties) + ".")
    if avoid:
        lines.append(
            "Questions already on this paper. Do not repeat or closely resemble any of them:"
        )
        lines += [f"- {text[:160]}" for text in avoid[-12:]]
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(lines)},
    ]


def solve_messages(items: list[tuple[str, list[str]]]) -> list[dict[str, str]]:
    blocks = []
    for number, (text, options) in enumerate(items, start=1):
        shown = "\n".join(f"{LABELS[i]}. {option}" for i, option in enumerate(options))
        blocks.append(f"Question {number}\n{text}\n{shown}")
    return [
        {"role": "system", "content": SOLVE_RULES},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]


def write_schema() -> dict[str, Any]:
    return RawBatch.model_json_schema()


def solve_schema() -> dict[str, Any]:
    return SolvedBatch.model_json_schema()
