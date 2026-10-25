"""The pipeline with a stand-in writer: what it keeps, what it throws away, and when it gives up."""

import random

import pytest

from app.services.qgen import pipeline
from app.services.qgen.categories import CATEGORIES
from app.services.qgen.check import LABELS
from app.services.qgen.schema import RawQuestion
from app.services.qgen.writers import WriterError, WriterUnavailable

# Different words in every one, so none counts as a repeat of another.
POOL = [
    ("A cyclist rides 36 kilometres in 3 hours. What is the average speed in kilometres per hour?",
     ["10", "12", "14", "9"], 1, "36/3", "36/3 = 12."),
    ("A pen costs KES 45 and a notebook costs KES 120. How much do 4 pens and 2 notebooks cost "
     "together in KES?", ["400", "420", "380", "440"], 1, "4*45+2*120", "180 + 240 = 420."),
    ("A tank holds 800 litres and is 35% full. How many litres of water are in it?",
     ["250", "280", "300", "320"], 1, "0.35*800", "0.35 x 800 = 280."),
    ("The mean of five exam marks is 64 and four of them total 250. What is the fifth mark?",
     ["60", "68", "70", "74"], 2, "5*64-250", "320 - 250 = 70."),
    ("An investment of KES 5000 earns 4% simple interest each year. What is the total after one "
     "year in KES?", ["5100", "5200", "5400", "5020"], 1, "5000+5000*0.04", "5000 + 200 = 5200."),
    ("A recipe needs 3 parts flour to 2 parts sugar. How much sugar goes with 450 grams of flour, "
     "in grams?", ["200", "250", "300", "350"], 2, "450/3*2", "450 / 3 x 2 = 300."),
]


def raw_from(index: int, **overrides) -> RawQuestion:
    text, options, correct, calculation, explanation = POOL[index]
    base = {
        "difficulty": "easy",
        "question": text,
        "options": options,
        "correct_index": correct,
        "explanation": explanation,
        "calculation": calculation,
    }
    return RawQuestion(**(base | overrides))


class Stub:
    """Writes the batches it was given, in order, and solves by looking each question up."""

    name = "stub"
    model = "stub-1"

    def __init__(self, *batches, solver=None):
        self.batches = list(batches)
        self.solver = solver
        self.written = 0
        self.solved = 0
        self.asked_for: list[int] = []
        self.avoided: list[list[str]] = []
        self.key: dict[str, str] = {}

    def write(self, category, count, difficulties, avoid):
        self.written += 1
        self.asked_for.append(count)
        self.avoided.append(list(avoid))
        batch = self.batches.pop(0)
        if isinstance(batch, Exception):
            raise batch
        for q in batch:
            self.key[q.question] = q.options[q.correct_index]
        return batch

    def solve(self, items):
        self.solved += 1
        if self.solver:
            return self.solver(self, items)
        return self.right_answers(items)

    def right_answers(self, items):
        return [LABELS[options.index(self.key[text])] for text, options in items]


def run(stub, count=2, avoid=(), category="numerical", seed=1, solves=1):
    report = pipeline.Report()
    batches = list(
        pipeline.produce(
            stub,
            CATEGORIES[category],
            ["easy"] * count,
            list(avoid),
            random.Random(seed),
            report,
            solves,
        )
    )
    return [w for batch in batches for w in batch], report


# ----------------------------------------------------------------------------------- the good path


def test_good_questions_are_kept_with_the_key_following_its_option():
    stub = Stub([raw_from(0), raw_from(1)])
    written, report = run(stub)

    assert len(written) == 2
    assert report.rounds == 1 and report.accepted == 2 and report.rejected == []
    for item in written:
        source = next(p for p in POOL if p[0] == item.text)
        assert item.options[item.correct_index] == source[1][source[2]]
        assert sorted(item.options) == sorted(source[1])  # the same four, in some order
        assert item.category == "numerical"


