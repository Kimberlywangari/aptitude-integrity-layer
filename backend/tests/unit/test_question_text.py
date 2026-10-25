"""Turning Cytonn's HTML into text a candidate's screen can show, and fetching its pictures."""

import random

import httpx
import pytest

from app.services import cytonn_images
from app.services.question_text import clean_image_url, strip_option_letters, to_plain
from app.services.shuffle import MAX_PER_PASSAGE, balanced_sample, blueprint_sample, draw

# --------------------------------------------------------------------------------- the text


@pytest.mark.parametrize(
    ("html", "plain"),
    [
        ("<p>One.</p><p>Two.</p>", "One.\n\nTwo."),
        ("<p>Line<br>break<br/>again</p>", "Line\nbreak\nagain"),
        ("Tom &amp; Jerry&nbsp;&rsquo;s &pound;5 &euro;6 &frac14;", "Tom & Jerry ’s £5 €6 ¼"),
        ("<p>  lots   of \t space </p>", "lots of space"),
        ("<p>&nbsp;</p><p>text</p><p>&nbsp;&nbsp;</p>", "text"),
        ("x<sup>2</sup> + y<sup>3</sup>", "x² + y³"),
        ("2<sup>n-1</sup>", "2ⁿ⁻¹"),
        ("e<sup>kt</sup>", "e^(kt)"),
        ("H<sub>2</sub>O", "H₂O"),
        ("the 2<sup>nd</sup> of 3<sup>rd</sup>", "the 2nd of 3rd"),
        ("<ol><li>First</li><li>Second</li></ol>", "1. First\n2. Second"),
        ("<ul><li>Red</li><li>Blue</li></ul>", "- Red\n- Blue"),
        ("<h3>Heading</h3><p>Body</p>", "Heading\n\nBody"),
        (
            '<span style="color:red">styled</span> <u>under</u> <strong>bold</strong>',
            "styled under bold",
        ),
        ("<style>p { color: red }</style><p>kept</p>", "kept"),
        ("", ""),
        ("plain text, no tags", "plain text, no tags"),
    ],
)
def test_html_becomes_plain_text(html, plain):
    assert to_plain(html)[0] == plain


def test_nothing_that_looks_like_markup_survives():
    messy = "<p>a <b>b</b> <script>alert(1)</script><a href='x'>link</a> &lt;not a tag&gt;</p>"
    text, _ = to_plain(messy)
    assert "<b>" not in text and "<script>" not in text and "alert" not in text
    assert text == "a b link <not a tag>"  # an escaped < was text all along


def test_pictures_become_markers_and_come_back_in_order():
    html = '<p>a</p><img src="https://h.test/x/../y/1.png"><p>b</p><img src="https://h.test/2.jpg">'
    text, images = to_plain(html)
    assert text == "a\n\n[[image 1]]\n\nb\n\n[[image 2]]"
    assert images == ["https://h.test/y/1.png", "https://h.test/2.jpg"]


def test_a_picture_without_a_usable_address_is_reported_as_none_with_its_marker_kept():
    text, images = to_plain('<p>see <img alt="x"> and <img src="ftp://h/p.png"></p>')
    assert images == [None, None]
    assert "[[image 1]]" in text and "[[image 2]]" in text


@pytest.mark.parametrize(
    ("src", "clean"),
    [
        ("https://hr.cytonn.com/../storage/aptitude/q92.PNG", "https://hr.cytonn.com/storage/aptitude/q92.PNG"),
        ("https://hr.cytonn.com/a/./b/../c.png", "https://hr.cytonn.com/a/c.png"),
        ("http://h.test/p.png?v=2#top", "http://h.test/p.png?v=2"),
        (" https://h.test/p.png ", "https://h.test/p.png"),
        ("/storage/relative.png", None),
        ("javascript:alert(1)", None),
        ("data:image/png;base64,AAAA", None),
        ("", None),
        (None, None),
    ],
)
def test_picture_addresses_are_cleaned_and_only_web_addresses_are_accepted(src, clean):
    assert clean_image_url(src) == clean


def test_letters_are_stripped_from_answers_only_when_all_have_them_in_order():
    assert strip_option_letters(["A. one", "B. two", "C. three"]) == ["one", "two", "three"]
    assert strip_option_letters(["A) one", "B) two"]) == ["one", "two"]
    assert strip_option_letters(["B. one", "A. two"]) == ["B. one", "A. two"]  # not in order
    assert strip_option_letters(["A. one", "two"]) == ["A. one", "two"]
    assert strip_option_letters(["A. one"]) == ["A. one"]  # one answer is not a list of letters


# ------------------------------------------------------------------------------- the pictures


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (b"GIF89a" + b"\x00" * 10, "image/gif"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"<html>please log in</html>", None),
        (b"", None),
    ],
)
def test_a_picture_is_recognised_by_its_first_bytes(data, kind):
    assert cytonn_images.sniff(data) == kind


