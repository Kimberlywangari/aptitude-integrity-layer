"""Invitations belong to a sitting: a code made for a sitting opens that sitting's paper, whichever
other sittings are open, and the candidate sits what the sitting asked for, for as long as it says.

The same holds whatever the questions come from: the practice bank, Cytonn's questions (with their
pictures) or questions an AI writes for each candidate.
"""

import csv
import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.staff_token import issue_staff_token
from app.models import Candidate, Question, QuestionImage, SessionQuestion, Sitting
from app.services.cytonn_bank import load_bank, parse_sections
from app.services.cytonn_images import ImageBlob
from app.services.qgen import jobs, paper
from app.services.staff_auth import create_reviewer
from tests.integration.test_ai_papers import FactoryWriter
from tests.support import Live

PASSWORD = "correct horse battery"
PNG = b"\x89PNG\r\n\x1a\n" + b"fake picture " * 10


@pytest.fixture
def admin_headers(db, clock, settings):
    account, _ = create_reviewer(
        db, clock, email="boss@example.com", password=PASSWORD, role="admin"
    )
    token = issue_staff_token(settings.session_secret, clock, account.id, account.password_hash)
    return {"Authorization": f"Bearer {token}"}


def sitting_of(client, headers, name, per_section, mode="practice", **extra):
    body = {
        "name": name,
        "per_section": per_section,
        "question_mode": mode,
    } | extra
    response = client.post("/api/admin/sittings", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def invites_for(client, headers, sitting_id=None, count=1):
    body = {"count": count} | ({} if sitting_id is None else {"sitting_id": sitting_id})
    return client.post("/api/admin/invites", json=body, headers=headers)


def sections_on_paper(db, session_id):
    return sorted(
        db.scalars(
            select(Question.section)
            .join(SessionQuestion, SessionQuestion.question_id == Question.id)
            .where(SessionQuestion.session_id == session_id)
        )
    )


def start(client, db, code):
    return Live(client, db, code).start()


# ---------------------------------------- a code opens the sitting it was made for


def test_a_code_opens_its_own_sitting_even_when_a_newer_one_is_open(
    client, db, seeded, admin_headers
):
    older = sitting_of(client, admin_headers, "Older", {"numerical": 2, "verbal": 2})
    newer = sitting_of(client, admin_headers, "Newer", {"logical": 3})

    made = invites_for(client, admin_headers, older["id"], count=2).json()
    assert (made["sitting_id"], made["sitting_name"]) == (older["id"], "Older")
    for item in made["invites"]:
        assert db.get(Candidate, item["candidate_id"]).sitting_id == older["id"]
        live = start(client, db, item["code"])
        assert live.session().sitting_id == older["id"]
        assert sections_on_paper(db, live.session_id) == ["numerical"] * 2 + ["verbal"] * 2

    other = invites_for(client, admin_headers, newer["id"]).json()["invites"][0]
    live = start(client, db, other["code"])
    assert sections_on_paper(db, live.session_id) == ["logical"] * 3


def test_each_sitting_keeps_its_own_time_and_its_own_number_of_questions(
    client, db, clock, seeded, admin_headers
):
    short = sitting_of(client, admin_headers, "Short", {"numerical": 2})
    long = sitting_of(client, admin_headers, "Long", {"verbal": 5})

    for sitting, total, seconds in ((short, 2, 210), (long, 5, 525)):  # 105 s a question
        code = invites_for(client, admin_headers, sitting["id"]).json()["invites"][0]["code"]
        live = start(client, db, code)
        assert live.begin().json()["remaining_s"] == seconds
        assert live.question().json()["total"] == total
        live.answer_everything(clock)
        assert live.session().status == "finished"


def test_a_sitting_that_has_not_opened_or_has_closed_cannot_be_started(
    client, db, clock, seeded, admin_headers
):
    opens = (clock.now() + timedelta(hours=2)).isoformat()
    future = sitting_of(client, admin_headers, "Later", {"numerical": 2}, opens_at=opens)
    code = invites_for(client, admin_headers, future["id"]).json()["invites"][0]["code"]
    refused = client.post("/api/session/start", json={"token": code})
    assert (refused.status_code, refused.json()["code"]) == (403, "sitting_not_open_yet")
    assert refused.json()["opens_at"] == opens  # early, not closed: the page can say when

    clock.advance(3 * 3600)  # now it is open
    assert client.post("/api/session/start", json={"token": code}).status_code == 200

    other = sitting_of(client, admin_headers, "Short run", {"verbal": 2})
    second = invites_for(client, admin_headers, other["id"]).json()["invites"][0]["code"]
    url = f"/api/admin/sittings/{other['id']}/close"
    client.post(url, json={"force": True}, headers=admin_headers)
    closed = client.post("/api/session/start", json={"token": second})
    assert (closed.status_code, closed.json()["code"]) == (403, "no_open_sitting")


def test_starting_again_returns_the_same_session_and_the_same_paper(
    client, db, seeded, admin_headers
):
    sitting = sitting_of(client, admin_headers, "Once", {"numerical": 3})
    code = invites_for(client, admin_headers, sitting["id"]).json()["invites"][0]["code"]
    first = start(client, db, code)
    again = start(client, db, code)
    assert again.session_id == first.session_id
    assert sections_on_paper(db, first.session_id) == ["numerical"] * 3


# ---------------------------------------- which sitting, when not said


def test_without_a_named_sitting_the_only_open_one_is_used(client, db, seeded, admin_headers):
    made = invites_for(client, admin_headers).json()  # seeded has exactly one open sitting
    only = db.scalar(select(Sitting).where(Sitting.status == "open"))
    assert made["sitting_id"] == only.id


def test_with_several_open_it_must_be_said_which(client, db, seeded, admin_headers):
    a = sitting_of(client, admin_headers, "A", {"numerical": 2})
    b = sitting_of(client, admin_headers, "B", {"verbal": 2})
    response = invites_for(client, admin_headers)
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "sitting_required"
    assert {a["id"], b["id"]} <= set(body["sittings"])
    assert db.scalar(select(Candidate.id).where(Candidate.id == "cand-021")) is None  # none made


def test_no_open_sitting_a_closed_one_and_an_unknown_one_are_refused(
    client, db, seeded, admin_headers
):
    sitting = sitting_of(client, admin_headers, "Gone", {"numerical": 2})
    url = f"/api/admin/sittings/{sitting['id']}/close"
    client.post(url, json={"force": True}, headers=admin_headers)
    closed = invites_for(client, admin_headers, sitting["id"])
    assert (closed.status_code, closed.json()["code"]) == (409, "sitting_closed")
    unknown = invites_for(client, admin_headers, 99999)
    assert (unknown.status_code, unknown.json()["code"]) == (404, "sitting_not_found")

    for open_one in db.scalars(select(Sitting).where(Sitting.status == "open")):
        open_one.status = "closed"
    db.flush()
    none = invites_for(client, admin_headers)
    assert (none.status_code, none.json()["code"]) == (409, "no_open_sitting")


# ---------------------------------------- what the admin sees


def test_the_sitting_list_counts_each_sittings_own_invitations(client, db, seeded, admin_headers):
    a = sitting_of(client, admin_headers, "A", {"numerical": 2})
    b = sitting_of(client, admin_headers, "B", {"verbal": 2})
    invites_for(client, admin_headers, a["id"], count=3)
    codes = invites_for(client, admin_headers, b["id"], count=2).json()["invites"]
    start(client, db, codes[0]["code"])  # one of B's opens their link

    listed = {
        s["name"]: s["counts"]
        for s in client.get("/api/admin/sittings", headers=admin_headers).json()["sittings"]
    }
    assert listed["A"]["not_started"] == 3
    # B is the newest open sitting, so it also holds the seeded codes that were never given one
    assert listed["B"]["not_started"] == 2 + len(seeded.invites)


def test_the_invite_list_names_the_sitting_and_can_be_filtered(client, db, seeded, admin_headers):
    a = sitting_of(client, admin_headers, "Alpha", {"numerical": 2})
    b = sitting_of(client, admin_headers, "Beta", {"verbal": 2})
    made_a = invites_for(client, admin_headers, a["id"], count=2).json()["invites"]
    invites_for(client, admin_headers, b["id"], count=1)

    everyone = client.get("/api/admin/invites", headers=admin_headers).json()
    by_id = {i["candidate_id"]: i for i in everyone["invites"]}
    assert by_id[made_a[0]["candidate_id"]]["sitting_name"] == "Alpha"
    assert by_id["cand-001"]["sitting_id"] is None  # made before invitations had a sitting

    only_alpha = client.get(f"/api/admin/invites?sitting={a['id']}", headers=admin_headers).json()
    assert only_alpha["total"] == 2
    assert {i["sitting_name"] for i in only_alpha["invites"]} == {"Alpha"}


def test_an_invitation_made_before_sittings_had_their_own_still_opens_the_newest(
    client, db, seeded, admin_headers
):
    older = sitting_of(client, admin_headers, "Older", {"numerical": 2})
    newest = sitting_of(client, admin_headers, "Newest", {"verbal": 3})
    live = Live(client, db, seeded.invites[0].token).start()  # an unassigned, seeded code
    assert live.session().sitting_id == newest["id"] != older["id"]


# ---------------------------------------- the three kinds of question


def test_an_ai_sitting_writes_each_candidates_paper_after_they_open_their_code(
    client, db, seeded, admin_headers, monkeypatch
):
    monkeypatch.setattr("app.api.admin.check_available", lambda settings: (True, "Stub."))
    launched: list[str] = []
    monkeypatch.setattr(jobs, "launch", lambda session_id: launched.append(session_id) or True)
    sitting = sitting_of(
        client, admin_headers, "Written", {"numerical": 1, "logical": 1}, mode="ai"
    )
    codes = invites_for(client, admin_headers, sitting["id"], count=2).json()["invites"]

    lives = [start(client, db, item["code"]) for item in codes]
    assert launched == [live.session_id for live in lives]
    assert all(live.session().paper_status == "pending" for live in lives)
    assert all(live.begin().status_code == 409 for live in lives)  # not before the questions exist

    for index, live in enumerate(lives):
        writer = FactoryWriter(start=index * 500)  # each candidate's questions are their own
        assert paper.write_paper(db, live.session_id, writer) == "ready"
    papers = [sections_on_paper(db, live.session_id) for live in lives]
    assert papers == [["logical", "numerical"]] * 2
    texts = [
        set(
            db.scalars(
                select(Question.text)
                .join(SessionQuestion, SessionQuestion.question_id == Question.id)
                .where(SessionQuestion.session_id == live.session_id)
            )
        )
        for live in lives
    ]
    assert texts[0].isdisjoint(texts[1])  # every candidate has questions of their own
    assert lives[0].begin().json()["remaining_s"] == 2 * 105


def test_the_practice_bank_and_cytonns_questions_never_mix(client, db, seeded, admin_headers):
    load_cytonn(db)
    practice = sitting_of(client, admin_headers, "Practice", {"numerical": 3, "verbal": 3})
    real = sitting_of(client, admin_headers, "Real", {"numerical": 3, "verbal": 3}, mode="cytonn")
    for sitting, source in ((practice, "synthetic"), (real, "cytonn")):
        code = invites_for(client, admin_headers, sitting["id"]).json()["invites"][0]["code"]
        live = start(client, db, code)
        sources = set(
            db.scalars(
                select(Question.source)
                .join(SessionQuestion, SessionQuestion.question_id == Question.id)
                .where(SessionQuestion.session_id == live.session_id)
            )
        )
        assert sources == {source}


def test_a_cytonn_sitting_cannot_be_made_before_cytonns_questions_are_loaded(
    client, db, seeded, admin_headers
):
    body = {"name": "Early", "per_section": {"numerical": 2}}
    response = client.post(
        "/api/admin/sittings", json=body | {"question_mode": "cytonn"}, headers=admin_headers
    )
    assert (response.status_code, response.json()["code"]) == (409, "cytonn_not_loaded")


def test_a_cytonn_sitting_checks_what_cytonn_has_in_each_section(client, db, seeded, admin_headers):
    load_cytonn(db, per_section=4)
    body = {"name": "Greedy", "question_mode": "cytonn"}
    short = client.post(
        "/api/admin/sittings", json=body | {"per_section": {"numerical": 5}}, headers=admin_headers
    )
    assert (short.status_code, short.json()["code"]) == (409, "section_too_small")
    assert short.json()["sections"] == [{"section": "numerical", "available": 4, "needed": 5}]
    odd = client.post(
        "/api/admin/sittings", json=body | {"per_section": {"astrology": 1}}, headers=admin_headers
    )
    assert (odd.status_code, odd.json()["code"]) == (422, "unknown_section")


def test_a_candidate_sits_a_whole_cytonn_paper_pictures_and_all(
    client, db, clock, seeded, admin_headers
):
    load_cytonn(db, per_section=6)
    sitting = sitting_of(
        client,
        admin_headers,
        "Cytonn day",
        {"numerical": 6, "verbal": 4},
        mode="cytonn",
    )
    code = invites_for(client, admin_headers, sitting["id"]).json()["invites"][0]["code"]
    live = start(client, db, code)
    assert live.begin().json()["remaining_s"] == 10 * 105

    seen_pictures = 0
    for _ in range(10):
        body = live.question().json()
        assert "[[image" not in body["text"] or body["images"]  # a marker always has a picture
        seen_pictures += len(body["images"])
        for url in body["images"]:
            fetched = client.get(url)
            assert fetched.status_code == 200
            assert fetched.headers["content-type"] == "image/png" and fetched.content == PNG
            assert "private" in fetched.headers["cache-control"]
        live.answer_one(clock, body["position"])
    assert seen_pictures == 3  # numerical questions 0, 2 and 4 carry one each
    assert live.session().status == "finished"


def test_a_picture_link_works_only_for_its_own_candidate_and_question(
    client, db, clock, seeded, admin_headers
):
    load_cytonn(db, per_section=6)
    sitting = sitting_of(client, admin_headers, "Pictures", {"numerical": 6}, mode="cytonn")
    codes = invites_for(client, admin_headers, sitting["id"], count=2).json()["invites"]
    one, two = (start(client, db, c["code"]) for c in codes)
    one.begin(), two.begin()

    url = None
    for _ in range(6):
        body = one.question().json()
        if body["images"]:
            url = body["images"][0]
            break
        one.answer_one(clock, body["position"])
    assert url is not None
    image_id = int(url.split("/image/")[1].split("?")[0])

    assert client.get(url).status_code == 200
    # someone else's session cannot use it
    foreign = url.replace(one.session_id, two.session_id)
    assert client.get(foreign).status_code == 403
    # a made-up token, no token, and a token for another picture
    assert client.get(url.split("?")[0] + "?t=garbage").status_code == 403
    assert client.get(url.split("?")[0]).status_code == 403
    other_id = db.scalar(select(QuestionImage.id).where(QuestionImage.id != image_id))
    assert client.get(url.replace(f"/image/{image_id}", f"/image/{other_id}")).status_code == 403
    # the link goes stale
    clock.advance(7 * 3600)
    assert client.get(url).status_code == 403


def test_a_picture_that_is_not_on_the_candidates_paper_is_refused_even_with_a_valid_link(
    client, db, clock, seeded, admin_headers, settings
):
    from app.core.image_url import issue_image_token

    load_cytonn(db, per_section=6)
    sitting = sitting_of(client, admin_headers, "Narrow", {"numerical": 1}, mode="cytonn")
    code = invites_for(client, admin_headers, sitting["id"]).json()["invites"][0]["code"]
    live = start(client, db, code)
    on_paper = set(
        db.scalars(
            select(SessionQuestion.question_id).where(SessionQuestion.session_id == live.session_id)
        )
    )
    elsewhere = db.scalar(
        select(QuestionImage.id).where(QuestionImage.question_id.not_in(on_paper))
    )
    token = issue_image_token(settings.session_secret, clock, live.session_id, elsewhere)
    refused = client.get(f"/api/session/{live.session_id}/image/{elsewhere}?t={token}")
    assert (refused.status_code, refused.json()["code"]) == (404, "image_not_found")


# ---------------------------------------- the terminal job


def test_the_terminal_job_makes_codes_for_a_sitting_and_writes_the_links(
    client, db, seeded, admin_headers, monkeypatch, tmp_path
):
    from scripts import create_invites

    sitting = sitting_of(client, admin_headers, "By terminal", {"numerical": 2})

    class Borrowed:
        def __enter__(self):
            return db

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("app.db.SessionLocal", lambda: Borrowed())
    out = tmp_path / "codes.csv"
    create_invites.main(["--sitting", "By terminal", "--count", "3", "--out", str(out)])

    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [r["candidate_id"] for r in rows] == ["cand-021", "cand-022", "cand-023"]
    assert all(r["sitting"] == "By terminal" for r in rows)
    assert all(r["url"].endswith(f"?t={r['token']}") for r in rows)
    live = start(client, db, rows[0]["token"])  # the code in the file works, typed as written
    assert live.session().sitting_id == sitting["id"]
    with pytest.raises(SystemExit, match="no sitting matches"):
        create_invites.main(["--sitting", "Nope", "--out", str(out)])


# ---------------------------------------- helpers


def load_cytonn(db, per_section=6):
    """A small Cytonn bank: numerical (every other question has a picture) and verbal."""
    pictures: dict[str, ImageBlob] = {}
    sections = []
    for name, base in (("Numerical", 1000), ("Verbal", 2000)):
        questions = []
        for i in range(per_section):
            qid = base + i
            html = f"<p>{name} question {qid}: how many of item {qid} remain?</p>"
            if name == "Numerical" and i % 2 == 0:
                url = f"https://hr.cytonn.com/../storage/aptitude/q{qid}.PNG"
                html += f'<p><img src="{url}" alt=""></p>'
                clean = f"https://hr.cytonn.com/storage/aptitude/q{qid}.PNG"
                pictures[clean] = ImageBlob("image/png", PNG, hashlib.sha256(PNG).hexdigest())
            questions.append(
                {
                    "id": qid,
                    "question": html,
                    "answers": [
                        {"id": qid * 10 + 1, "answer": "&pound;17", "is_correct": False},
                        {"id": qid * 10 + 2, "answer": "&pound;19", "is_correct": True},
                        {"id": qid * 10 + 3, "answer": "&pound;21", "is_correct": False},
                    ],
                }
            )
        sections.append(
            {"id": base, "name": name, "time_per_question": "1.75", "questions": questions}
        )
    bank = parse_sections({"data": sections})
    result = load_bank(db, bank, images=pictures)
    assert result.created == 2 * per_section and not result.no_image
    return bank


def test_an_older_code_is_told_when_the_only_open_sitting_has_not_opened_yet(
    client, db, clock, seeded
):
    only = db.scalar(select(Sitting).where(Sitting.status == "open"))
    only.opens_at = clock.now() + timedelta(hours=5)
    db.flush()

    refused = client.post("/api/session/start", json={"token": seeded.invites[0].token})

    assert (refused.status_code, refused.json()["code"]) == (403, "sitting_not_open_yet")
    assert refused.json()["opens_at"] == only.opens_at.isoformat()
