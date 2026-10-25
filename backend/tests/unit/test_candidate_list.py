from app.services.candidate_list import parse
from app.services.mail import mask, render

# what the result emails are filled in with (services/outcomes.py: compose)
RESULT_VALUES = {
    "result_line": "Your result: 9 of 12 questions correct. The pass mark for this sitting was 10.",
    "appeal_email": "appeals@example.test",
    "candidate_id": "cand-001",
    "reason": "During the test your screen left the test page or left full screen more than once.",
}


def names_and_emails(raw, already=frozenset()):
    people, problems = parse(raw, already)
    return [(p.name, p.email) for p in people], [(p.line, p.reason) for p in problems]


def test_every_way_of_writing_a_person_reads_the_same():
    raw = (
        "Ada Lovelace, ada@example.org\n"
        "grace@navy.test;Grace Hopper\n"
        "Alan Turing <alan@bletchley.test>\n"
        '"Hamilton, Margaret"\tmargaret@nasa.test\n'
    )
    people, problems = names_and_emails(raw)
    assert problems == []
    assert people == [
        ("Ada Lovelace", "ada@example.org"),
        ("Grace Hopper", "grace@navy.test"),
        ("Alan Turing", "alan@bletchley.test"),
        ("Hamilton, Margaret", "margaret@nasa.test"),
    ]


def test_a_header_row_and_blank_lines_are_skipped_and_emails_are_lower_cased():
    people, problems = names_and_emails("\nName,Email\n\n  Ada   Lovelace , ADA@Example.ORG \n")
    assert problems == []
    assert people == [("Ada Lovelace", "ada@example.org")]


def test_each_problem_is_pointed_at_by_line_number_and_good_lines_still_count():
    raw = (
        "Ada Lovelace, ada@example.org\n"  # 1 fine
        "Bob, not-an-email\n"  # 2
        "carol@example.org\n"  # 3 no name
        "Ada Again, ADA@example.org\n"  # 4 the same email as line 1
        "Dan, dan@example.org\n"  # 5 fine
        "Eve, eve@example.org\n"  # 6 already invited
    )
    people, problems = names_and_emails(raw, frozenset({"eve@example.org"}))
    assert [name for name, _ in people] == ["Ada Lovelace", "Dan"]
    assert problems == [
        (2, "bad_email"),
        (3, "name_missing"),
        (4, "repeated"),
        (6, "already_invited"),
    ]


def test_a_very_long_name_is_refused():
    assert names_and_emails(f"{'x' * 201}, long@example.org")[1] == [(1, "name_too_long")]


def test_an_email_is_masked_for_lists_and_the_name_is_put_in_by_value():
    assert mask("jane.doe@gmail.com") == "j***@gmail.com"
    assert mask(None) is None
    subject, body = render("passed", name="Zoe {curly} Brace", **RESULT_VALUES)
    assert "Dear Zoe {curly} Brace," in body and subject


def test_result_emails_never_mention_what_the_system_saw():
    """Nothing about flags, video, the camera or the AI in any of them. The email sent after a
    person reviewed a sitting is the one place "review" belongs: it says a person looked."""
    watched = ("flag", "video", "integrity", "cheat", " ai ", "camera", "threshold", "weight")
    for kind in ("passed", "not_passed_score", "not_passed_review"):
        _, body = render(kind, name="Ada", **RESULT_VALUES)
        text = body.lower()
        for word in watched:
            assert word not in text, (kind, word)
        if kind != "not_passed_review":
            assert "review" not in text, kind


def test_every_result_email_tells_the_candidate_where_to_write_and_whom_to_quote():
    for kind in ("not_passed_score", "not_passed_review"):
        _, body = render(kind, name="Ada", **RESULT_VALUES)
        assert "appeals@example.test" in body and "cand-001" in body, kind
    _, passed = render("passed", name="Ada", **RESULT_VALUES)
    assert "9 of 12" in passed and "pass mark" in passed.lower()
