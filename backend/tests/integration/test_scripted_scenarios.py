"""The scripted actions, end to end: a candidate drives the real HTTP API on a fake clock, sending
the events and heartbeats a browser would, and the flag rules read what the server stored.

This is the "scripted actions are caught every time" criterion made executable. Each test is one
row of eval/scripted_actions.md. The honest runs matter as much: an action a page cannot stop
(leaving full screen, a reload, a dropped connection) must show up as context and never as a flag.
"""

import pytest
from sqlalchemy import select, update

from app.models import Event, Flag, Option, Question, SessionQuestion
from app.services.flags.engine import compute_session_flags
from tests.support import Live

# An ordinary answer. Every ordinary answer takes the same time, so a candidate's own median is
# this, the long-hold line is 90 s (its cap) and the "quick run" line is 25 s whatever the paper
# holds.
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
        # in time order: without an ORDER BY the rows come back in whatever order the table's pages
        # happen to hold them, and the assertions below read the flags by position
        found = select(Flag).where(Flag.session_id == self.live.session_id)
        for flag in self.db.scalars(found.order_by(Flag.server_ts, Flag.id)):
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
        s.wait(50)

    script.paper({3: lookup, 5: lookup, 7: lookup})
    found = script.flags()

    assert [f.position for f in found["FOCUS_LOSS"]] == [3, 5, 7]
    holds = found["LONG_HOLD_CORRECT"]
    assert [f.position for f in holds] == [3, 5, 7]
    assert all(f.weight == 4 for f in holds)
    assert all(f.detail["focus_lost_s"] == 40 for f in holds)
    assert holds[0].detail["time_s"] > holds[0].detail["own_median_s"]


def test_a_long_hold_with_focus_on_the_page_the_whole_time_is_not_flagged(script):
    def slow(s, position):
        s.wait(100)

    script.paper({4: slow})  # answered correctly, and slowly, but nothing took them away
    assert "LONG_HOLD_CORRECT" not in script.flags()


def test_a_long_hold_needs_more_than_two_seconds_away(script):
    def glance(s, position):  # 2 s away: not enough
        s.wait(6)
        s.send("focus_lost")
        s.wait(2)
        s.send("focus_returned")
        s.wait(88)

    def look(s, position):  # 3 s away: enough
        s.wait(6)
        s.send("focus_lost")
        s.wait(3)
        s.send("focus_returned")
        s.wait(87)

    script.paper({4: glance, 8: look})
    holds = script.flags()["LONG_HOLD_CORRECT"]
    assert [f.position for f in holds] == [8]
    assert holds[0].detail["focus_lost_s"] == 3


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


def test_a_screenshot_key_is_flagged_at_two_points_and_only_the_key_combination_is_stored(script):
    def snap(s, position):
        s.wait(8)
        s.send("screenshot_attempt", combo="PrintScreen", note="free text the page should not send")
        s.wait(12)

    script.paper({3: snap})
    (flag,) = script.flags()["SCREENSHOT_KEY"]

    assert flag.position == 3 and flag.weight == 2 and flag.detail == {"combo": "PrintScreen"}
    stored = script.db.scalars(select(Event).where(Event.type == "screenshot_attempt")).all()
    assert [e.payload for e in stored] == [{"combo": "PrintScreen"}]


def test_cutting_counts_as_copying(script):
    def cut(s, position):
        s.wait(5)
        s.send("cut_attempt", length=50)
        s.wait(15)

    script.paper({2: cut})
    assert [f.position for f in script.flags()["COPY_ATTEMPT"]] == [2]


def test_going_idle_then_answering_a_run_correctly_and_fast_is_caught(script):  # S5
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
    assert flag.detail["mean_s"] < 0.5 * flag.detail["own_median_s"]


def test_answering_three_in_a_row_in_under_twenty_seconds_is_caught_without_leaving_the_page(
    script,
):  # S5c: the phone
    def quick(s, position):
        s.wait(5)

    script.paper({4: quick, 5: quick, 6: quick})
    found = script.flags()

    (flag,) = found["FAST_RUN"]
    assert flag.position == 4 and flag.weight == 1
    assert flag.detail == {"answers_in_a_row": 3, "answers_mean_s": 5.0}
    assert "FOCUS_LOSS" not in found and "CORRECT_RUN_AFTER_GAP" not in found


def test_long_questions_answered_correctly_in_under_twenty_seconds_are_caught(script):  # S5d
    script.db.execute(update(Question).values(text="x" * 700))  # every question is now long

    def quick(s, position):
        s.wait(10)

    script.paper({2: quick, 4: quick})
    found = script.flags()

    flags = found["LONG_FAST_CORRECT"]
    assert [f.position for f in flags] == [2, 4]
    assert all(f.weight == 0.5 and f.detail["question_chars"] == 700 for f in flags)
    assert "FAST_RUN" not in found  # two apart, not three in a row


def test_a_run_after_a_gap_at_the_candidates_usual_pace_is_not_flagged(script):
    def idle(s, position):
        s.send("idle_start")
        s.wait(60)
        s.send("idle_end", duration_s=60)
        s.wait(30)

    script.paper({5: idle})  # they come back and carry on at their normal pace, all correct
    assert "CORRECT_RUN_AFTER_GAP" not in script.flags()


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
