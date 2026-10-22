from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.errors import ApiError
from app.models import Option, Question, QuestionStats, SessionQuestion, Sitting, TestSession
from app.services import admin, evidence
from app.services.cytonn_bank import BankInUse, load_bank, parse_sections
from scripts.seed_synthetic import seed

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)


def answer(answer_id, text, correct=False):
    return {"id": answer_id, "answer": text, "is_correct": correct}


def api_question(question_id, text="What is 12 + 7?", answers=None):
    if answers is None:
        answers = [answer(101, "17"), answer(102, "19", True), answer(103, "21")]
    return {"id": question_id, "question": text, "answers": answers}


def bank_of(*questions, name="Numerical Reasoning"):
    section = {"name": name, "time_per_question": "1.5", "questions": list(questions)}
    return parse_sections({"data": [section]})


@pytest.fixture
def seeded(db):
    seed(db, seed=42, secret="s", public_base_url="http://x")
    return db


def draw(db, question_id, *, status="finished", candidate="cand-001"):
    """A session whose paper includes this question. Its id is returned."""
    sid = f"{candidate}-{status}".ljust(32, "x")
    db.add(
        TestSession(
            id=sid,
            candidate_id=candidate,
            sitting_id=db.scalar(select(Sitting.id)),
            status=status,
            created_at=NOW,
        )
    )
    db.flush()
    db.add(SessionQuestion(session_id=sid, position=1, question_id=question_id, option_order=[]))
    db.flush()
    return sid


def test_a_new_question_is_created_with_cytonns_ids_and_no_statistics(db):
    result = load_bank(db, bank_of(api_question(10)))

    assert (result.created, result.updated, result.unchanged) == (1, 0, 0)
    question = db.get(Question, "C10")
    assert (question.cytonn_id, question.source) == (10, "cytonn")
    assert question.section == "numerical reasoning"
    assert question.difficulty is None
    assert [(o.label, o.cytonn_id, o.text) for o in question.options] == [
        ("A", 101, "17"),
        ("B", 102, "19"),
        ("C", 103, "21"),
    ]
    assert question.correct_option == "B"
    assert db.scalar(select(func.count()).select_from(QuestionStats)) == 0


def test_the_answer_marked_correct_follows_the_answer_not_its_position(db):
    answers = [answer(205, "five", False), answer(201, "one", True), answer(203, "three")]
    load_bank(db, bank_of(api_question(20, answers=answers)))
    question = db.get(Question, "C20")
    correct = next(o for o in question.options if o.label == question.correct_option)
    assert (correct.cytonn_id, correct.text) == (201, "one")


def test_running_it_twice_changes_nothing_even_if_the_answers_arrive_reordered(db):
    load_bank(db, bank_of(api_question(10)))
    ids_before = sorted(db.scalars(select(Option.id)))

    reordered = [answer(103, "21"), answer(102, "19", True), answer(101, "17")]
    again = load_bank(db, bank_of(api_question(10, answers=reordered)))

    assert (again.created, again.updated, again.unchanged) == (0, 0, 1)
    assert sorted(db.scalars(select(Option.id))) == ids_before  # rows were not rewritten


def test_a_question_nobody_has_drawn_is_updated_in_place(db):
    load_bank(db, bank_of(api_question(10)))

    changed = [answer(100, "15"), answer(101, "17"), answer(102, "19", True), answer(103, "21")]
    result = load_bank(db, bank_of(api_question(10, text="What is 8 + 11?", answers=changed)))

    assert (result.created, result.updated) == (0, 1)
    question = db.get(Question, "C10")
    assert question.text == "What is 8 + 11?"
    assert [(o.label, o.cytonn_id) for o in question.options] == [
        ("A", 100),
        ("B", 101),
        ("C", 102),
        ("D", 103),
    ]
    assert question.correct_option == "C"  # answer 102 is now the third
    assert db.scalar(select(func.count()).select_from(Question)) == 1


def test_a_question_a_session_has_drawn_is_never_changed_and_is_reported(seeded):
    load_bank(seeded, bank_of(api_question(10)))
    draw(seeded, "C10")

    flipped = [answer(101, "17", True), answer(102, "19"), answer(103, "21")]
    result = load_bank(seeded, bank_of(api_question(10, answers=flipped)))

    assert result.kept_used == [10] and result.updated == 0
    assert seeded.get(Question, "C10").correct_option == "B"  # still what was scored against


