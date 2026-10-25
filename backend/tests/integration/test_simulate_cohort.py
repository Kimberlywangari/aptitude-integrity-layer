"""The made-up sitting: what it writes, that it can be removed cleanly, and that it never
touches what was seeded for real people."""

from sqlalchemy import func, select

from app.models import Candidate, Flag, SessionQuestion, Sitting, TestSession
from scripts.simulate_cohort import SITTING_NAME, purge, simulate


def test_it_writes_sixteen_finished_sessions_and_their_flags(db, seeded):
    result = simulate(db, seed=1)

    assert result.created is True
    assert result.candidates == 16
    assert result.flags is not None and result.flags.cohort_applied is True
    assert db.scalar(select(func.count()).select_from(TestSession)) == 16
    sitting = db.scalar(select(Sitting).where(Sitting.name == SITTING_NAME))
    assert sitting.status == "closed"  # so a real candidate can never be started into it
    assert db.scalar(select(Flag.id).limit(1)) is not None


def test_the_simulation_can_be_removed_without_touching_anything_else(db, seeded):
    result = simulate(db, seed=1)
    assert result.created and result.candidates == 16

    removed = purge(db)
    assert removed == 16
    assert db.scalar(select(Flag.id).limit(1)) is None
    assert db.scalar(select(func.count()).select_from(TestSession)) == 0
    assert db.scalar(select(Sitting).where(Sitting.name == SITTING_NAME)) is None
    # what was seeded for real people is untouched
    assert db.scalar(select(func.count()).select_from(Candidate)) == 20
    assert db.scalar(select(func.count()).select_from(Sitting)) == 1
    simulated = select(func.count()).select_from(Candidate).where(Candidate.id.like("sim-%"))
    assert db.scalar(simulated) == 0


def test_simulating_twice_does_not_duplicate(db, seeded):
    simulate(db, seed=1)
    again = simulate(db, seed=1)
    assert again.created is False
    assert db.scalar(select(func.count()).select_from(TestSession)) == 16


def test_the_same_seed_gives_the_same_cohort(db, seeded):
    first = simulate(db, seed=7, name="first")
    flags_first = sorted(
        db.execute(
            select(TestSession.candidate_id, Flag.kind, Flag.position)
            .join(Flag, Flag.session_id == TestSession.id)
            .where(TestSession.sitting_id == first.sitting_id)
        ).all()
    )
    purge(db, "first")
    second = simulate(db, seed=7, name="second")
    flags_second = sorted(
        db.execute(
            select(TestSession.candidate_id, Flag.kind, Flag.position)
            .join(Flag, Flag.session_id == TestSession.id)
            .where(TestSession.sitting_id == second.sitting_id)
        ).all()
    )
    assert flags_first == flags_second
    assert flags_first  # and it is not vacuous


def test_it_needs_no_past_candidate_statistics_and_ignores_written_questions(db, seeded):
    from app.models import Question, QuestionStats

    db.execute(QuestionStats.__table__.delete())  # a bank with no history at all
    for section in ("numerical", "verbal", "logical"):  # and some questions an AI wrote
        db.add(
            Question(
                id=f"G{section[:3]}{'0' * 12}", section=section, difficulty="easy",
                correct_option="A", text="written for someone", source="ai",
            )
        )
    db.flush()

    result = simulate(db, seed=3)

    assert result.created and result.candidates == 16
    used = db.scalars(
        select(Question.source)
        .join(SessionQuestion, SessionQuestion.question_id == Question.id)
        .join(TestSession, TestSession.id == SessionQuestion.session_id)
        .where(TestSession.sitting_id == result.sitting_id)
    ).all()
    assert used and "ai" not in set(used)
