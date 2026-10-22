import httpx
import pytest

from app.config import Settings
from app.services.cytonn_bank import LoadResult, parse_sections
from scripts.fetch_cytonn_bank import FetchError, _report, fetch_sections

KEY = "k3y-that-must-never-be-printed-0123456"
BASE = "https://hr.example/api/aptitude"


def client_answering(status, body=b'{"data": []}', seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_it_asks_for_sections_with_the_key_in_the_header_only():
    seen: list[httpx.Request] = []
    body = fetch_sections(BASE + "/", KEY, client=client_answering(200, seen=seen))

    assert body == b'{"data": []}'
    (request,) = seen
    assert request.method == "GET"
    assert str(request.url) == BASE + "/sections"
    assert request.headers["X-API-KEY"] == KEY
    assert KEY not in str(request.url)


def test_a_rejected_key_says_so_without_repeating_the_key():
    with pytest.raises(FetchError) as problem:
        fetch_sections(BASE, KEY, client=client_answering(401, b'{"error": "Unauthorized"}'))
    assert "401" in str(problem.value)
    assert KEY not in str(problem.value)


def test_the_key_is_read_from_the_x_api_key_line_of_the_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"X-API-KEY={KEY}\n", encoding="utf-8")

    assert Settings(_env_file=env_file).aptitude_api_key == KEY
    assert Settings(_env_file=None).aptitude_api_key == ""


def test_a_missing_key_is_caught_before_any_request():
    seen: list[httpx.Request] = []
    with pytest.raises(FetchError, match="X-API-KEY"):
        fetch_sections(BASE, "", client=client_answering(200, seen=seen))
    assert seen == []


@pytest.mark.parametrize(("status", "word"), [(429, "rate limiting"), (500, "500"), (404, "404")])
def test_other_answers_are_explained(status, word):
    with pytest.raises(FetchError, match=word):
        fetch_sections(BASE, KEY, client=client_answering(status))


def test_a_network_failure_is_reported_without_the_key():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client = httpx.Client(transport=httpx.MockTransport(refuse))
    with pytest.raises(FetchError, match="could not reach") as problem:
        fetch_sections(BASE, KEY, client=client)
    assert KEY not in str(problem.value)


def test_the_report_lists_what_was_skipped_and_what_to_look_at(capsys):
    payload = {
        "data": [
            {
                "name": "Numerical Reasoning",
                "time_per_question": "1.5",
                "questions": [
                    {"id": 10, "question": "Fine?", "answers": [
                        {"id": 1, "answer": "yes", "is_correct": True},
                        {"id": 2, "answer": "no", "is_correct": False},
                    ]},
                    {"id": 11, "question": "Unmarked?", "answers": [
                        {"id": 3, "answer": "a", "is_correct": False},
                        {"id": 4, "answer": "b", "is_correct": False},
                    ]},
                ],
            }
        ]
    }
    bank = parse_sections(payload)
    result = LoadResult(
        created=1, kept_used=[7], missing_upstream=[8], by_section={"numerical reasoning": 1}
    )

    _report(bank, result, dry_run=True, source="a saved file")

    out = capsys.readouterr().out
    assert "1 questions created" in out and "would be applied from a saved file" in out
    assert "numerical reasoning" in out and "1.5 min per question" in out
    assert "1 questions skipped" in out and "no marking scheme" in out and "11" in out
    assert "already drawn" in out and "no longer in Cytonn's list" in out
