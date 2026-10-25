"""Write a few questions with the configured model and print them, to see what it does before a
sitting depends on it. Nothing is stored and no database is needed.

    python -m scripts.jobs try_question_writer --category numerical [--count 2] [--level medium]

It runs the same pipeline as a candidate's paper, every check included, so what it prints is what a
candidate would be shown, with the marked answer and how long it took. Which model writes is set in
.env (QUESTION_PROVIDER, QUESTION_OLLAMA_MODEL). A slow computer takes about a minute a question.
"""

import argparse
import random
import time

from app.config import get_settings
from app.services.qgen import pipeline
from app.services.qgen.categories import CATEGORIES, DIFFICULTIES
from app.services.qgen.check import LABELS
from app.services.qgen.writers import WriterError, check_available, get_writer


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--category", default="numerical", choices=sorted(CATEGORIES))
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--level", default="medium", choices=DIFFICULTIES)
    args = parser.parse_args(argv)

    settings = get_settings()
    ready, detail = check_available(settings)
    print(detail)
    if not ready:
        raise SystemExit("The writer is not ready, so nothing was written.")

    writer = get_writer(settings)
    report = pipeline.Report()
    started = time.perf_counter()
    shown = 0
    try:
        for batch in pipeline.produce(
            writer,
            CATEGORIES[args.category],
            [args.level] * args.count,
            [],
            random.Random(),
            report,
            settings.question_solves,
        ):
            for item in batch:
                shown += 1
                print(f"\n{shown}. [{item.difficulty}] {item.text}")
                for index, option in enumerate(item.options):
                    mark = "  <- marked correct" if index == item.correct_index else ""
                    print(f"   {LABELS[index]}. {option}{mark}")
                print(f"   working: {item.explanation}")
    except (pipeline.PaperFailed, WriterError) as problem:
        print(f"\nFAILED: {problem}")
    print(
        f"\n{report.accepted} written in {time.perf_counter() - started:.0f} s, "
        f"{report.rounds} round(s), {len(report.rejected)} thrown away"
    )
    for reason in dict.fromkeys(report.rejected):
        print(f"  thrown away: {reason}")


if __name__ == "__main__":
    main()
