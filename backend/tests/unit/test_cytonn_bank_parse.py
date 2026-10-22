import pytest

from app.services.cytonn_bank import MAX_OPTIONS, SECTION_MAX, parse_sections


def answer(answer_id, text, correct=False):
    return {"id": answer_id, "answer": text, "is_correct": correct}


def question(question_id=10, text="What is 12 + 7?", answers=None):
    if answers is None:
        answers = [answer(101, "17"), answer(102, "19", True), answer(103, "21")]
    return {"id": question_id, "question": text, "answers": answers}


def section(questions, name="Numerical Reasoning", minutes="1.5"):
    return {
        "id": 1,
        "name": name,
        "description": "Questions on basic arithmetic.",
        "time_per_question": minutes,
        "questions": questions,
    }


def parse(*sections):
    return parse_sections({"data": list(sections)})


def test_the_guides_example_parses():
    bank = parse(section([question()]))

    assert bank.skipped == [] and bank.warnings == []
    (parsed,) = bank.questions
    assert (parsed.id, parsed.cytonn_id, parsed.section) == ("C10", 10, "numerical reasoning")
    assert parsed.text == "What is 12 + 7?"
    assert parsed.options == ((101, "17"), (102, "19"), (103, "21"))
    assert parsed.correct_answer_id == 102
    assert bank.minutes == {"numerical reasoning": 1.5}


def test_answers_come_back_in_no_fixed_order_but_are_sorted_by_their_id():
    shuffled = [answer(103, "21"), answer(101, "17"), answer(102, "19", True)]
    (parsed,) = parse(section([question(answers=shuffled)])).questions
    assert [answer_id for answer_id, _ in parsed.options] == [101, 102, 103]


def test_a_one_stands_for_true_and_the_text_is_trimmed():
    answers = [answer(1, "  yes "), {"id": 2, "answer": "no", "is_correct": 1}]
    (parsed,) = parse(section([question(text="  Is it?  ", answers=answers)])).questions
    assert parsed.text == "Is it?"
    assert parsed.options[0] == (1, "yes")
    assert parsed.correct_answer_id == 2


@pytest.mark.parametrize(
    ("answers", "reason"),
    [
        ([answer(1, "a"), answer(2, "b")], "no marking scheme"),
        ([answer(1, "a", True), answer(2, "b", True)], "more than one answer is marked correct"),
        ([answer(1, "a", True)], "fewer than 2 answers"),
        (
            [answer(i, f"option {i}", i == 1) for i in range(1, MAX_OPTIONS + 2)],
            f"more than {MAX_OPTIONS} answers",
        ),
        ([answer(1, "a", True), answer(1, "b")], "two answers share an id"),
        ([answer(1, "a", True), answer(2, "   ")], "an answer has no id or no text"),
        ([answer(None, "a", True), answer(2, "b")], "an answer has no id or no text"),
    ],
)
def test_a_question_that_cannot_be_scored_is_skipped_and_says_why(answers, reason):
    bank = parse(section([question(answers=answers)]))
    assert bank.questions == []
    assert len(bank.skipped) == 1
    cytonn_id, why = bank.skipped[0]
    assert cytonn_id == 10 and why.startswith(reason)


def test_a_blank_question_and_a_question_without_an_id_are_skipped():
    bank = parse(section([question(text="  "), {"question": "no id", "answers": []}]))
    assert bank.questions == []
    assert [reason for _, reason in bank.skipped] == [
        "the question has no text",
        "a question has no numeric id",
    ]


def test_the_good_questions_in_a_section_still_load_next_to_a_bad_one():
    bank = parse(section([question(10), question(11, answers=[]), question(12)]))
    assert [q.cytonn_id for q in bank.questions] == [10, 12]
    assert [cytonn_id for cytonn_id, _ in bank.skipped] == [11]


def test_a_section_name_that_will_not_fit_skips_its_questions():
    bank = parse(section([question(10), question(11)], name="x" * (SECTION_MAX + 1)))
    assert bank.questions == []
    assert [cytonn_id for cytonn_id, _ in bank.skipped] == [10, 11]
    assert "section name" in bank.skipped[0][1]


def test_a_question_that_appears_twice_is_kept_once():
    bank = parse(section([question(10)], name="A"), section([question(10)], name="B"))
    assert [q.section for q in bank.questions] == ["a"]
    assert bank.skipped == [(10, "the question appears twice")]


def test_questions_are_ordered_by_section_then_id():
    bank = parse(
        section([question(30), question(20)], name="Verbal"),
        section([question(40)], name="Logical"),
    )
    assert [(q.section, q.cytonn_id) for q in bank.questions] == [
        ("logical", 40),
        ("verbal", 20),
        ("verbal", 30),
    ]


@pytest.mark.parametrize("minutes", [None, "", "soon", "0", "-1"])
def test_minutes_per_question_is_none_when_it_is_not_a_positive_number(minutes):
    assert parse(section([question()], minutes=minutes)).minutes == {"numerical reasoning": None}


def test_text_that_would_print_badly_is_warned_about_not_rejected():
    markup = question(10, text="<p>What is <b>2 + 2</b>?</p>")
    long_text = question(11, text="x" * 2001)
    twins = question(12, answers=[answer(1, "Same", True), answer(2, "same")])
    clean = question(13)

    bank = parse(section([markup, long_text, twins, clean]))

    assert [q.cytonn_id for q in bank.questions] == [10, 11, 12, 13]
    assert len(bank.warnings) == 3
    assert any("HTML" in w and "10" in w for w in bank.warnings)
    assert any("over 2000" in w and "11" in w for w in bank.warnings)
    assert any("same text" in w and "12" in w for w in bank.warnings)


@pytest.mark.parametrize(
    "payload", [{}, [], {"data": {}}, {"error": "No aptitude test found"}, None]
)
def test_a_response_of_the_wrong_shape_is_an_error(payload):
    with pytest.raises(ValueError, match="unexpected response"):
        parse_sections(payload)
