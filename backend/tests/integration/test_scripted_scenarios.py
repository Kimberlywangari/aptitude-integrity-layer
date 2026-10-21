"""The scripted actions, end to end: a candidate drives the real HTTP API on a fake clock, sending
the events and heartbeats a browser would, and the flag rules read what the server stored.

This is the "scripted actions are caught every time" criterion made executable. Each test is one
row of eval/scripted_actions.md. The honest runs matter as much: an action a page cannot stop
(leaving full screen, a reload, a dropped connection) must show up as context and never as a flag.
"""

import pytest
from sqlalchemy import select

from app.models import Event, Flag, Option, Question, SessionQuestion
from app.services.flags.engine import compute_session_flags
from tests.support import Live

# An ordinary answer. Session ids are random, so the paper (and each question's difficulty) differs
# from run to run; this is long enough to be below nobody's "quick" and short enough to be below
# nobody's "long hold" whatever the paper holds: a hard question's quick-answer line is at most
# 47 s, and with every answer 50 s the long-hold line is 150 s.
USUAL_S = 50


class Script:
    """Walks one candidate through the paper, one question at a time, on the fake clock."""

    def __init__(self, live: Live, clock, db) -> None:
        self.live, self.clock, self.db = live, clock, db
        self.seq = 0
        assert live.begin().status_code == 200

    def send(self, type_, *, age_s: float = 0.0, **payload) -> None:
        self.seq += 1
        body = {"client_seq": self.seq, "type": type_, "age_ms": int(age_s * 1000)}
        if payload:
            body["payload"] = payload
        assert self.live.events(body).status_code == 200

    def wait(self, seconds: float, *, beat: bool = True) -> None:
        """Let time pass, with a heartbeat every ten seconds unless `beat` is off."""
        left = seconds
        while left > 0:
            step = min(10.0, left)
            self.clock.advance(step)
            left -= step
            if beat:
                self.live.heartbeat()

    def _option(self, position: int, correct: bool) -> int:
        row = self.db.get(SessionQuestion, (self.live.session_id, position))
        question = self.db.get(Question, row.question_id)
        wanted = question.correct_option
        options = self.db.scalars(select(Option).where(Option.question_id == question.id)).all()
        return next((o.id for o in options if (o.label == wanted) == correct), None)

    def question(self) -> int:
        self.db.expire_all()
        return self.live.question().json()["position"]

    def answer(self, position: int, *, correct: bool = True) -> None:
        self.db.expire_all()
        response = self.live.client.post(
            self.live.url("answer"),
            json={"position": position, "option_id": self._option(position, correct)},
            headers=self.live.headers,
        )
        assert response.status_code == 200, response.text

    def paper(self, plan=None) -> None:
        """Answer every question. `plan[position]` is a function(script, position) that spends
        the time and sends the events for that question; the default is an ordinary answer."""
        plan = plan or {}
        while True:
            position = self.question()
            self.send("question_opened", position=position)
            step = plan.get(position)
            if step:
                step(self, position)
            else:
                self.wait(USUAL_S)
            done = self.live.session().status == "finished"
            if done:
                return
            self.answer(position)
            if self.live.session().status == "finished":
                return

    def flags(self) -> dict[str, list[Flag]]:
        compute_session_flags(self.db, self.live.session_id)
        by_kind: dict[str, list[Flag]] = {}
        for flag in self.db.scalars(select(Flag).where(Flag.session_id == self.live.session_id)):
            by_kind.setdefault(flag.kind, []).append(flag)
        return by_kind


@pytest.fixture
def script(client, db, seeded, clock):
    return Script(Live(client, db, seeded.invites[0].token).start(), clock, db)


# -------------------------------------------------------------------------- honest candidates


def test_a_plain_honest_run_raises_nothing(script):
    script.paper()
    assert script.flags() == {}


def test_an_honest_run_with_every_problem_a_page_cannot_prevent_raises_nothing(script):
    def drop(s, position):  # the connection goes for 30 s and comes back; the page reloads
        s.wait(5)
        s.send("connection_lost")
        s.wait(30, beat=False)
        s.send("connection_restored")
        s.send("reload")
        s.wait(USUAL_S)  # then an ordinary-length answer, so these are not fast ones

    def fullscreen(s, position):  # out of full screen for 40 s, plus ordinary page events
        s.wait(5)
        s.send("fullscreen_exited")
        s.send("paste_attempt")
        s.send("contextmenu_attempt")
        s.wait(40)
        s.send("fullscreen_entered")
        s.wait(USUAL_S)

    def camera(s, position):
        s.wait(10)
        s.send("camera_dropped", duration_s=25)
        s.send("mic_muted")
        s.wait(10)
        s.send("mic_unmuted")
        s.wait(USUAL_S)

    script.paper({3: drop, 6: fullscreen, 9: camera})
    assert script.flags() == {}


