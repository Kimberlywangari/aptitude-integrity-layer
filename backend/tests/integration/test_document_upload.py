# ruff: noqa: F811
"""Uploading a document of any common kind: the endpoint, who may use it, and that what comes out
of it feeds the invite list and the question import the same way a pasted CSV does."""

from app.services import documents
from tests.integration.test_admin import (  # noqa: F401  (fixtures used by name)
    SUMMARY_HEADER,
    admin_headers,
    closed_bank,
    do_import,
    reviewer_headers,
)
from tests.unit.test_documents import PEOPLE, docx, paragraph, pdf, word_table, xlsx

URL = "/api/admin/extract-text"


def upload(client, headers, data, **params):
    sent = {**headers, "Content-Type": "application/octet-stream"}
    return client.post(URL, content=data, params=params, headers=sent)


def test_an_admin_gets_the_words_out_of_a_word_file(client, admin_headers):
    body = paragraph("Invitations") + word_table(PEOPLE[1:])
    done = upload(client, admin_headers, docx(body))
    assert done.status_code == 200, done.text
    assert done.json()["kind"] == "docx"
    assert "Ada Lovelace\tada@example.org" in done.json()["text"]


def test_a_spreadsheet_comes_back_as_csv_when_a_table_is_asked_for(client, admin_headers):
    done = upload(client, admin_headers, xlsx(PEOPLE), want="table")
    assert (done.status_code, done.json()["kind"]) == (200, "xlsx")
    assert (
        done.json()["text"]
        == "Name,Email\nAda Lovelace,ada@example.org\nGrace Hopper,grace@navy.test\n"
    )


def test_only_an_admin_may_upload(client, reviewer_headers):
    assert client.post(URL, content=b"hello").status_code == 401
    assert upload(client, reviewer_headers, b"hello,there\n").status_code == 403


def test_a_file_over_the_limit_is_turned_away_with_the_limit(client, admin_headers):
    done = upload(client, admin_headers, b"a," * (documents.MAX_BYTES // 2 + 1))
    assert (done.status_code, done.json()["code"]) == (413, "file_too_large")
    assert done.json()["max_mb"] == 5
    assert "PDF" in done.json()["formats"]  # and it says what would have been fine


def test_an_unknown_want_is_refused(client, admin_headers):
    assert upload(client, admin_headers, b"a,b\n", want="everything").status_code == 422


def test_what_cannot_be_read_says_why_in_a_code_the_page_can_word(client, admin_headers):
    old = upload(client, admin_headers, bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 600)
    assert (old.status_code, old.json()["code"]) == (415, "legacy_office_format")
    scanned = upload(client, admin_headers, pdf(None))
    assert (scanned.status_code, scanned.json()["code"]) == (422, "scanned_pdf")
    empty = upload(client, admin_headers, b"  \n")
    assert (empty.status_code, empty.json()["code"]) == (422, "empty_file")


def test_nothing_is_kept_of_an_upload(client, db, admin_headers):
    from sqlalchemy import select

    from app.models import AuditLog

    before = len(db.scalars(select(AuditLog)).all())
    upload(client, admin_headers, docx(paragraph("Ada Lovelace, ada@example.org")))
    assert len(db.scalars(select(AuditLog)).all()) == before  # no row, and no text in any row


# -------------------------------------------------------------- the two places it is used for


def test_a_spreadsheet_of_people_becomes_an_invite_list(client, seeded, admin_headers):
    text = upload(client, admin_headers, xlsx(PEOPLE)).json()["text"]
    preview = client.post(
        "/api/admin/invites/preview", json={"list_text": text}, headers=admin_headers
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert [p["email"] for p in body["people"]] == ["ada@example.org", "grace@navy.test"]
    assert body["problems"] == []


def test_a_pdf_of_people_becomes_an_invite_list_too(client, seeded, admin_headers):
    text = upload(client, admin_headers, pdf("Ada Lovelace, ada@example.org")).json()["text"]
    preview = client.post(
        "/api/admin/invites/preview", json={"list_text": text}, headers=admin_headers
    )
    assert [p["email"] for p in preview.json()["people"]] == ["ada@example.org"]


def test_a_spreadsheet_or_word_table_of_questions_imports_like_a_csv(
    client, closed_bank, admin_headers
):
    header = SUMMARY_HEADER.split(",")
    row = ["Q001", "verbal", "b", "hard", 812, 38.5, 71, 50, 96]
    as_sheet = upload(client, admin_headers, xlsx([header, row]), want="table").json()["text"]
    as_csv = f"{SUMMARY_HEADER}\nQ001,verbal,b,hard,812,38.5,71,50,96\n"
    assert as_sheet == as_csv

    imported = do_import(client, admin_headers, as_sheet, filename="questions.xlsx")
    assert (imported.status_code, imported.json()["imported"]) == (200, 1)

    table = word_table([header, [str(c) for c in row]])
    as_word = upload(client, admin_headers, docx(table), want="table").json()["text"]
    assert as_word == as_csv


def test_a_pdf_of_questions_says_it_has_no_table_rather_than_guessing(client, admin_headers):
    done = upload(client, admin_headers, pdf("question_id, section, correct_option"), want="table")
    assert (done.status_code, done.json()["code"]) == (422, "no_table_found")
