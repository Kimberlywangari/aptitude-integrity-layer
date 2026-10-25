"""The checks that decide whether a written question may reach a candidate. Plain strings in, a
verdict out: no model, no database."""

import pytest

from app.services.qgen import check
from app.services.qgen.schema import RawQuestion


def raw(**overrides) -> RawQuestion:
    base = {
        "difficulty": "easy",
        "question": "A shop gives a discount of 12% on a jacket that costs KES 250. What is the "
        "discount in KES?",
        "options": ["20", "30", "25", "35"],
        "correct_index": 1,
        "explanation": "12% of 250 is 0.12 x 250 = 30.",
        "calculation": "0.12*250",
    }
    return RawQuestion(**(base | overrides))


# ------------------------------------------------------------------------------------- shape


def test_a_well_formed_question_passes_untouched():
    item = check.shape(raw(), "medium")
    assert item.options == ("20", "30", "25", "35")
    assert item.correct_index == 1
    assert item.difficulty == "easy"


def test_an_unknown_difficulty_falls_back_to_the_one_asked_for():
    assert check.shape(raw(difficulty="tricky"), "hard").difficulty == "hard"
    assert check.shape(raw(difficulty=" HARD "), "easy").difficulty == "hard"


def test_labels_are_stripped_only_when_every_option_has_one():
    labelled = raw(options=["A) 20", "B) 30", "C) 25", "D) 35"])
    assert check.shape(labelled, "easy").options == ("20", "30", "25", "35")
    # one option that merely starts like a label is a real option, so nothing is touched
    mixed = raw(options=["A. Smith", "Jones", "Brown", "Green"])
    assert check.shape(mixed, "easy").options[0] == "A. Smith"


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"options": ["20", "30", "25"]}, "expected 4 options"),
        ({"options": ["20", "30", "25", "30"]}, "two options are the same"),
        ({"options": ["20", "30", "25", "30 "]}, "two options are the same"),
        ({"options": ["20", "Thirty", "25", ""]}, "empty"),
        ({"correct_index": 4}, "not one of the options"),
        ({"correct_index": -1}, "not one of the options"),
        ({"options": ["20", "30", "25", "None of the above"]}, "all/none of the above"),
        ({"options": ["20", "30", "25", "All of the above"]}, "all/none of the above"),
        ({"question": "Look at the chart below and say which bar is tallest."}, "picture"),
        ({"question": "The diagram shows a triangle. What is its area in square cm?"}, "picture"),
        ({"question": "See Figure 2. What does the curve show about the figures?"}, "picture"),
        ({"question": "What is <b>12%</b> of 250 shillings in total?"}, "markup"),
        ({"question": "**Bold** question about twelve percent of 250"}, "markup"),
        ({"question": "Too short"}, "too short"),
        ({"question": "x" * 1600}, "too long"),
    ],
)
def test_a_badly_formed_question_is_refused(overrides, why):
    with pytest.raises(check.Reject, match="|".join(why.split())) as caught:
        check.shape(raw(**overrides), "easy")
    assert caught.value.args[0]


def test_inequalities_and_the_word_figures_are_not_mistaken_for_markup_or_pictures():
    ok = raw(question="If a<b and c>d, which of the figures given in the report is largest?")
    assert check.shape(ok, "easy")


def test_line_breaks_in_a_table_are_kept_and_other_whitespace_tidied():
    text = "Sales  by   region:\n\nNorth   12\nSouth 15\n\n\nWhich region sold most?"
    assert check.clean(text) == "Sales by region:\n\nNorth 12\nSouth 15\n\nWhich region sold most?"


# ------------------------------------------------------------------------------- not a repeat


def test_a_question_that_shares_most_of_its_wording_is_a_repeat():
    first = "A train travels 120 km in 2 hours. What is its average speed in km per hour?"
    same = "A train travels 150 km in 2 hours. What is its average speed in km per hour?"
    other = "Which statement would most weaken the manager's argument about remote work?"
    seen = [check.words(first)]
    assert check.is_repeat(same, seen) is True
    assert check.is_repeat(other, seen) is False
    assert check.is_repeat(first, []) is False


