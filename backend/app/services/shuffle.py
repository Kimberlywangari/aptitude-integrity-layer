"""Seeded randomness for a candidate's paper.

Everything is seeded from the session ID, so the same session always gets the same questions
and option order (a reload or a rebuilt paper never reshuffles), and two sessions differ.
"""

import random
from collections.abc import Mapping, Sequence


def session_rng(session_id: str, purpose: str) -> random.Random:
    # A str seed is hashed with SHA-512 by random.Random, so this is stable across processes.
    return random.Random(f"{purpose}:{session_id}")


def shuffle_options(session_id: str, position: int, option_ids: Sequence[int]) -> list[int]:
    """Option order for one question of one session."""
    order = list(option_ids)
    session_rng(session_id, f"options:{position}").shuffle(order)
    return order


def balanced_sample(
    rng: random.Random, by_section: Mapping[str, Sequence[str]], count: int
) -> list[str]:
    """Pick `count` question IDs, spread as evenly as possible over the sections.

    Sections stay grouped (in name order) and the questions inside each are in random order.
    When `count` doesn't divide evenly, which sections get the extra question is random.
    """
    sections = sorted(by_section)
    if not sections:
        raise ValueError("no sections to sample from")
    base, extra = divmod(count, len(sections))
    with_extra = set(rng.sample(sections, extra))
    picked: list[str] = []
    for section in sections:
        wanted = base + (1 if section in with_extra else 0)
        pool = sorted(by_section[section])
        if wanted > len(pool):
            raise ValueError(f"section {section!r} has {len(pool)} questions, need {wanted}")
        picked.extend(rng.sample(pool, wanted))
    return picked
