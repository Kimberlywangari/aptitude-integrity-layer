"""Everything that decides whether a written question is fit to put in front of a candidate.

All of it is plain code with no model and no database, so each rule is tested with a few strings.
A question that fails any check is thrown away and replaced; nothing here repairs a question,
because a repaired question is one nobody checked.
"""

import ast
import math
import operator
import re
from dataclasses import dataclass, replace

from app.services.qgen.categories import DIFFICULTIES
from app.services.qgen.schema import RawQuestion

OPTION_COUNT = 4
QUESTION_MAX = 1500  # a verbal passage plus its question fits well inside this
QUESTION_MIN = 15
OPTION_MAX = 220
EXPLANATION_MAX = 1200
CALCULATION_MAX = 200
SIMILAR = 0.7  # two questions sharing this much of their wording are the same question

LABELS = "ABCDEFGH"

_LEADING_LABEL = re.compile(r"^\s*(?:\(?[A-Ha-h][\).:]|\([A-Ha-h]\))\s+")
_BANNED_OPTIONS = re.compile(
    r"\b(all|none|neither|both)\s+of\s+(the\s+)?(above|these|them)\b|\bnone\s+of\s+the\s+above\b",
    re.IGNORECASE,
)
_PICTURE = re.compile(
    r"\b(diagram|chart|graph|picture|image|photo|illustration|pictured|fig(?:ure|\.)\s*\d+"
    r"|shown\s+(?:below|above))\b",
    re.IGNORECASE,
)
_MARKUP = re.compile(
    # A bare <b> or <p> is markup, but "a<b and c>d" is an inequality, so one-letter tags count
    # only when nothing sits between the letter and the closing bracket.
    r"</?(?:p|br|b|i|u)\s*/?>|<a\s+href\b[^>]*>"
    r"|</?(?:em|strong|span|div|ul|ol|li|table|tr|td|th|h[1-6]|sup|sub|code|pre)\b[^>]*>"
    r"|\\\(|\\\[|\$\$|\*\*|^#{1,6}\s",
    re.IGNORECASE | re.MULTILINE,
)
_WORD = re.compile(r"[a-z0-9]+")


class Reject(Exception):
    """Why a question was thrown away. The message is for the log and the admin's sample screen."""


def clean(text: str) -> str:
    """Tidy whitespace without touching the line breaks a passage or table needs."""
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.replace("\r", "").split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def strip_labels(options: list[str]) -> list[str]:
    """A model sometimes writes "A) 12" although it was told not to. Labels come off only when every
    option carries one, so a real option that happens to start with a letter is left alone."""
    if options and all(_LEADING_LABEL.match(o) for o in options):
        return [_LEADING_LABEL.sub("", o, count=1).strip() for o in options]
    return options


@dataclass(frozen=True)
class Shaped:
    """A question that has the right form. Not yet known to be right."""

    difficulty: str
    text: str
    options: tuple[str, ...]
    correct_index: int
    explanation: str
    calculation: str


def shape(raw: RawQuestion, fallback_difficulty: str) -> Shaped:
    """Tidy a raw question and refuse it if its form is wrong."""
    text = clean(raw.question)
    options = tuple(strip_labels([clean(o) for o in raw.options]))
    difficulty = raw.difficulty.strip().lower()
    if difficulty not in DIFFICULTIES:
        difficulty = fallback_difficulty

    if not QUESTION_MIN <= len(text) <= QUESTION_MAX:
        raise Reject("the question is empty, too short or too long")
    if len(options) != OPTION_COUNT:
        raise Reject(f"expected {OPTION_COUNT} options, got {len(options)}")
    if any(not o or len(o) > OPTION_MAX for o in options):
        raise Reject("an option is empty or too long")
    if len({o.casefold() for o in options}) != OPTION_COUNT:
        raise Reject("two options are the same")
    if not 0 <= raw.correct_index < OPTION_COUNT:
        raise Reject("the marked answer is not one of the options")
    if any(_BANNED_OPTIONS.search(o) for o in options):
        raise Reject("an option says 'all/none of the above', which a shuffle would break")
    if _PICTURE.search(text):
        raise Reject("the question refers to a picture the candidate cannot see")
    if _MARKUP.search(text) or any(_MARKUP.search(o) for o in options):
        raise Reject("the text carries markup; plain text only")
    return Shaped(
        difficulty=difficulty,
        text=text,
        options=options,
        correct_index=raw.correct_index,
        explanation=clean(raw.explanation)[:EXPLANATION_MAX],
        calculation=raw.calculation.strip()[:CALCULATION_MAX],
    )


