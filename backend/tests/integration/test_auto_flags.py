"""Flags work themselves out: when a candidate finishes, when late events arrive and when the
sitting is closed. Nobody has to run a command for a reviewer to see them."""

import pytest
from sqlalchemy import select

from app.core.staff_token import issue_staff_token
from app.models import Flag, Sitting, TestSession
from app.services import test_flow
from app.services.flags.engine import COHORT_KINDS, compute_session_flags
from app.services.staff_auth import create_reviewer
from tests.support import Live

ORDINARY_S = 50  # long enough that no answer counts as a quick one, short enough to be no hold


def copy_event(seq: int, age_ms: int = 0, length: int = 120) -> dict:
    payload = {"length": length}
    return {"client_seq": seq, "type": "copy_attempt", "age_ms": age_ms, "payload": payload}


def kinds_of(db, session_id: str) -> list[str]:
    db.expire_all()
    found = select(Flag).where(Flag.session_id == session_id).order_by(Flag.server_ts, Flag.id)
    return [flag.kind for flag in db.scalars(found)]


@pytest.fixture
def admin_headers(db, clock, settings):
    account, _ = create_reviewer(
        db, clock, email="boss@example.com", password="correct horse battery", role="admin"
    )
    token = issue_staff_token(settings.session_secret, clock, account.id, account.password_hash)
    return {"Authorization": f"Bearer {token}"}


def sitting_of(db, live: Live) -> Sitting:
    return db.get(Sitting, live.session().sitting_id)


# ------------------------------------------------------------------------------- on finishing


def test_pressing_finish_works_out_the_flags(client, db, seeded, clock):
    live = Live(client, db, seeded.invites[0].token).start()
    assert live.begin().status_code == 200
    clock.advance(30)
    assert live.events(copy_event(1)).status_code == 200
    assert kinds_of(db, live.session_id) == []  # still sitting: nothing worked out yet

    clock.advance(30)
    assert live.finish().status_code == 200

    assert "COPY_ATTEMPT" in kinds_of(db, live.session_id)


def test_answering_the_last_question_works_out_the_flags(client, db, seeded, clock):
    live = Live(client, db, seeded.invites[0].token).start()
    assert live.begin().status_code == 200
    clock.advance(30)
    assert live.events(copy_event(1)).status_code == 200

    live.answer_everything(clock, seconds_each=ORDINARY_S)

    assert live.session().status == "finished"
    assert "COPY_ATTEMPT" in kinds_of(db, live.session_id)


def test_running_out_of_time_works_out_the_flags(client, db, seeded, clock):
    live = Live(client, db, seeded.invites[0].token).start()
    assert live.begin().status_code == 200
    clock.advance(30)
    assert live.events(copy_event(1)).status_code == 200

    clock.advance(sitting_of(db, live).duration_s)
    assert live.question().status_code == 410  # time_up finishes the session

    assert live.session().status == "finished"
    assert "COPY_ATTEMPT" in kinds_of(db, live.session_id)


def test_finishing_again_does_not_double_the_flags(client, db, seeded, clock):
    live = Live(client, db, seeded.invites[0].token).start()
    assert live.begin().status_code == 200
    clock.advance(30)
    assert live.events(copy_event(1)).status_code == 200
    clock.advance(30)
    live.finish()
    once = kinds_of(db, live.session_id)

    live.finish(chunks_total=3)  # the page says the chunk count again after its last flush

    assert kinds_of(db, live.session_id) == once


def test_events_that_arrive_after_the_test_ended_update_the_flags(client, db, seeded, clock):
    live = Live(client, db, seeded.invites[0].token).start()
    assert live.begin().status_code == 200
    clock.advance(60)
    live.finish()
    assert "COPY_ATTEMPT" not in kinds_of(db, live.session_id)

    clock.advance(5)
    assert live.events(copy_event(1, age_ms=3000)).status_code == 200  # held back by the network

    assert "COPY_ATTEMPT" in kinds_of(db, live.session_id)


def test_events_during_the_test_do_not_work_out_flags_early(client, db, seeded, clock):
    live = Live(client, db, seeded.invites[0].token).start()
    assert live.begin().status_code == 200
    clock.advance(10)
    assert live.events(copy_event(1)).status_code == 200
    assert live.session().status == "in_progress"
    assert kinds_of(db, live.session_id) == []


# ------------------------------------------------------------------------------ on closing


def test_closing_finishes_an_abandoned_test_and_works_out_its_flags(
    client, db, seeded, clock, admin_headers
):
    live = Live(client, db, seeded.invites[0].token).start()
    assert live.begin().status_code == 200
    assert live.events(copy_event(1)).status_code == 200
    sitting = sitting_of(db, live)

    clock.advance(sitting.duration_s + 60)  # the tab was closed; nobody came back
    assert live.session().status == "in_progress"
    closed = client.post(
        f"/api/admin/sittings/{sitting.id}/close", json={"force": True}, headers=admin_headers
    )
    assert closed.status_code == 200, closed.text

    session = live.session()
    assert session.status == "finished"
    assert session.finished_at == session.ends_at  # when its time ran out, not when it was found
    assert "COPY_ATTEMPT" in kinds_of(db, live.session_id)


def test_closing_leaves_a_test_still_inside_its_time_alone(
    client, db, seeded, clock, admin_headers
):
    live = Live(client, db, seeded.invites[0].token).start()
    assert live.begin().status_code == 200
    clock.advance(30)
    sitting = sitting_of(db, live)

    closed = client.post(
        f"/api/admin/sittings/{sitting.id}/close", json={"force": True}, headers=admin_headers
    )

    assert closed.status_code == 200
    assert live.session().status == "in_progress"


def test_the_sweep_finishes_only_tests_whose_time_has_run_out(client, db, seeded, clock):
    first = Live(client, db, seeded.invites[0].token).start()
    assert first.begin().status_code == 200
    duration = sitting_of(db, first).duration_s
    clock.advance(duration / 2)
    second = Live(client, db, seeded.invites[1].token).start()
    assert second.begin().status_code == 200
    clock.advance(duration / 2 + 1)  # the first is out of time; the second has half left

    swept = test_flow.finish_expired(db, clock)

    assert swept == [first.session_id]
    assert first.session().status == "finished"
    assert second.session().status == "in_progress"


# ---------------------------------------------------------------------- group flags are kept


def test_rerunning_one_session_keeps_the_group_flags_a_closed_sitting_gave_it(db, clock, sim):
    session_id = db.scalars(
        select(TestSession.id).where(TestSession.sitting_id == sim.sitting_id).limit(1)
    ).one()
    db.add(
        Flag(
            session_id=session_id,
            kind=COHORT_KINDS[0],
            weight=1.5,
            server_ts=clock.now(),
            position=None,
            detail={"direction": "fast"},
            source="rule",
        )
    )
    db.flush()
    before = sorted(k for k in kinds_of(db, session_id) if k not in COHORT_KINDS)

    compute_session_flags(db, session_id)

    after = kinds_of(db, session_id)
    assert COHORT_KINDS[0] in after
    assert sorted(k for k in after if k not in COHORT_KINDS) == before