def test_a_question_cytonn_no_longer_lists_is_reported_and_kept(db):
    load_bank(db, bank_of(api_question(10), api_question(11)))

    result = load_bank(db, bank_of(api_question(10)))

    assert result.missing_upstream == [11]
    assert db.get(Question, "C11") is not None


def test_statistics_of_a_question_are_left_alone(db):
    load_bank(db, bank_of(api_question(10)))
    db.add(
        QuestionStats(
            question_id="C10",
            n=500,
            pct_correct=0.5,
            median_s=30,
            p25_s=20,
            p75_s=45,
            source="cytonn",
        )
    )
    db.flush()

    load_bank(db, bank_of(api_question(10, text="Reworded")))

    stats = db.get(QuestionStats, "C10")
    assert (stats.n, stats.source) == (500, "cytonn")


def test_it_refuses_while_a_session_is_in_progress_unless_forced(seeded):
    draw(seeded, "Q001", status="in_progress")  # a paper that has been started

    with pytest.raises(BankInUse):
        load_bank(seeded, bank_of(api_question(10)))
    assert seeded.get(Question, "C10") is None

    assert load_bank(seeded, bank_of(api_question(10)), force=True).created == 1


def test_questions_skipped_by_the_parser_are_not_written(db):
    no_scheme = api_question(11, answers=[answer(1, "a"), answer(2, "b")])
    result = load_bank(db, bank_of(api_question(10), no_scheme))
    assert result.created == 1
    assert db.get(Question, "C11") is None


# ---------------------------------------------------- what the rest of the app now does with them


def test_retiring_placeholders_keeps_questions_from_cytonn_even_without_statistics(seeded):
    load_bank(seeded, bank_of(api_question(10), api_question(11)))

    removed, kept = admin.retire_synthetic(seeded)

    assert (removed, kept) == (60, 0)
    assert sorted(seeded.scalars(select(Question.id))) == ["C10", "C11"]


def test_the_bank_summary_counts_a_question_from_cytonn_as_real_without_statistics(seeded):
    load_bank(seeded, bank_of(api_question(10)))

    summary = admin.bank_summary(seeded)

    assert (summary.total, summary.cytonn, summary.synthetic) == (61, 1, 60)
    real = next(s for s in summary.by_section if s.section == "numerical reasoning")
    assert (real.count, real.cytonn, real.synthetic) == (1, 1, 0)


def test_the_migration_marked_questions_with_cytonns_statistics_as_real(seeded):
    # the import path marks them too: a question imported from Cytonn's summary is Cytonn's
    from app.services.question_import import import_summary

    summary = (
        "question_id,section,correct_option,difficulty_tag,n_candidates,pct_correct,"
        "median_s,p25_s,p75_s\nQ001,verbal,B,hard,812,38.5,71,50,96\n"
    )
    import_summary(seeded, "summary.csv", summary)
    assert seeded.get(Question, "Q001").source == "cytonn"
    assert seeded.get(Question, "Q002").source == "synthetic"


def sitting_args(count):
    return {
        "name": "Real sitting",
        "opens_at": None,
        "closes_at": None,
        "duration_s": 1800,
        "question_count": count,
    }


def test_a_sitting_is_refused_when_one_section_is_too_small_for_its_share(db):
    questions = [api_question(i) for i in range(1, 11)]
    load_bank(db, bank_of(*questions, name="Numerical Reasoning"))
    load_bank(db, bank_of(api_question(50), api_question(51), name="Verbal Reasoning"))

    with pytest.raises(ApiError) as refused:
        admin.create_sitting(db, **sitting_args(6))  # 3 from each section; verbal has 2

    assert (refused.value.status_code, refused.value.code) == (409, "section_too_small")
    assert refused.value.extra == {
        "needed": 3,
        "sections": [{"section": "verbal reasoning", "available": 2}],
    }

    assert admin.create_sitting(db, **sitting_args(4)).question_count == 4  # 2 from each


def test_a_total_that_is_too_big_still_gets_the_older_message(db):
    load_bank(db, bank_of(api_question(10)))
    with pytest.raises(ApiError) as refused:
        admin.create_sitting(db, **sitting_args(2))
    assert refused.value.code == "question_bank_too_small"
    assert refused.value.extra == {"available": 1}


def test_the_reviewer_is_told_when_no_question_has_any_history(seeded):
    load_bank(seeded, bank_of(api_question(10)))
    sid = draw(seeded, "C10")
    assert evidence.history_source(seeded, sid) == "none"

    with_history = draw(seeded, "Q001", candidate="cand-002")
    assert evidence.history_source(seeded, with_history) == "synthetic"
