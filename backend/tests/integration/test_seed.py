import csv
from collections import Counter

from sqlalchemy import func, select

from app.core.security import INVITE_ALPHABET, hash_token, normalise_invite_code
from app.models import Candidate, Option, Question, QuestionStats, Sitting
from scripts.seed_synthetic import seed


def _count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


def test_seed_twice_changes_nothing(db):
    first = seed(db, seed=42, secret="s", public_base_url="http://x")
    second = seed(db, seed=42, secret="s", public_base_url="http://x")

    assert _count(db, Question) == 60
    assert _count(db, Option) == 240
    assert _count(db, QuestionStats) == 60
    assert _count(db, Candidate) == 20
    assert _count(db, Sitting) == 1

    assert first.questions_created == 60
    assert second.questions_created == second.options_created == second.stats_created == 0
    assert second.candidates_created == second.sittings_created == 0
    assert [i.token for i in first.invites] == [i.token for i in second.invites]


def test_each_section_has_7_easy_7_medium_6_hard(db):
    seed(db, seed=42, secret="s", public_base_url="http://x")
    rows = db.execute(select(Question.section, Question.difficulty)).all()
    by_section = {}
    for section, difficulty in rows:
        by_section.setdefault(section, Counter())[difficulty] += 1
    assert set(by_section) == {"numerical", "verbal", "logical"}
    for counts in by_section.values():
        assert counts == {"easy": 7, "medium": 7, "hard": 6}


def test_stats_follow_the_difficulty_table_with_bounded_jitter(db):
    seed(db, seed=42, secret="s", public_base_url="http://x")
    expected = {"easy": (25, 0.85), "medium": (45, 0.60), "hard": (75, 0.35)}
    rows = db.execute(
        select(Question.difficulty, QuestionStats).join(
            QuestionStats, QuestionStats.question_id == Question.id
        )
    ).all()
    assert len(rows) == 60
    for difficulty, stats in rows:
        median, pct = expected[difficulty]
        assert stats.source == "synthetic"
        assert stats.n == 400
        assert 0.8 * median - 0.1 <= stats.median_s <= 1.2 * median + 0.1
        assert 0.8 * pct - 0.001 <= stats.pct_correct <= min(0.99, 1.2 * pct) + 0.001
        assert stats.p25_s == round(0.7 * stats.median_s, 1)
        assert stats.p75_s == round(1.4 * stats.median_s, 1)


def test_correct_option_is_a_real_label_and_not_always_the_same(db):
    seed(db, seed=42, secret="s", public_base_url="http://x")
    labels = {q.id: {o.label for o in q.options} for q in db.scalars(select(Question))}
    correct = dict(db.execute(select(Question.id, Question.correct_option)).all())
    assert all(correct[qid] in labels[qid] for qid in correct)
    assert len(set(correct.values())) > 1


def test_invites_are_hashed_in_the_database_and_written_to_csv(db, tmp_path):
    path = tmp_path / "data" / "invites.csv"
    result = seed(db, seed=42, secret="s", public_base_url="http://x", invites_path=path)

    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 20
    assert rows[0]["url"] == f"http://x/?t={rows[0]['token']}"
    # the CSV shows the code the way a candidate types it
    assert all(len(r["token"]) == 9 and r["token"][4] == "-" for r in rows)

    stored = {c.id: c.invite_token_hash for c in db.scalars(select(Candidate))}
    for invite in result.invites:
        assert stored[invite.candidate_id] == hash_token(invite.token)
        assert invite.token not in stored.values()


def test_invites_are_short_typeable_codes_and_the_csv_form_maps_back_to_them(db, tmp_path):
    path = tmp_path / "invites.csv"
    result = seed(db, seed=42, secret="s", public_base_url="http://x", invites_path=path)

    with path.open(newline="", encoding="utf-8") as fh:
        rows = {r["candidate_id"]: r["token"] for r in csv.DictReader(fh)}

    assert len({i.token for i in result.invites}) == 20
    for invite in result.invites:
        assert len(invite.token) == 8
        assert set(invite.token) <= set(INVITE_ALPHABET)
        # typing the CSV form (or a lower-case copy of it) reaches the same stored hash
        assert normalise_invite_code(rows[invite.candidate_id]) == invite.token
        assert normalise_invite_code(rows[invite.candidate_id].lower()) == invite.token
