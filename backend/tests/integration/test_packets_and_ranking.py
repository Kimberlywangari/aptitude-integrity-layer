"""Evidence packets, the cohort baselines, and ranking a sitting, on the made-up closed sitting of
sixteen candidates (the simulator's data stands in for the practice questions sitting)."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select

from app.models import (
    AudioSilence,
    Event,
    Flag,
    Packet,
    Ranking,
    SittingStat,
    TestSession,
)
from app.schemas.packet import Packet as PacketSchema
from app.services.flags.engine import compute_sitting_flags
from app.services.packets import build_packet, build_sitting_packets
from app.services.ranking.base import RankerError, RankerResult
from app.services.ranking.rules import rule_order
from app.services.ranking.runner import rank_sitting
from tests.support import good_assessment  # noqa: F401  (shape reference)

# ---------------------------------------------------------------------------------- helpers


def flagged_ids(db, sitting_id):
    return set(
        db.scalars(
            select(Flag.session_id)
            .join(TestSession, TestSession.id == Flag.session_id)
            .where(TestSession.sitting_id == sitting_id)
        )
    )


def unflagged(db, sitting_id):
    flagged = flagged_ids(db, sitting_id)
    return [
        s
        for s in db.scalars(select(TestSession).where(TestSession.sitting_id == sitting_id))
        if s.id not in flagged
    ]


def passing(packet, strength=3):
    """An assessment that passes the fact check for any packet: it cites only the first flag
    and the flag count, and writes no number of its own."""
    from app.services.ranking.base import Assessment

    return Assessment.model_validate(
        {
            "candidate_id": packet["candidate_id"],
            "flags_support_each_other": "partly",
            "innocent_explanation": {"present": False, "evidence_ids": []},
            "strength": strength,
            "explanation": "F1 is the first of the flags in this packet.",
            "cited": {
                "flag_ids": ["F1"],
                "question_numbers": [],
                "times_s": [],
                "counts": {"flags": len(packet["flags"])},
            },
        }
    )


class Scripted:
    """A stand-in ranker: `plan(packet, attempt, violations)` returns an Assessment (or raises)."""

    name = "scripted"
    model = "scripted-1"

    def __init__(self, plan, clock=None, seconds_per_call=0):
        self.plan, self.clock, self.seconds = plan, clock, seconds_per_call
        self.calls: list[tuple[str, list[str] | None]] = []

    def assess(self, packet, violations=None):
        self.calls.append((packet["candidate_id"], violations))
        attempt = sum(1 for who, _ in self.calls if who == packet["candidate_id"])
        if self.clock and self.seconds:
            self.clock.advance(self.seconds)
        result = self.plan(packet, attempt, violations)
        return RankerResult(result, result.model_dump_json())


def always(strength):
    return lambda packet, attempt, violations: passing(packet, strength)


def hallucinating(packet, attempt, violations):
    bad = passing(packet).model_copy(deep=True)
    bad.cited.flag_ids = ["F99"]
    return bad


# ----------------------------------------------------------------------------------- packets


def test_every_queued_candidate_gets_a_packet_and_nobody_else(db, sim, clock):
    built = build_sitting_packets(db, clock, sim.sitting_id)

    queued = {o.session.id for o in rule_order(db, sim.sitting_id)}
    stored = set(db.scalars(select(Packet.session_id)))
    assert built == len(stored) == len(queued) > 0
    assert stored == queued


def test_a_lone_loss_of_focus_is_a_flag_but_not_enough_to_be_queued_or_get_a_packet(db, sim, clock):
    queued = {o.session.id for o in rule_order(db, sim.sitting_id)}
    lone = [
        s
        for s in db.scalars(
            select(TestSession).where(TestSession.id.in_(flagged_ids(db, sim.sitting_id)))
        )
        if s.id not in queued
    ]
    assert lone, "the simulator has honest candidates with a single loss of focus"
    build_sitting_packets(db, clock, sim.sitting_id)
    stored = set(db.scalars(select(Packet.session_id)))
    for session in lone:
        kinds = set(db.scalars(select(Flag.kind).where(Flag.session_id == session.id)))
        assert kinds == {"FOCUS_LOSS"} and session.id not in stored


def test_the_queue_threshold_is_a_setting(db, sim):
    from app.services.flags.config import FlagConfig

    strict = {o.session.id for o in rule_order(db, sim.sitting_id, FlagConfig(flagged_score=5.0))}
    default = {o.session.id for o in rule_order(db, sim.sitting_id)}
    loose = {o.session.id for o in rule_order(db, sim.sitting_id, FlagConfig(flagged_score=0.5))}
    assert strict < default < loose  # a higher bar queues fewer, a lower one queues the lone losses


def test_a_session_with_no_flags_has_no_packet_whatever_else_the_record_shows(db, sim):
    quiet = unflagged(db, sim.sitting_id)
    assert quiet, "the simulator makes honest candidates with no flags"
    for session in quiet:
        assert build_packet(db, session) is None


def test_a_reload_or_a_quiet_microphone_alone_never_makes_a_packet(db, sim):
    session = unflagged(db, sim.sitting_id)[0]
    base = session.started_at
    db.add_all(
        [
            Event(
                session_id=session.id,
                client_seq=900,
                type="reload",
                server_ts=base,
                received_at=base,
                payload=None,
            ),
            Event(
                session_id=session.id,
                client_seq=901,
                type="mic_silent_start",
                server_ts=base + timedelta(minutes=2),
                received_at=base,
                payload=None,
            ),
            Event(
                session_id=session.id,
                client_seq=902,
                type="mic_silent_end",
                server_ts=base + timedelta(minutes=5),
                received_at=base,
                payload={"duration_s": 180},
            ),
        ]
    )
    db.flush()
    assert build_packet(db, session) is None
    assert (
        db.scalar(select(func.count()).select_from(Flag).where(Flag.session_id == session.id)) == 0
    )


def test_a_packet_has_the_agreed_shape_and_a_complete_facts_block(db, sim):
    for session in db.scalars(
        select(TestSession).where(TestSession.id.in_(flagged_ids(db, sim.sitting_id)))
    ):
        packet = build_packet(db, session)
        PacketSchema.model_validate(packet)

        assert packet["candidate_id"] == session.candidate_id
        assert [f["id"] for f in packet["flags"]] == [
            f"F{i}" for i in range(1, len(packet["flags"]) + 1)
        ]
        facts = packet["facts"]
        for flag in packet["flags"]:
            assert flag["elapsed_s"] in facts["times_s"]
            if flag["question_number"] is not None:
                assert flag["question_number"] in facts["question_numbers"]
        assert facts["counts"]["flags"] == len(packet["flags"])
        assert packet["pace_s_per_q"] in facts["times_s"]
        assert "history_source" not in packet
        referenced = {f["question_number"] for f in packet["flags"] if f["question_number"]}
        assert referenced <= {q["number"] for q in packet["questions"]}


def test_a_packet_names_nobody_and_carries_no_token_label_or_free_text(db, sim, clock):
    session = db.get(TestSession, sorted(flagged_ids(db, sim.sitting_id))[0])
    session.precheck_report = {
        "camera_ok": True,
        "notifications_off_confirmed": True,
        "fullscreen_ok": True,
        "browser": {"name": "Chrome", "version": "141"},
        "device_labels": {"camera": "Wanjiru's iPhone Camera", "mic": "AirPods of Wanjiru"},
    }
    session.self_report = {
        "had_technical_issues": True,
        "note": "Call me on 0712 345 678 or wanjiru@example.com, my wifi dropped.",
    }
    db.add(
        Event(
            session_id=session.id,
            client_seq=950,
            type="device_info",
            server_ts=session.started_at,
            received_at=session.started_at,
            payload={"camera_label": "Wanjiru's iPhone Camera", "mic_label": "AirPods"},
        )
    )
    db.flush()

    packet = build_packet(db, session)
    text = json.dumps(packet)

    for secret in ("Wanjiru", "AirPods", "0712", "example.com", "wifi dropped"):
        assert secret not in text
    assert packet["candidate_id"] == session.candidate_id
    assert {"self_report", "technical_issue"} <= {
        v for s in packet["innocent_signals"] for v in s.values()
    }
    assert packet["precheck"] == {
        "notifications_off_confirmed": True,
        "fullscreen_ok": True,
        "browser": "Chrome 141",
    }

    def keys(value):
        if isinstance(value, dict):
            for k, v in value.items():
                yield k
                yield from keys(v)
        elif isinstance(value, list):
            for v in value:
                yield from keys(v)

    assert not {"name", "email", "token", "invite", "label"} & set(keys(packet))


def test_a_browser_stretch_and_a_server_stretch_that_overlap_are_one_entry_listing_both(db, sim):
    session = next(
        s
        for s in db.scalars(
            select(TestSession).where(TestSession.id.in_(flagged_ids(db, sim.sitting_id)))
        )
        if build_packet(db, s)["mic_silence"]
    )
    packet = build_packet(db, session)
    (stretch,) = packet["mic_silence"]
    assert stretch["layers"] == ["browser"]

    start = session.started_at + timedelta(seconds=stretch["start_s"] + 5)
    end = session.started_at + timedelta(seconds=stretch["end_s"] - 5)
    db.add(
        AudioSilence(
            session_id=session.id,
            segment=0,
            start_s=0,
            end_s=0,
            start_server_ts=start,
            end_server_ts=end,
        )
    )
    far = session.started_at + timedelta(seconds=stretch["end_s"] + 400)
    db.add(
        AudioSilence(
            session_id=session.id,
            segment=0,
            start_s=0,
            end_s=0,
            start_server_ts=far,
            end_server_ts=far + timedelta(seconds=90),
        )
    )
    db.flush()

    merged = build_packet(db, session)["mic_silence"]
    assert [m["layers"] for m in merged] == [["browser", "server"], ["server"]]
    assert merged[0]["start_s"] == stretch["start_s"] and merged[0]["end_s"] == stretch["end_s"]
    assert [m["id"] for m in merged] == ["M1", "M2"]


def test_a_server_stretch_shorter_than_the_minimum_is_left_out(db, sim):
    session = db.get(TestSession, sorted(flagged_ids(db, sim.sitting_id))[0])
    start = session.started_at + timedelta(seconds=30)
    db.add(
        AudioSilence(
            session_id=session.id,
            segment=0,
            start_s=0,
            end_s=0,
            start_server_ts=start,
            end_server_ts=start + timedelta(seconds=20),
        )
    )
    db.flush()
    assert all("server" not in m["layers"] for m in build_packet(db, session)["mic_silence"])


def test_leaving_full_screen_is_context_in_the_packet_and_never_a_flag(db, sim):
    session = db.get(TestSession, sorted(flagged_ids(db, sim.sitting_id))[0])
    flags_before = db.scalar(
        select(func.count()).select_from(Flag).where(Flag.session_id == session.id)
    )
    out = session.started_at + timedelta(seconds=100)
    db.add_all(
        [
            Event(
                session_id=session.id,
                client_seq=960,
                type="fullscreen_exited",
                server_ts=out,
                received_at=out,
                payload=None,
            ),
            Event(
                session_id=session.id,
                client_seq=961,
                type="fullscreen_entered",
                server_ts=out + timedelta(seconds=45),
                received_at=out,
                payload=None,
            ),
        ]
    )
    db.flush()

    packet = build_packet(db, session)
    assert packet["fullscreen_exits"] == [{"start_s": 100, "end_s": 145, "duration_s": 45}]
    assert 45 in packet["facts"]["times_s"]
    compute_sitting_flags(db, session.sitting_id)
    flags_after = db.scalar(
        select(func.count()).select_from(Flag).where(Flag.session_id == session.id)
    )
    assert flags_after == flags_before


def test_rebuilding_changes_nothing_and_a_packet_with_no_flags_left_is_removed(db, sim, clock):
    build_sitting_packets(db, clock, sim.sitting_id)
    first = {p.session_id: p.json for p in db.scalars(select(Packet))}
    build_sitting_packets(db, clock, sim.sitting_id)
    assert {p.session_id: p.json for p in db.scalars(select(Packet))} == first

    victim = sorted(first)[0]
    db.execute(delete(Flag).where(Flag.session_id == victim))
    build_sitting_packets(db, clock, sim.sitting_id)
    assert victim not in {p.session_id for p in db.scalars(select(Packet))}


# ---------------------------------------------------------------------------- the baselines


def test_the_cohort_baselines_are_kept_for_a_closed_sitting_of_enough_candidates(db, sim):
    stats = {s.metric: s for s in db.scalars(select(SittingStat))}
    assert set(stats) == {"pace", "spread"}
    assert stats["pace"].n == stats["spread"].n == 16
    assert stats["pace"].median > 0 and stats["pace"].mad > 0


def test_recomputing_replaces_the_baselines_rather_than_adding_to_them(db, sim):
    compute_sitting_flags(db, sim.sitting_id)
    compute_sitting_flags(db, sim.sitting_id)
    assert db.scalar(select(func.count()).select_from(SittingStat)) == 2


def test_a_sitting_that_shrinks_below_the_minimum_loses_its_baselines(db, sim):
    keep = list(db.scalars(select(TestSession.id).where(TestSession.sitting_id == sim.sitting_id)))
    for session_id in keep[:10]:
        db.get(TestSession, session_id).status = "in_progress"
    db.flush()

    run = compute_sitting_flags(db, sim.sitting_id)

    assert run.cohort_applied is False
    assert db.scalar(select(func.count()).select_from(SittingStat)) == 0


# ------------------------------------------------------------------------------- the ranking


def rankings(db):
    return {r.session_id: r for r in db.scalars(select(Ranking))}


def test_a_rules_only_run_writes_the_rule_order_and_says_the_ai_did_not_run(db, sim, clock):
    run = rank_sitting(db, sim.sitting_id, None, clock)

    ordered = rule_order(db, sim.sitting_id)
    assert run.flagged == len(ordered) == len(run.rankings) > 0
    assert [r.session_id for r in run.rankings] == [o.session.id for o in ordered]
    assert all(r.ai_status == "not_run" and r.ai_json is None for r in run.rankings)
    assert all(r.provider == "rules" and r.model is None for r in run.rankings)
    assert [r.final_rank for r in run.rankings] == list(range(1, len(ordered) + 1))
    assert all(r.rule_rank == o.rank for r, o in zip(run.rankings, ordered, strict=True))
    assert all(r.explanation.startswith("Rules only:") for r in run.rankings)


def test_when_the_ai_passes_its_strength_orders_the_queue(db, sim, clock):
    ordered = [o for o in rule_order(db, sim.sitting_id) if not o.logging_only]
    underdog = ordered[-1].session.id

    ranker = Scripted(
        lambda p, a, v: passing(
            p, 5 if p["candidate_id"] == ordered[-1].session.candidate_id else 1
        )
    )
    run = rank_sitting(db, sim.sitting_id, ranker, clock)

    assert run.statuses == {"ok": run.flagged}
    by_session = rankings(db)
    assert by_session[underdog].final_rank == 1  # moved from last to first by the AI
    assert by_session[underdog].rule_rank == ordered[-1].rank  # the rule position is kept
    assert all(r.ai_json and len(r.ai_attempts) == 1 for r in run.rankings)
    assert {r.provider for r in run.rankings} == {"scripted"}


def test_a_gap_in_the_record_stays_below_everyone_with_evidence_whatever_the_ai_says(
    db, sim, clock
):
    run = rank_sitting(db, sim.sitting_id, Scripted(always(5)), clock)
    lanes = [r.logging_only for r in run.rankings]
    assert any(lanes), "the simulator makes a candidate whose only flag is a record gap"
    assert lanes == sorted(lanes)


def test_a_wrong_first_answer_is_retried_with_the_violations_and_recorded(db, sim, clock):
    def plan(packet, attempt, violations):
        return hallucinating(packet, attempt, violations) if attempt == 1 else passing(packet)

    ranker = Scripted(plan)
    run = rank_sitting(db, sim.sitting_id, ranker, clock)

    assert run.statuses == {"retried": run.flagged}
    sample = run.rankings[0]
    first, second = sample.ai_attempts
    assert first["violations"] == ["unknown_flag_id: F99"] and first["raw"]
    assert second["violations"] == [] and second["error"] is None
    assert sample.ai_json is not None
    retries = [violations for _, violations in ranker.calls if violations]
    assert len(retries) == run.flagged and retries[0] == ["unknown_flag_id: F99"]


def test_two_wrong_answers_fall_back_to_the_rule_order_for_that_candidate(db, sim, clock):
    ranker = Scripted(hallucinating)
    run = rank_sitting(db, sim.sitting_id, ranker, clock)

    assert run.statuses == {"fallback": run.flagged}
    assert all(r.ai_json is None and len(r.ai_attempts) == 2 for r in run.rankings)
    assert [r.session_id for r in run.rankings] == [
        o.session.id for o in rule_order(db, sim.sitting_id)
    ]
    assert all(r.explanation.startswith("Rules only:") for r in run.rankings)


def test_ollama_being_down_keeps_every_candidate_in_the_rule_order(db, sim, clock):
    class Down:
        name, model = "ollama", "qwen-test"

        def assess(self, packet, violations=None):
            raise RankerError("ollama could not be reached", raw=None)

    run = rank_sitting(db, sim.sitting_id, Down(), clock)

    assert run.flagged == len(run.rankings) == db.scalar(select(func.count()).select_from(Ranking))
    assert run.statuses == {"fallback": run.flagged}
    assert [r.session_id for r in run.rankings] == [
        o.session.id for o in rule_order(db, sim.sitting_id)
    ]
    assert run.rankings[0].ai_attempts[0]["error"] == "ollama could not be reached"


def test_an_unusable_answer_then_a_good_one_is_a_retry_that_says_what_went_wrong(db, sim, clock):
    def plan(packet, attempt, violations):
        if attempt == 1:
            raise RankerError("the answer broke the schema: 2 problems", raw="{not json")
        return passing(packet)

    ranker = Scripted(plan)
    run = rank_sitting(db, sim.sitting_id, ranker, clock)

    assert run.statuses == {"retried": run.flagged}
    assert run.rankings[0].ai_attempts[0]["raw"] == "{not json"
    sent = next(v for _, v in ranker.calls if v)
    assert "unusable" in sent[0] and "schema" in sent[0]


def test_the_seconds_an_ai_spent_on_a_candidate_are_recorded(db, sim, clock):
    ranker = Scripted(always(3), clock=clock, seconds_per_call=4)
    run = rank_sitting(db, sim.sitting_id, ranker, clock)
    assert run.seconds == [4.0] * run.flagged
    assert all(r.ai_seconds == 4.0 for r in run.rankings)

    two = Scripted(
        lambda p, a, v: hallucinating(p, a, v) if a == 1 else passing(p),
        clock=clock,
        seconds_per_call=4,
    )
    again = rank_sitting(db, sim.sitting_id, two, clock)
    assert again.seconds == [8.0] * again.flagged


def test_ranking_again_replaces_the_earlier_run(db, sim, clock):
    rank_sitting(db, sim.sitting_id, Scripted(always(2)), clock)
    run = rank_sitting(db, sim.sitting_id, None, clock)
    assert db.scalar(select(func.count()).select_from(Ranking)) == run.flagged
    assert {r.ai_status for r in rankings(db).values()} == {"not_run"}


def test_ranking_a_sitting_nobody_was_flagged_in_is_an_empty_run(db, seeded, clock):
    run = rank_sitting(db, seeded.sitting_id, Scripted(always(3)), clock)
    assert run.flagged == 0 and run.rankings == []


# -------------------------------------------------------------- what the reviewer then sees


def test_the_queue_follows_the_stored_ranking_and_shows_the_ai_strength(
    client, db, sim, clock, staff
):
    ordered = [o for o in rule_order(db, sim.sitting_id) if not o.logging_only]
    last = ordered[-1].session.candidate_id
    rank_sitting(
        db,
        sim.sitting_id,
        Scripted(lambda p, a, v: passing(p, 5 if p["candidate_id"] == last else 2)),
        clock,
    )

    items = client.get("/api/review/queue", headers=staff).json()["items"]

    assert items[0]["candidate_id"] == last and items[0]["rank"] == 1
    assert items[0]["ai_strength"] == 5 and items[0]["ai_status"] == "ok"
    assert [i["rank"] for i in items] == list(range(1, len(items) + 1))
    lanes = [i["logging_only"] for i in items]
    assert lanes == sorted(lanes)


def test_the_candidate_page_shows_the_ais_account_when_it_passed(client, db, sim, clock, staff):
    rank_sitting(db, sim.sitting_id, Scripted(always(4)), clock)
    candidate = client.get("/api/review/queue", headers=staff).json()["items"][0]["candidate_id"]

    detail = client.get(f"/api/review/candidates/{candidate}", headers=staff).json()

    assert detail["explanation"]["source"] == "ai" and detail["explanation"]["status"] == "ok"
    assert detail["explanation"]["strength"] == 4
    assert detail["explanation"]["text"] == "F1 is the first of the flags in this packet."
    assert detail["rank"] == 1


def test_the_candidate_page_says_so_when_the_ai_fell_back_and_shows_the_rules_account(
    client, db, sim, clock, staff
):
    rank_sitting(db, sim.sitting_id, Scripted(hallucinating), clock)
    candidate = client.get("/api/review/queue", headers=staff).json()["items"][0]["candidate_id"]

    detail = client.get(f"/api/review/candidates/{candidate}", headers=staff).json()

    assert (
        detail["explanation"]["source"] == "rules" and detail["explanation"]["status"] == "fallback"
    )
    assert detail["explanation"]["text"].startswith("Rules only:")
    assert detail["explanation"]["strength"] is None


def test_a_stored_ranking_that_no_longer_matches_the_flags_is_not_trusted(
    client, db, sim, clock, staff
):
    ordered = rule_order(db, sim.sitting_id)
    rank_sitting(db, sim.sitting_id, Scripted(always(3)), clock)
    victim = ordered[0].session
    db.execute(delete(Flag).where(Flag.session_id == victim.id))  # they lose their only flags
    db.flush()

    items = client.get("/api/review/queue", headers=staff).json()["items"]

    assert victim.candidate_id not in {i["candidate_id"] for i in items}
    assert all(i["ai_status"] == "not_run" for i in items)  # the rules decide until it is re-ranked
    assert len(items) == len(ordered) - 1


@pytest.mark.parametrize("provider_status", ["ok", "fallback"])
def test_the_final_order_is_a_strict_ranking_of_everyone_flagged(db, sim, clock, provider_status):
    ranker = Scripted(always(3) if provider_status == "ok" else hallucinating)
    run = rank_sitting(db, sim.sitting_id, ranker, clock)
    assert sorted(r.final_rank for r in run.rankings) == list(range(1, run.flagged + 1))
    assert len({r.session_id for r in run.rankings}) == run.flagged