# ----------------------------------------------------------------------------- arithmetic


@pytest.mark.parametrize(
    ("expression", "value"),
    [
        ("0.12*250", 30.0),
        ("(5000*4*1)/100", 200.0),
        ("2^3", 8.0),
        ("2**3", 8.0),
        ("12 × 5 ÷ 3", 20.0),
        ("100 - 15", 85.0),
        ("-3 + 10", 7.0),
        ("17 % 5", 2.0),
        ("7 // 2", 3.0),
        ("5000*1.04^2 =", 5408.0),
    ],
)
def test_arithmetic_is_evaluated(expression, value):
    assert check.evaluate(expression) == pytest.approx(value)


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "__import__('os').system('echo hi')",
        "open('x')",
        "abs(-3)",
        "x + 1",
        "(1).real",
        "[1, 2]",
        "'a' * 3",
        "9 ** 99",
        "1 / 0",
        "2 +",
        "1 + " * 40 + "1",
        "9" * 250,
    ],
)
def test_anything_but_plain_arithmetic_is_refused(expression):
    with pytest.raises(ValueError):
        check.evaluate(expression)


@pytest.mark.parametrize(
    ("option", "number"),
    [
        ("30", 30.0),
        ("KES 12,500", 12500.0),
        ("KES 12 500", 12500.0),
        ("15%", 15.0),
        ("3.5 km", 3.5),
        ("-4", -4.0),
        ("3/4", 0.75),
        ("1,250.50", 1250.5),
    ],
)
def test_the_number_an_option_states(option, number):
    assert check.number_in(option) == pytest.approx(number)


@pytest.mark.parametrize("option", ["3 hours 20 minutes", "5:3", "none", "between 4 and 6", ""])
def test_an_option_without_exactly_one_number_has_none(option):
    assert check.number_in(option) is None


def test_the_key_is_the_option_the_calculation_gives():
    good = check.shape(raw(), "easy")  # the writer's key is already that option
    settled = check.key_from_calculation(good)
    assert settled.correct_index == 1
    assert settled.explanation.endswith("Calculation: 0.12*250 = 30.")
    assert settled.explanation.startswith("12% of 250 is 0.12 x 250 = 30.")


def test_a_writer_that_points_at_the_wrong_option_is_corrected_by_the_arithmetic():
    pointing_wrong = check.shape(raw(correct_index=3), "easy")  # 35, but the sum gives 30
    assert check.key_from_calculation(pointing_wrong).correct_index == 1


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"calculation": "0.12*200"}, "no option is the result"),  # 24 is not on offer
        ({"calculation": ""}, "no calculation"),
        ({"calculation": "twelve percent"}, "could not be evaluated"),
        ({"options": ["30", "30.1", "25", "35"], "correct_index": 0}, "more than one option"),
    ],
)
def test_a_question_whose_calculation_does_not_pick_out_exactly_one_option_is_refused(
    overrides, why
):
    with pytest.raises(check.Reject, match=why):
        check.key_from_calculation(check.shape(raw(**overrides), "easy"))


def test_rounding_to_the_precision_of_an_option_still_matches():
    third = check.shape(
        raw(options=["33.3", "30", "35", "40"], correct_index=0, calculation="100/3"), "easy"
    )
    assert check.key_from_calculation(third).correct_index == 0


def test_options_that_are_not_plain_numbers_are_left_to_the_solving_pass():
    times = check.shape(
        raw(
            question="A task takes 80 minutes. How long is that in hours and minutes?",
            options=["1 hour 20 minutes", "1 hour 40 minutes", "2 hours", "1 hour 10 minutes"],
            correct_index=0,
            calculation="80/60",
        ),
        "easy",
    )
    assert check.key_from_calculation(times) == times  # untouched: nothing to compare
