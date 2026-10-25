import pytest

from app.services.cytonn_bank import MAX_OPTIONS, SECTION_MAX, parse_sections


def answer(answer_id, text, correct=False):
    return {"id": answer_id, "answer": text, "is_correct": correct}


def question(question_id=10, text=None, answers=None):
    text = text or f"What is {question_id} + 7?"  # each its own, or they would be copies
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
    assert parsed.text == "What is 10 + 7?"
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


def test_a_very_long_text_or_answer_is_warned_about_not_rejected():
    long_text = question(11, text="x" * 2001)
    long_answer = question(12, answers=[answer(1, "y" * 501, True), answer(2, "short")])

    bank = parse(section([long_text, long_answer, question(13)]))

    assert [q.cytonn_id for q in bank.questions] == [11, 12, 13]
    assert len(bank.warnings) == 2
    assert any("over 2000" in w and "11" in w for w in bank.warnings)
    assert any("answer over 500" in w and "12" in w for w in bank.warnings)


def test_html_is_turned_into_the_plain_text_the_screen_shows():
    html = (
        "<p>Revenue rose by <strong>12%</strong> to &pound;1,050 in 2&nbsp;years.</p>"
        "<p>10<sup>3</sup> is a <em>thousand</em>; the 1<sup>st</sup> quarter.</p>"
    )
    (parsed,) = parse(section([question(10, text=html)])).questions
    assert parsed.text == (
        "Revenue rose by 12% to £1,050 in 2 years.\n\n10³ is a thousand; the 1st quarter."
    )


def test_answers_are_converted_too_and_a_leading_letter_is_taken_off_when_they_all_have_one():
    lettered = [
        answer(1, "A. Allow the AI to decide", False),
        answer(2, "B. Use it as a first pass", True),
        answer(3, "C. Ask them to re-submit", False),
    ]
    (parsed,) = parse(section([question(10, answers=lettered)])).questions
    assert [t for _, t in parsed.options] == [
        "Allow the AI to decide",
        "Use it as a first pass",
        "Ask them to re-submit",
    ]
    # one that merely starts like a letter is a real answer
    mixed = [answer(1, "A. Smith", True), answer(2, "Jones"), answer(3, "Brown")]
    (kept,) = parse(section([question(11, answers=mixed)])).questions
    assert kept.options[0][1] == "A. Smith"
    entity = [answer(1, "&pound;5", True), answer(2, "&euro;5")]
    (decoded,) = parse(section([question(12, answers=entity)])).questions
    assert [t for _, t in decoded.options] == ["£5", "€5"]


def test_a_picture_leaves_a_marker_and_its_address_is_cleaned_and_kept_in_order():
    html = (
        "<p>Study the chart.</p>"
        '<p><img src="https://hr.cytonn.com/../storage/aptitude/q92.PNG" alt="" /></p>'
        "<p>What comes next?</p>"
        '<p><img src="https://hr.cytonn.com/storage/aptitude/q93.PNG"></p>'
    )
    (parsed,) = parse(section([question(10, text=html)])).questions
    assert parsed.text == "Study the chart.\n\n[[image 1]]\n\nWhat comes next?\n\n[[image 2]]"
    assert parsed.images == (
        "https://hr.cytonn.com/storage/aptitude/q92.PNG",
        "https://hr.cytonn.com/storage/aptitude/q93.PNG",
    )


def test_a_question_with_nothing_but_a_picture_is_kept():
    html = '<p><img src="https://hr.cytonn.com/storage/aptitude/q1.PNG" alt=""></p>'
    bank = parse(section([question(10, text=html)]))
    assert [q.text for q in bank.questions] == ["[[image 1]]"]
    assert bank.images_needed == ["https://hr.cytonn.com/storage/aptitude/q1.PNG"]


@pytest.mark.parametrize(
    ("kwargs", "why"),
    [
        ({"text": '<p>Look: <img src="not a web address"></p>'}, "a picture has no usable"),
        ({"text": '<img src="javascript:alert(1)">'}, "a picture has no usable"),
        (
            {
                "answers": [
                    {"id": 1, "answer": '<img src="https://hr.cytonn.com/a.png">', "is_correct": 1},
                    answer(2, "b"),
                ]
            },
            "an answer contains a picture",
        ),
        (
            {"answers": [answer(1, "Same", True), answer(2, "same")]},
            "two answers have the same text",
        ),
    ],
)
def test_a_question_that_cannot_be_shown_properly_is_left_out_and_says_why(kwargs, why):
    bank = parse(section([question(10, **kwargs)]))
    assert bank.questions == []
    assert bank.skipped[0][1].startswith(why)


def test_a_copy_under_another_id_is_left_out_but_the_first_is_kept():
    bank = parse(
        section([question(20, text="Same words"), question(10, text="Same words")], name="Verbal")
    )
    assert [q.cytonn_id for q in bank.questions] == [10]
    assert bank.skipped == [(20, "a copy of question 10")]


def test_two_copies_that_disagree_about_the_answer_are_both_left_out():
    first = question(10, text="Same words", answers=[answer(1, "True", True), answer(2, "False")])
    second = question(11, text="Same words", answers=[answer(5, "True"), answer(6, "False", True)])
    bank = parse(section([first, second]))
    assert bank.questions == []
    assert sorted(i for i, _ in bank.skipped) == [10, 11]
    assert "different answer" in bank.skipped[0][1]


def test_questions_that_differ_only_by_underlining_are_not_copies():
    plain = question(10, text="<p>Which word means dictates?</p>")
    underlined = question(11, text="<p>Which word means <u>dictates</u>?</p>")
    assert [q.cytonn_id for q in parse(section([plain, underlined])).questions] == [10, 11]


def test_questions_about_one_passage_share_a_key_and_a_short_question_has_none():
    passage = (
        "The Silk Road, stretching from China to the Mediterranean Sea, was not a single road but "
        "a web of routes used for centuries. "
    )
    one = question(10, text=passage + "It connected which two regions of the world?")
    two = question(11, text=passage + "What does the passage say it was not?")
    short = question(12, text="What is 2 + 2?")
    other = question(13, text="A different passage altogether, with enough words to be long. " * 3)
    keys = {q.cytonn_id: q.passage_key for q in parse(section([one, two, short, other])).questions}
    assert keys[10] == keys[11] and keys[10] is not None
    assert keys[12] is None
    assert keys[13] not in (None, keys[10])


@pytest.mark.parametrize(
    "payload", [{}, [], {"data": {}}, {"error": "No aptitude test found"}, None]
)
def test_a_response_of_the_wrong_shape_is_an_error(payload):
    with pytest.raises(ValueError, match="unexpected response"):
        parse_sections(payload)
