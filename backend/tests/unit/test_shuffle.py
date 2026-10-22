from collections import Counter

import pytest

from app.services.shuffle import (
    balanced_sample,
    most_asked_of_a_section,
    session_rng,
    shuffle_options,
)

BANK = {
    "numerical": [f"N{i:02d}" for i in range(20)],
    "verbal": [f"V{i:02d}" for i in range(20)],
    "logical": [f"L{i:02d}" for i in range(20)],
}


def sections_of(ids):
    return Counter(i[0] for i in ids)


def test_twelve_over_three_sections_is_four_each_and_no_repeats():
    picked = balanced_sample(session_rng("s1", "paper"), BANK, 12)
    assert len(picked) == len(set(picked)) == 12
    assert sections_of(picked) == {"N": 4, "V": 4, "L": 4}


def test_same_session_same_paper_and_other_session_differs():
    a = balanced_sample(session_rng("s1", "paper"), BANK, 12)
    again = balanced_sample(session_rng("s1", "paper"), BANK, 12)
    other = balanced_sample(session_rng("s2", "paper"), BANK, 12)
    assert a == again
    assert a != other


def test_uneven_count_spreads_the_remainder_by_at_most_one():
    picked = balanced_sample(session_rng("s1", "paper"), BANK, 10)
    counts = sections_of(picked).values()
    assert sum(counts) == 10
    assert max(counts) - min(counts) == 1


def test_sections_stay_grouped_in_name_order():
    picked = balanced_sample(session_rng("s1", "paper"), BANK, 12)
    assert [i[0] for i in picked] == ["L"] * 4 + ["N"] * 4 + ["V"] * 4


def test_too_few_questions_in_a_section_is_an_error():
    small = {"a": ["A1"], "b": ["B1", "B2", "B3"]}
    with pytest.raises(ValueError):
        balanced_sample(session_rng("s", "paper"), small, 6)


def test_option_shuffle_is_a_stable_permutation_per_position():
    ids = [11, 12, 13, 14]
    first = shuffle_options("s1", 3, ids)
    assert sorted(first) == ids
    assert first == shuffle_options("s1", 3, ids)
    orders = {tuple(shuffle_options(f"session-{n}", 1, ids)) for n in range(30)}
    assert len(orders) > 1  # different sessions do get different orders


@pytest.mark.parametrize(
    ("count", "sections", "most"), [(12, 3, 4), (13, 3, 5), (14, 3, 5), (10, 1, 10), (1, 3, 1)]
)
def test_the_most_asked_of_a_section_is_the_rounded_up_share(count, sections, most):
    assert most_asked_of_a_section(count, sections) == most


@pytest.mark.parametrize("count", [5, 7, 13, 14])
def test_sections_of_exactly_that_size_always_make_a_paper(count):
    need = most_asked_of_a_section(count, 3)
    bank = {name: [f"{name}{i}" for i in range(need)] for name in ("a", "b", "c")}
    for seed in range(60):
        assert len(balanced_sample(session_rng(f"s{seed}", "paper"), bank, count)) == count
