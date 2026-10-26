"""A candidate's name and email exist for the invitation and result emails and the admin's list.
Nothing the AI reads and nothing a reviewer sees may carry them. This test gives every simulated
candidate a name and an address nobody would otherwise write, then looks everywhere those could
have leaked: the evidence packets, the exact text sent to a model, and every reviewer screen."""

import json

import pytest
from sqlalchemy import select

from app.models import Candidate, EmailOutbox, Sitting, TestSession
from app.services.packets import build_packet
from app.services.ranking import prompts
from app.services.staff_auth import create_reviewer
from scripts.simulate_cohort import SITTING_NAME, simulate

PASSWORD = "correct horse battery"
SURNAME = "Quillfeather"
DOMAIN = "privacy-check.invalid"


@pytest.fixture
def named(db, seeded):
    sim = simulate(db, seed=1)
    db.flush()
    for number, candidate in enumerate(
        db.scalars(select(Candidate).where(Candidate.id.like("sim-%"))), start=1
    ):
        candidate.full_name = f"Zed {SURNAME}{number}"
        candidate.email = f"zed.{SURNAME.lower()}{number}@{DOMAIN}"
    assert number >= 10  # the names really are on the candidates being checked
    db.flush()
    return sim


def mentions(text: str) -> list[str]:
    return [needle for needle in (SURNAME, SURNAME.lower(), DOMAIN, "@") if needle in text]


def test_packets_and_the_text_sent_to_a_model_never_hold_a_name_or_an_address(db, named):
    sessions = list(db.scalars(select(TestSession).where(TestSession.candidate_id.like("sim-%"))))
    built = 0
    for session in sessions:
        packet = build_packet(db, session)
        if packet is None:  # not flagged: there is no packet to read
            continue
        built += 1
        assert mentions(json.dumps(packet)) == []
        for violations in (None, ["a cited time that is not in the packet"]):
            sent = json.dumps(prompts.build_messages(packet, violations))
            assert mentions(sent) == []
    assert built >= 3


def test_no_reviewer_screen_carries_a_name_or_an_address(client, db, clock, named):
    account, _ = create_reviewer(db, clock, email="rev-only@staff.test", password=PASSWORD)
    db.flush()
    token = client.post(
        "/api/review/login", json={"email": "rev-only@staff.test", "password": PASSWORD}
    ).json()["token"]
    staff = {"Authorization": f"Bearer {token}"}
    sitting = db.scalar(select(Sitting.id).where(Sitting.name == SITTING_NAME))

    queue = client.get("/api/review/queue", params={"sitting": sitting}, headers=staff).json()
    listed = client.get("/api/review/candidates", params={"sitting": sitting}, headers=staff).json()
    looked_at = [i["candidate_id"] for i in queue["items"]][:3]
    pages = [queue, listed, client.get("/api/review/overview", headers=staff).json()]
    for candidate_id in looked_at:
        base = f"/api/review/candidates/{candidate_id}"
        for tail in ("", "/events"):
            response = client.get(base + tail, params={"sitting": sitting}, headers=staff)
            assert response.status_code == 200, response.text
            pages.append(response.json())
    pages.append(client.get("/api/review/audit", headers=staff).json())

    assert len(pages) >= 6
    for page in pages:
        # the audit log shows which reviewer did what, so staff addresses may appear; no other @
        text = json.dumps(page).replace("rev-only@staff.test", "")
        assert mentions(text) == []


def test_the_outcomes_list_and_a_recorded_result_never_leak_a_name_to_a_reviewer(
    client, db, clock, named
):
    """The new screens: the outcomes list, the result panel on a candidate's page, passing someone
    and the audit entry that leaves. The email itself does carry the name (that is its job)."""
    create_reviewer(db, clock, email="rev-only@staff.test", password=PASSWORD)
    db.flush()
    token = client.post(
        "/api/review/login", json={"email": "rev-only@staff.test", "password": PASSWORD}
    ).json()["token"]
    staff = {"Authorization": f"Bearer {token}"}
    sitting = db.scalar(select(Sitting.id).where(Sitting.name == SITTING_NAME))
    params = {"sitting": sitting}

    listed = client.get("/api/review/outcomes", params=params, headers=staff)
    assert listed.status_code == 200
    target = next(i["candidate_id"] for i in listed.json()["items"] if i["can_mark_passed"])
    passed = client.post(
        f"/api/review/candidates/{target}/result",
        params=params,
        json={"result": "pass"},
        headers=staff,
    )
    assert passed.status_code == 200, passed.text

    pages = [
        listed.json(),
        passed.json(),
        client.get("/api/review/outcomes", params=params, headers=staff).json(),
        client.get(f"/api/review/candidates/{target}", params=params, headers=staff).json(),
        client.get("/api/review/audit", headers=staff).json(),
    ]
    for page in pages:
        text = json.dumps(page).replace("rev-only@staff.test", "")
        assert mentions(text) == []

    queued = db.scalar(select(EmailOutbox).where(EmailOutbox.candidate_id == target))
    assert SURNAME in queued.body  # the one place a name belongs


def test_processing_a_sitting_reports_and_logs_no_name(
    client, db, clock, settings, named, monkeypatch
):
    """The Process sitting button: what it reports on the admin's page and the audit line it
    leaves, which reviewers can read, carry counts only."""
    from app.core.staff_token import issue_staff_token
    from app.services import processing

    account, _ = create_reviewer(
        db, clock, email="boss@staff.test", password=PASSWORD, role="admin"
    )
    db.flush()
    admin = {
        "Authorization": "Bearer "
        + issue_staff_token(settings.session_secret, clock, account.id, account.password_hash)
    }
    sitting = db.scalar(select(Sitting.id).where(Sitting.name == SITTING_NAME))
    steps = processing.process_sitting(db, sitting, settings, clock, None, use_video=False)
    assert len(steps) == 5

    monkeypatch.setattr(processing, "launch", lambda sitting_id, clock=None: True)
    url = f"/api/admin/sittings/{sitting}/process"
    started = client.post(url, headers=admin)
    status = client.get(url, headers=admin)
    audit = client.get("/api/review/audit", headers=admin)
    assert started.status_code == status.status_code == audit.status_code == 200

    for page in (started.json(), status.json(), audit.json()):
        text = json.dumps(page).replace("boss@staff.test", "")
        assert mentions(text) == []
    assert status.json()["last_ranked_at"] is not None  # the rankings really were written