# ----------------------------------------------------------------------------- not a repeat


def words(text: str) -> frozenset[str]:
    return frozenset(_WORD.findall(text.casefold()))


def similarity(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_repeat(text: str, others: list[frozenset[str]]) -> bool:
    mine = words(text)
    return any(similarity(mine, other) >= SIMILAR for other in others)


# ------------------------------------------------------------------- arithmetic on the working

_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_MAX_POWER = 12
_MAX_NODES = 60


def evaluate(expression: str) -> float:
    """The value of an arithmetic expression: numbers, + - * / // % ** and brackets, nothing else.

    No names, no calls, no attributes: the text came from a model, so it is treated as untrusted.
    """
    cleaned = (
        expression.replace("×", "*").replace("÷", "/").replace("−", "-").replace("^", "**")
    ).strip()
    cleaned = cleaned.rstrip("=").strip()
    if not cleaned or len(cleaned) > CALCULATION_MAX:
        raise ValueError("no expression")
    try:
        tree = ast.parse(cleaned, mode="eval")
    except SyntaxError as problem:
        raise ValueError("not an expression") from problem
    if sum(1 for _ in ast.walk(tree)) > _MAX_NODES:
        raise ValueError("too long")

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = walk(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POWER:
                raise ValueError("power too large")
            return _OPERATORS[type(node.op)](left, right)
        raise ValueError("only arithmetic is allowed")

    try:
        value = walk(tree)
    except (ZeroDivisionError, OverflowError) as problem:
        raise ValueError("cannot be calculated") from problem
    if not math.isfinite(value):
        raise ValueError("cannot be calculated")
    return value


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_FRACTION = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*$")


def number_in(option: str) -> float | None:
    """The one number an option states, or None when it states none or several (a time such as
    '3 hours 20 minutes', a ratio '5:3'), where arithmetic cannot say if it matches."""
    text = re.sub(r"(?<=\d)[,\s](?=\d{3}\b)", "", option.replace(" ", " "))
    fraction = _FRACTION.match(text)
    if fraction:
        return float(fraction.group(1)) / float(fraction.group(2))
    found = _NUMBER.findall(text)
    if len(found) != 1:
        return None
    return float(found[0])


def same_number(a: float, b: float) -> bool:
    """Equal to the precision an option would be written to: a percent or a price rounded to one
    or two places still matches the exact result."""
    return math.isclose(a, b, rel_tol=0.006, abs_tol=0.006)


def key_from_calculation(question: Shaped) -> Shaped:
    """Settle a numerical question's key by arithmetic, not by the writer's say-so.

    A model that has worked an answer out correctly still often points `correct_index` at the wrong
    option, so the key is the one option whose number is the result of the calculation. The question
    is refused if the calculation cannot be worked out, if no option is that number, or if more than
    one is. When the options are not plain numbers (a time, a ratio) there is nothing to compare
    and the writer's key is left for the solving passes to confirm.
    """
    if not question.calculation:
        raise Reject("no calculation was given")
    try:
        value = evaluate(question.calculation)
    except ValueError as problem:
        raise Reject("the calculation could not be evaluated") from problem
    numbers = [number_in(o) for o in question.options]
    if any(n is None for n in numbers):
        return question
    hits = [i for i, n in enumerate(numbers) if n is not None and same_number(value, n)]
    if not hits:
        raise Reject("no option is the result of the calculation")
    if len(hits) > 1:
        raise Reject("more than one option is the result of the calculation")
    note = f"Calculation: {question.calculation} = {value:.10g}."
    return replace(
        question, correct_index=hits[0], explanation=f"{question.explanation} {note}".strip()
    )
