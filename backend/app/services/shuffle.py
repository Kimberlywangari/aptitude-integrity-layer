"""Seeded randomness for a candidate's paper.

Everything is seeded from the session ID, so the same session always gets the same questions
and option order (a reload or a rebuilt paper never reshuffles), and two sessions differ.
"""

import random
from collections.abc import Mapping, Sequence

# Questions that hang off one reading passage carry its text each, so a paper that took many of
# them would have the candidate read the same passage again and again.
MAX_PER_PASSAGE = 2


def session_rng(session_id: str, purpose: str) -> random.Random:
    # A str seed is hashed with SHA-512 by random.Random, so this is stable across processes.
    return random.Random(f"{purpose}:{session_id}")


def shuffle_options(session_id: str, position: int, option_ids: Sequence[int]) -> list[int]:
    """Option order for one question of one session."""
    order = list(option_ids)
    session_rng(session_id, f"options:{position}").shuffle(order)
    return order


def most_asked_of_a_section(count: int, section_count: int) -> int:
    """The most questions `balanced_sample` can ask of any one section: it gives each section
    count // sections and a random few of them one more, so any section may be asked the rounded-up
    share. A section holding fewer than this can fail a candidate's start."""
    return -(-count // section_count)


def draw(
    rng: random.Random,
    pool: Sequence[str],
    wanted: int,
    passages: Mapping[str, str] | None = None,
) -> list[str]:
    """`wanted` IDs from `pool`, in random order. With `passages` (question ID to passage key),
    no more than MAX_PER_PASSAGE come from one passage unless the pool leaves no other way to
    fill the paper, so a section made mostly of one passage still gets its questions."""
    if not passages:
        return rng.sample(sorted(pool), wanted)
    order = sorted(pool)
    rng.shuffle(order)
    picked: list[str] = []
    used: dict[str, int] = {}
    for question_id in order:
        key = passages.get(question_id)
        if key is not None and used.get(key, 0) >= MAX_PER_PASSAGE:
            continue
        picked.append(question_id)
        if key is not None:
            used[key] = used.get(key, 0) + 1
        if len(picked) == wanted:
            return picked
    chosen = set(picked)
    picked += [q for q in order if q not in chosen][: wanted - len(picked)]
    return picked


def balanced_sample(
    rng: random.Random,
    by_section: Mapping[str, Sequence[str]],
    count: int,
    passages: Mapping[str, str] | None = None,
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
        picked.extend(draw(rng, pool, wanted, passages))
    return picked


def blueprint_sample(
    rng: random.Random,
    by_section: Mapping[str, Sequence[str]],
    blueprint: Mapping[str, int],
    passages: Mapping[str, str] | None = None,
) -> list[str]:
    """Pick exactly the number of question IDs the blueprint asks of each section.

    Sections stay grouped (in name order) and the questions inside each are in random order, as in
    `balanced_sample`.
    """
    picked: list[str] = []
    for section in sorted(blueprint):
        wanted = blueprint[section]
        pool = sorted(by_section.get(section, ()))
        if wanted > len(pool):
            raise ValueError(f"section {section!r} has {len(pool)} questions, need {wanted}")
        picked.extend(draw(rng, pool, wanted, passages))
    return picked