def test_the_servers_shuffle_not_the_writers_decides_where_the_key_sits():
    positions = set()
    for seed in range(12):
        stub = Stub([raw_from(0)])
        (item,), _ = run(stub, count=1, seed=seed)
        positions.add(item.correct_index)
    assert len(positions) >= 3  # the writer always put it at index 1; the paper does not


# ------------------------------------------------------------------------ checked twice


def positional(stub, items):
    """A checker with a habit: it always says A, whatever the question."""
    return ["A"] * len(items)


def test_a_question_must_be_confirmed_with_its_options_in_a_different_order():
    shown = []

    def record(stub, items):
        shown.append([options for _, options in items])
        return stub.right_answers(items)

    stub = Stub([raw_from(0), raw_from(1)], solver=record)
    written, report = run(stub, solves=2, category="logical")

    assert len(written) == 2 and report.rejected == []
    assert stub.solved == 2
    first, second = shown
    assert second == [list(reversed(options)) for options in first]  # same four, turned round


def test_a_checker_with_a_favourite_letter_cannot_confirm_a_question_twice():
    # the first pass says A to everything, so it only agrees where the key happens to be A, and
    # the reversed pass then says "D" in the original order: it can never agree with both
    stub = Stub(*[[raw_from(0), raw_from(1)] for _ in range(4)], solver=positional)
    with pytest.raises(pipeline.PaperFailed):
        run(stub, solves=2, category="logical")


def test_only_the_questions_that_passed_the_first_check_are_asked_again():
    def second_pass_sees_one(stub, items):
        if stub.solved == 1:  # first pass: get question 1 wrong
            answers = stub.right_answers(items)
            answers[0] = LABELS[(LABELS.index(answers[0]) + 1) % 4]
            return answers
        assert len(items) == 1  # only the survivor is shown again
        return stub.right_answers(items)

    stub = Stub([raw_from(0), raw_from(1)], [raw_from(2)], solver=second_pass_sees_one)
    written, report = run(stub, solves=2, category="logical")
    assert {w.text for w in written} == {POOL[1][0], POOL[2][0]}
    assert report.rejected == ["the independent check did not confirm the answer"]


def test_the_arithmetic_counts_as_one_check_so_a_numerical_question_is_asked_one_fewer_time():
    stub = Stub([raw_from(0), raw_from(1)])
    written, _ = run(stub, solves=2, category="numerical")
    assert len(written) == 2 and stub.solved == 1

    other = Stub([raw_from(0), raw_from(1)])
    run(other, solves=2, category="verbal")
    assert other.solved == 2  # nothing else checks a verbal question, so both passes run


def test_one_check_is_enough_when_that_is_what_is_asked_for():
    stub = Stub([raw_from(0)])
    written, _ = run(stub, count=1, solves=1)
    assert len(written) == 1 and stub.solved == 1


def test_the_default_is_two_checks():
    assert pipeline.SOLVES == 2


# ------------------------------------------------------------------------ what is thrown away


def test_a_question_the_independent_check_answers_differently_is_replaced():
    def lazy(stub, items):
        answers = stub.right_answers(items)
        if stub.solved == 1:  # the first time, get the first question wrong
            answers[0] = LABELS[(LABELS.index(answers[0]) + 1) % 4]
        return answers

    stub = Stub([raw_from(0), raw_from(1)], [raw_from(2)], solver=lazy)
    written, report = run(stub)

    assert len(written) == 2
    assert {w.text for w in written} == {POOL[1][0], POOL[2][0]}
    assert report.rejected == ["the independent check did not confirm the answer"]
    assert stub.asked_for == [2, 1]  # only the missing one is asked for again


def test_a_numerical_question_whose_calculation_matches_no_option_is_replaced():
    stub = Stub([raw_from(0, calculation="36/5"), raw_from(1)], [raw_from(2)])
    written, report = run(stub)

    assert {w.text for w in written} == {POOL[1][0], POOL[2][0]}
    assert "no option is the result of the calculation" in report.rejected[0]
    assert stub.solved == 2  # the bad one never even reached the solver