# ------------------------------------------------------------------------- scripted actions


def test_tabbing_out_to_look_something_up_is_caught_as_focus_losses_and_long_correct_holds(script):
    def lookup(s, position):
        s.wait(6)
        s.send("focus_lost")
        s.wait(40)
        s.send("focus_returned")
        s.wait(220)

    script.paper({3: lookup, 5: lookup, 7: lookup})
    found = script.flags()

    assert [f.position for f in found["FOCUS_LOSS"]] == [3, 5, 7]
    holds = found["LONG_HOLD_CORRECT"]
    assert [f.position for f in holds] == [3, 5, 7]
    assert all(f.weight == 4 for f in holds)  # focus was lost during each: 3 + 1
    assert all(f.detail["focus_lost_during"] for f in holds)
    assert holds[0].detail["time_s"] > 3 * holds[0].detail["own_median_s"]


def test_a_long_hold_on_a_question_answered_correctly_is_flagged_without_the_bonus(script):
    def slow(s, position):
        s.wait(300)

    script.paper({4: slow})  # answered correctly by default: flagged
    holds = script.flags()["LONG_HOLD_CORRECT"]
    assert [f.position for f in holds] == [4] and holds[0].weight == 3  # no focus loss: no bonus


def test_copying_the_question_is_caught_and_only_its_length_is_stored(script):
    def copy(s, position):
        s.wait(8)
        s.send("copy_attempt", length=212, text="what is the capital of the moon")
        s.wait(12)

    script.paper({4: copy})
    found = script.flags()

    (flag,) = found["COPY_ATTEMPT"]
    assert flag.position == 4 and flag.weight == 3
    assert flag.detail == {"target": "question_text", "length": 212}
    stored = script.db.scalars(select(Event).where(Event.type == "copy_attempt")).all()
    assert [e.payload for e in stored] == [{"length": 212}]  # the wording never reached the table


def test_cutting_counts_as_copying(script):
    def cut(s, position):
        s.wait(5)
        s.send("cut_attempt", length=50)
        s.wait(15)

    script.paper({2: cut})
    assert [f.position for f in script.flags()["COPY_ATTEMPT"]] == [2]


def test_going_idle_then_answering_a_run_correctly_and_fast_is_caught(script):
    def idle(s, position):
        s.send("idle_start")
        s.wait(90)
        s.send("idle_end", duration_s=90)
        s.wait(8)

    def quick(s, position):
        s.wait(8)

    script.paper({5: idle, 6: quick, 7: quick, 8: quick})
    found = script.flags()

    (flag,) = found["CORRECT_RUN_AFTER_GAP"]
    assert flag.weight == 2 and flag.detail["run_length"] >= 3 and flag.detail["gap_s"] == 90


def test_a_focus_loss_of_a_second_or_more_counts_and_a_blink_does_not(script):
    def blink(s, position):
        s.wait(5)
        s.send("focus_lost")
        s.wait(0.5)
        s.send("focus_returned")
        s.wait(15)

    def real(s, position):
        s.wait(5)
        s.send("focus_lost")
        s.wait(3)
        s.send("focus_returned")
        s.wait(12)

    script.paper({2: blink, 3: real})
    assert [f.position for f in script.flags()["FOCUS_LOSS"]] == [3]


def test_heartbeats_stopping_for_a_minute_with_nothing_to_explain_it_is_a_logging_problem(script):
    def silent(s, position):
        s.wait(40, beat=False)  # no heartbeat, no dropped connection, no reload

    script.paper({5: silent})
    found = script.flags()

    (gap,) = found["LOGGING_PROBLEM"]
    assert gap.weight == 0 and gap.detail["heartbeat_gap_s"] > 35
    assert set(found) == {"LOGGING_PROBLEM"}


def test_the_same_gap_explained_by_a_dropped_connection_is_not_a_problem(script):
    def drop(s, position):
        s.wait(2)
        s.send("connection_lost")
        s.wait(60, beat=False)
        s.send("connection_restored")
        s.wait(8)

    script.paper({5: drop})
    assert "LOGGING_PROBLEM" not in script.flags()


def test_events_that_arrive_late_keep_the_moment_they_happened(script):
    def late(s, position):
        s.wait(40)  # the page was offline; it sends what it saw 35 s ago
        s.send("focus_lost", age_s=35)
        s.send("focus_returned", age_s=20)  # a 15 s loss, 20 s ago

    script.paper({4: late})
    (loss,) = script.flags()["FOCUS_LOSS"]
    assert loss.detail["focus_lost_s"] == 15
    row = script.db.get(SessionQuestion, (script.live.session_id, 4))
    assert row.opened_at < loss.server_ts < row.answered_at  # inside question 4, not after it
