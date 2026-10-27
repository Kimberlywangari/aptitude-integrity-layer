"""What the writer and the solver are told, for each of the seven categories. No model is called."""

import pytest

from app.services.qgen import prompts
from app.services.qgen.categories import CATEGORIES

EVERY_CATEGORY = list(CATEGORIES.values())


@pytest.mark.parametrize("category", EVERY_CATEGORY, ids=lambda c: c.key)
def test_each_category_is_asked_for_by_name_with_its_brief_and_difficulties(category):
    system, user = [
        m["content"] for m in prompts.write_messages(category, 2, ["easy", "hard"], [])
    ]

    assert f'category "{category.label}"' in user
    assert category.brief in user
    assert "easy, hard" in user
    assert "Reply with JSON only" in system


@pytest.mark.parametrize("category", EVERY_CATEGORY, ids=lambda c: c.key)
def test_only_a_numerical_category_is_told_to_give_a_calculation(category):
    system = prompts.write_messages(category, 1, ["easy"], [])[0]["content"]
    assert ("fill `calculation`" in system) is category.numeric


@pytest.mark.parametrize("category", EVERY_CATEGORY, ids=lambda c: c.key)
def test_a_categorys_build_rule_is_told_to_the_writer_exactly_when_it_has_one(category):
    user = prompts.write_messages(category, 1, ["easy"], [])[1]["content"]
    assert ("How to build this kind of question" in user) is bool(category.rule)
    if category.rule:
        assert category.rule in user


def test_error_checking_is_told_to_hide_one_error_that_does_not_spread():
    """Live, the solver disagreed with the key on these more than on any other kind, because an
    error that carries into later lines leaves more than one defensible answer."""
    rule = CATEGORIES["error checking"].rule
    assert "exactly one thing" in rule
    assert "each later step must follow correctly from the line above it" in rule
    assert "never a matter of opinion" in rule


def test_questions_already_on_the_paper_are_listed_so_they_are_not_repeated():
    user = prompts.write_messages(CATEGORIES["verbal"], 1, ["easy"], ["an earlier question"])[1][
        "content"
    ]
    assert "Do not repeat or closely resemble" in user and "- an earlier question" in user


def test_the_solver_is_told_to_keep_its_working_short_and_to_finish_the_json():
    """Live, an answer cut off in a long `working` note made the whole round unusable."""
    system = prompts.solve_messages([("What is 2 + 2?", ["3", "4", "5", "6"])])[0]["content"]
    assert "under 40 words" in system and "without double quotes" in system
    assert "always finish the JSON" in system