def test_a_picture_is_fetched_and_labelled_by_what_it_is_not_by_what_the_server_says():
    def handler(request):
        return httpx.Response(200, content=PNG, headers={"content-type": "image/jpeg"})

    client = client_for(handler)
    blob = cytonn_images.fetch_one("https://hr.test/storage/q 1.PNG", "hr.test", client)
    assert blob.content_type == "image/png"  # the server called it a jpeg
    assert blob.data == PNG and len(blob.sha256) == 64


def test_only_https_on_the_allowed_host_is_ever_contacted():
    contacted = []

    def handler(request):
        contacted.append(str(request.url))
        return httpx.Response(200, content=PNG)

    client = client_for(handler)
    for url in ("http://hr.test/p.png", "https://evil.test/p.png", "https://hr.test.evil.test/p.png"):
        with pytest.raises(ValueError, match="not an https address on hr.test"):
            cytonn_images.fetch_one(url, "hr.test", client)
    assert contacted == []


@pytest.mark.parametrize(
    ("response", "why"),
    [
        (httpx.Response(404), "answered 404"),
        (httpx.Response(302, headers={"location": "https://evil.test/"}), "answered 302"),
        (httpx.Response(200, content=b"<html>login</html>"), "is not a picture"),
        (httpx.Response(200, content=PNG + b"\x00" * cytonn_images.MAX_BYTES), "over the"),
    ],
)
def test_a_picture_that_cannot_be_used_says_why(response, why):
    with pytest.raises(ValueError, match=why):
        cytonn_images.fetch_one("https://hr.test/p.png", "hr.test", client_for(lambda r: response))


def test_a_dropped_connection_is_a_reason_not_a_crash():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(ValueError, match="could not be fetched"):
        cytonn_images.fetch_one("https://hr.test/p.png", "hr.test", client_for(handler))


def test_many_pictures_come_back_together_with_the_failures_named():
    def handler(request):
        if request.url.path.endswith("bad.png"):
            return httpx.Response(500)
        return httpx.Response(200, content=PNG if "png" in request.url.path else JPEG)

    urls = [f"https://hr.test/p{i}.png" for i in range(20)] + [
        "https://hr.test/p.jpg",
        "https://hr.test/bad.png",
        "https://hr.test/p0.png",  # asked twice, fetched once
    ]
    seen = []
    got, failed = cytonn_images.fetch_images(
        urls, "hr.test", client=client_for(handler), progress=lambda d, t: seen.append((d, t))
    )
    assert len(got) == 21 and set(failed) == {"https://hr.test/bad.png"}
    assert got["https://hr.test/p.jpg"].content_type == "image/jpeg"
    assert seen[-1] == (22, 22)


# ----------------------------------------------------------------------- not too much of a passage


def pool(n, passages):
    ids = [f"Q{i:03d}" for i in range(n)]
    return ids, {q: passages[i] for i, q in enumerate(ids) if passages[i]}


def test_no_more_than_two_questions_come_from_one_passage_when_there_is_a_choice():
    ids, groups = pool(12, ["A"] * 6 + ["B"] * 2 + [None] * 4)
    for seed in range(60):
        picked = draw(random.Random(seed), ids, 6, groups)
        assert len(picked) == len(set(picked)) == 6
        assert sum(1 for q in picked if groups.get(q) == "A") <= MAX_PER_PASSAGE


def test_a_section_made_mostly_of_one_passage_still_fills_the_paper():
    ids, groups = pool(8, ["A"] * 7 + [None])
    picked = draw(random.Random(1), ids, 5, groups)
    assert len(picked) == 5  # the cap gives way, rather than failing the candidate's start


def test_the_draw_is_the_same_every_time_for_the_same_seed():
    ids, groups = pool(30, ["A"] * 10 + ["B"] * 10 + [None] * 10)
    assert draw(random.Random(5), ids, 8, groups) == draw(random.Random(5), ids, 8, groups)


def test_without_passages_the_draw_is_what_it_always_was():
    ids = [f"Q{i:03d}" for i in range(20)]
    assert draw(random.Random(3), ids, 5, None) == random.Random(3).sample(sorted(ids), 5)


def test_both_samplers_take_the_cap_into_account():
    by_section = {"verbal": [f"V{i}" for i in range(10)], "numerical": [f"N{i}" for i in range(10)]}
    groups = {q: "P" for q in by_section["verbal"]}  # every verbal question hangs off one passage
    paper = blueprint_sample(random.Random(2), by_section, {"verbal": 4, "numerical": 3}, groups)
    # the cap gives way when there is nothing else to take
    assert len([q for q in paper if q.startswith("V")]) == 4
    spread = balanced_sample(random.Random(2), by_section, 6, {"N0": "x", "N1": "x", "N2": "x"})
    assert len(spread) == 6
