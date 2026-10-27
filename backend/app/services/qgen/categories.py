"""The seven kinds of question a sitting can ask for, and what each one is.

The keys are Cytonn's section names in lower case, exactly as the question bank stores them, so a
sitting's blueprint reads the same whether its questions come from the bank or from the writer.
`brief` is what the writer is told the kind of question is; it is the only place that lives.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    brief: str
    numeric: bool = False  # the options are numbers, so the working can be checked by arithmetic
    # How to build this kind of question so that exactly one option is right; told to the writer
    # after the brief. Empty when the brief is enough.
    rule: str = ""


CATEGORIES: dict[str, Category] = {
    c.key: c
    for c in (
        Category(
            "numerical",
            "Numerical",
            "Arithmetic and quantitative reasoning: percentages, ratios, averages, simple and "
            "compound interest, rates and speed, profit and loss, currency amounts in Kenya "
            "shillings (KES), and figures read from a short table written into the question. "
            "One to four steps of working. Every option is a single number (with its unit if it "
            "has one), and the question says how to round if rounding matters.",
            numeric=True,
        ),
        Category(
            "verbal",
            "Verbal",
            "Language and reading: a short passage of 60 to 120 words followed by a question about "
            "it (main idea, what is implied, what the author would agree with), or vocabulary in "
            "context, sentence completion, grammar and usage, analogies.",
        ),
        Category(
            "logical",
            "Logical",
            "Deductive and inductive reasoning: number and letter series, syllogisms, ordering or "
            "seating puzzles with three to five people, if-then statements, odd one out, "
            "coding and decoding. Everything needed is in the question.",
        ),
        Category(
            "critical thinking",
            "Critical Thinking",
            "Judging arguments: given a short paragraph from a workplace or business setting, find "
            "the assumption it depends on, the statement that would most weaken or strengthen it, "
            "the flaw in its reasoning, or the conclusion the evidence actually supports.",
        ),
        Category(
            "error checking",
            "Error Checking",
            "Spotting mistakes: a short text, a list of figures, or a calculation shown step by "
            "step, in which exactly one error is hidden (a spelling or grammar slip, a figure that "
            "does not match its total, a date out of order, a wrong step). The question asks where "
            "the error is or which corrected version is right.",
            # Live on 27 Oct 2026 the solver often disagreed with the key here, because a hidden
            # error that spreads into later lines leaves more than one defensible answer.
            rule="Build it backwards: first write the correct text, list or working in "
            "`explanation`, then change exactly one thing in it. Number the lines or steps "
            "(Line 1, Step 2) so the options can name them. Every other line must be right on its "
            "own terms, and in a calculation each later step must follow correctly from the line "
            "above it, even if that line is the wrong one, so that checking the lines in order "
            "finds one first error and no other. When a figure is the error, show the sum or total "
            "it should match in the text. The error must be provable by arithmetic, spelling or a "
            "date in the text, never a matter of opinion or style.",
        ),
        Category(
            "ai competence",
            "AI Competence",
            "Practical understanding of AI tools at work: what a prompt is, why AI output must be "
            "checked (made-up facts), keeping confidential data out of a public tool, bias, "
            "choosing the right tool for a task, writing a clearer instruction. Scenario based; no "
            "mathematics and no programming.",
        ),
        Category(
            "office assistant",
            "Office Assistant",
            "Everyday office skills: spreadsheet formulas and functions (SUM, IF, COUNTIF, "
            "VLOOKUP), formatting, keyboard shortcuts, mail merge, email etiquette, scheduling, "
            "filing and calendar invitations. Scenario based, with the formula or steps written "
            "out in the question.",
        ),
    )
}

# What a paper's difficulty mix is, as a share of each category. Fixed, not chosen per sitting.
MIX = (("easy", 0.3), ("medium", 0.4), ("hard", 0.3))
DIFFICULTIES = tuple(name for name, _ in MIX)

# Hard limits that keep one sitting sane. Per category and in total.
MAX_PER_CATEGORY = 30
MAX_TOTAL = 100


def difficulty_plan(count: int) -> list[str]:
    """How many of each difficulty a category of `count` questions asks for, easiest first."""
    easy = round(count * MIX[0][1])
    hard = round(count * MIX[2][1])
    medium = count - easy - hard
    return ["easy"] * easy + ["medium"] * medium + ["hard"] * hard