def test_the_arithmetic_not_the_writer_decides_which_option_is_the_key():
    # the writer's index points at 10 (the first option); 36/3 = 12 is the second
    wrong_index = raw_from(0, correct_index=0)

    def knows_the_truth(stub, items):
        return [LABELS[options.index("12")] for _, options in items]

    stub = Stub([wrong_index], solver=knows_the_truth)
    (item,), report = run(stub, count=1)

    assert item.options[item.correct_index] == "12"
    assert report.rejected == []
    assert item.explanation.endswith("Calculation: 36/3 = 12.")


def test_the_arithmetic_check_applies_only_to_numerical_questions():
    stub = Stub([raw_from(0, calculation=""), raw_from(1, calculation="")])
    written, report = run(stub, category="logical")
    assert len(written) == 2 and report.rejected == []


def test_a_repeat_of_a_question_already_on_the_paper_is_replaced():
    stub = Stub([raw_from(0), raw_from(1)], [raw_from(2)])
    written, report = run(stub, avoid=[POOL[0][0]])

    assert POOL[0][0] not in {w.text for w in written}
    assert any("repeats" in r for r in report.rejected)
    assert stub.avoided[0] == [POOL[0][0]]
    assert POOL[1][0] in stub.avoided[1]  # what was kept is on the list by the next round


def test_two_questions_alike_in_one_batch_keep_only_the_first():
    near = POOL[0][0].replace("36", "42").replace("3 hours", "3 hours")
    stub = Stub([raw_from(0), raw_from(0, question=near)], [raw_from(3)])
    written, _ = run(stub)
    assert len(written) == 2
    assert POOL[3][0] in {w.text for w in written}


def test_a_badly_formed_question_is_replaced():
    stub = Stub([raw_from(0, options=["1", "2", "3"]), raw_from(1)], [raw_from(2)])
    written, report = run(stub)
    assert len(written) == 2
    assert "expected 4 options" in report.rejected[0]


def test_more_questions_than_asked_for_are_ignored():
    stub = Stub([raw_from(0), raw_from(1), raw_from(2)])
    written, _ = run(stub, count=2)
    assert len(written) == 2


# ----------------------------------------------------------------------------------- when it fails


def test_a_writer_error_costs_a_round_and_it_tries_again():
    stub = Stub(WriterError("ollama took too long to answer"), [raw_from(0)])
    written, report = run(stub, count=1)
    assert len(written) == 1
    assert report.rejected == ["ollama took too long to answer"]


def test_a_solver_error_distrusts_the_whole_round():
    calls = []

    def flaky(stub, items):
        calls.append(len(items))
        if len(calls) == 1:
            raise WriterError("could not answer")
        return stub.right_answers(items)

    stub = Stub([raw_from(0)], [raw_from(0)], solver=flaky)
    written, report = run(stub, count=1)
    assert len(written) == 1
    assert report.rejected == ["could not be checked: could not answer"]
    assert stub.written == 2  # unchecked work is rewritten, and not mistaken for a repeat


def test_it_gives_up_with_the_reasons_when_the_rounds_run_out():
    bad = [raw_from(0, options=["1", "1", "2", "3"])]
    stub = Stub(bad, bad, bad, bad, bad)
    with pytest.raises(pipeline.PaperFailed, match="could not write enough Numerical questions"):
        run(stub, count=1)
    assert stub.written == 4  # one round plus the three extra


def test_a_writer_that_cannot_be_reached_is_not_retried():
    stub = Stub(WriterUnavailable("ollama is not running"), [raw_from(0)])
    with pytest.raises(WriterUnavailable):
        run(stub, count=1)
    assert stub.written == 1


def test_a_big_category_is_asked_for_in_batches_of_five():
    stub = Stub(
        [raw_from(i) for i in range(5)],
        [raw_from(5)],
    )
    written, report = run(stub, count=6)
    assert len(written) == 6
    assert stub.asked_for == [5, 1]
    assert report.rounds == 2
