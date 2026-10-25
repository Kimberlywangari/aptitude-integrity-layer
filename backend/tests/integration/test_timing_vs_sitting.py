# ruff: noqa: F811
"""A candidate's time on each question, and in all, next to what the rest of the sitting took. It is
context for a reviewer: it needs enough other people to mean anything, it says what it is the median
of, and in a sitting whose questions are written for each candidate it falls back to the section."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Question, SessionQuestion, Sitting, TestSession
from app.services import evidence
from app.services.staff_auth import create_reviewer
from tests.integration.test_candidate_emails import (  # noqa: F401  (fixtures used by name)
    PASSWORD,
    admin_headers,
    paste,
    sitting,
)
from tests.integration.test_results_and_outcomes import reviewer_headers  # noqa: F401

MINIMUM = 8  # the same number of others the percentile comparison needs


def numerical_ids(db, count):
    return list(db.scalars(select(Question.id).where(Question.section == "numerical").limit(count)))


def finished(db, clock, sitting_id, candidate_id, question_ids, seconds, total_s=600):
    """A finished session that spent `seconds[i]` on question i and `total_s` in all."""
    start = clock.now()
    session = TestSession(
        id=f"s-{candidate_id}",
        candidate_id=candidate_id,
        sitting_id=sitting_id,
        status="finished",
        created_at=start,
        started_at=start,
        ends_at=start + timedelta(seconds=total_s),
        finished_at=start + timedelta(seconds=total_s),
    )
    db.add(session)
    db.flush()
    cursor = start
    for position, (question_id, took) in enumerate(zip(question_ids, seconds, strict=True), 1):
        db.add(
            SessionQuestion(
                session_id=session.id,
                position=position,
                question_id=question_id,
                option_order=[],
                opened_at=cursor,
                answered_at=cursor + timedelta(seconds=took),
                correct=True,
            )
        )
        cursor += timedelta(seconds=took + 1)
    db.flush()


def invite(client, headers, sitting, count):
    text = "\n".join(f"Person {n}, p{n}@example.org" for n in range(1, count + 1))
    return [i["candidate_id"] for i in paste(client, headers, sitting, text).json()["invites"]]


def log(client, headers, sitting, candidate_id):
    response = client.get(
        f"/api/review/candidates/{candidate_id}/events",
        params={"sitting": sitting["id"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def room(client, db, clock, sitting, admin_headers, others):
    """The candidate to look at (ids[0], slow on the first question and quick on the second) and
    `others` more who all took 10 s, then 20 s, and 100 s in all."""
    ids = invite(client, admin_headers, sitting, others + 1)
    questions = numerical_ids(db, 2)
    finished(db, clock, sitting["id"], ids[0], questions, [40, 5], total_s=300)
    for other in ids[1:]:
        finished(db, clock, sitting["id"], other, questions, [10, 20], total_s=100)
    return ids[0]


def test_each_question_shows_the_sitting_median_for_that_same_question(
    client, db, clock, sitting, admin_headers, reviewer_headers
):
    me = room(client, db, clock, sitting, admin_headers, MINIMUM)
    body = log(client, reviewer_headers, sitting, me)

    first, second = body["questions"]
    assert (first["time_s"], first["sitting_median_s"], first["median_of"]) == (
        40.0,
        10.0,
        "question",
    )
    assert (second["time_s"], second["sitting_median_s"], second["median_n"]) == (
        5.0,
        20.0,
        MINIMUM,
    )
    assert body["timing"] == {
        "total_s": 300.0,
        "sitting_median_total_s": 100.0,
        "others": MINIMUM,
        "min_others": MINIMUM,
        "same_questions": True,
    }


def test_with_too_few_others_nothing_is_compared(
    client, db, clock, sitting, admin_headers, reviewer_headers
):
    me = room(client, db, clock, sitting, admin_headers, MINIMUM - 1)
    body = log(client, reviewer_headers, sitting, me)
    assert all(q["sitting_median_s"] is None and q["median_of"] is None for q in body["questions"])
    assert body["questions"][0]["median_n"] == 0
    assert body["timing"]["sitting_median_total_s"] is None
    assert body["timing"]["others"] == MINIMUM - 1


def test_a_skipped_or_timed_out_question_is_not_part_of_anyones_median(
    client, db, clock, sitting, admin_headers, reviewer_headers
):
    me = room(client, db, clock, sitting, admin_headers, MINIMUM)
    # one other candidate ran out the 105 s on the first question: that is no answer time
    first_of_someone_else = db.scalars(
        select(SessionQuestion).where(
            SessionQuestion.session_id != f"s-{me}", SessionQuestion.position == 1
        )
    ).first()
    first_of_someone_else.skipped = True
    first_of_someone_else.answered_at = first_of_someone_else.opened_at + timedelta(seconds=105)
    db.flush()

    first, second = log(client, reviewer_headers, sitting, me)["questions"]
    # seven answers to the first question is too few, so it falls back to the section: 7 tens and
    # 8 twenties, median 20. The second question still has all eight.
    assert (first["median_of"], first["median_n"], first["sitting_median_s"]) == (
        "section",
        MINIMUM * 2 - 1,
        20.0,
    )
    assert (second["median_of"], second["median_n"], second["sitting_median_s"]) == (
        "question",
        MINIMUM,
        20.0,
    )


def test_a_sitting_with_a_paper_per_candidate_is_compared_by_section(
    client, db, clock, sitting, admin_headers, reviewer_headers
):
    ids = invite(client, admin_headers, sitting, MINIMUM + 1)
    pool = numerical_ids(db, 2 * (MINIMUM + 1))
    # nobody shares a question, as when an AI writes a paper for each candidate
    for number, candidate_id in enumerate(ids):
        mine = pool[2 * number : 2 * number + 2]
        took = [50, 50] if number == 0 else [10, 30]
        finished(db, clock, sitting["id"], candidate_id, mine, took)
    db.get(Sitting, sitting["id"]).question_mode = "ai"
    db.flush()

    body = log(client, reviewer_headers, sitting, ids[0])
    # ten and thirty seconds, eight people each: the section's median is 20
    assert [q["median_of"] for q in body["questions"]] == ["section", "section"]
    assert [q["sitting_median_s"] for q in body["questions"]] == [20.0, 20.0]
    assert body["timing"]["same_questions"] is False


def test_the_median_functions_need_enough_people():
    four = evidence.OthersTimes(
        by_question={"Q1": [10.0, 20.0, 30.0]},
        by_section={"numerical": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]},
        totals=[100.0, 110.0, 120.0, 130.0],
    )
    assert evidence.median_of([1.0, 2.0, 3.0], 3) == 2.0
    assert evidence.median_of([1.0, 2.0], 3) is None
    assert evidence.compare_question(four, "Q1", "numerical", 3) == (20.0, "question", 3)
    assert evidence.compare_question(four, "Q9", "numerical", 3) == (3.5, "section", 6)
    assert evidence.compare_question(four, "Q9", "verbal", 3) == (None, None, 0)
    # six answers in the section, but only two people behind them: not a group
    two = evidence.OthersTimes(
        by_section={"numerical": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}, totals=[100.0, 110.0]
    )
    assert evidence.compare_question(two, "Q9", "numerical", 3) == (None, None, 0)


def test_no_question_text_and_no_other_candidate_is_named(
    client, db, clock, sitting, admin_headers, reviewer_headers
):
    me = room(client, db, clock, sitting, admin_headers, MINIMUM)
    text = client.get(
        f"/api/review/candidates/{me}/events",
        params={"sitting": sitting["id"]},
        headers=reviewer_headers,
    ).text
    assert "Person" not in text and "example.org" not in text
    assert "text" not in {
        key for q in log(client, reviewer_headers, sitting, me)["questions"] for key in q
    }


@pytest.fixture(autouse=True)
def _a_reviewer_exists(db, clock):
    create_reviewer(db, clock, email="someone@example.com", password=PASSWORD)
