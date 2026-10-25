"""Loading Cytonn's questions with the pictures they depend on."""

import hashlib

from sqlalchemy import func, select
from sqlalchemy.orm import undefer

from app.models import Question, QuestionImage
from app.services.cytonn_bank import load_bank, parse_sections
from app.services.cytonn_images import ImageBlob

URL = "https://hr.cytonn.com/storage/aptitude/q92.PNG"
PNG = b"\x89PNG\r\n\x1a\n" + b"first picture"
OTHER = b"\x89PNG\r\n\x1a\n" + b"second picture"


def blob(data: bytes) -> ImageBlob:
    return ImageBlob("image/png", data, hashlib.sha256(data).hexdigest())


def question(question_id=1, text=None, urls=(), answers=None):
    text = text or f"What comes next in sequence {question_id}?"
    html = f"<p>{text}</p>" + "".join(f'<p><img src="{u}" alt=""></p>' for u in urls)
    answers = answers or [
        {"id": question_id * 10 + 1, "answer": "Set A", "is_correct": True},
        {"id": question_id * 10 + 2, "answer": "Set B", "is_correct": False},
    ]
    return {"id": question_id, "question": html, "answers": answers}


def bank_of(*questions):
    return parse_sections(
        {"data": [{"name": "Logical", "time_per_question": "1.75", "questions": list(questions)}]}
    )


def pictures_of(db, question_id):
    return list(
        db.scalars(
            select(QuestionImage)
            .where(QuestionImage.question_id == question_id)
            .order_by(QuestionImage.position)
            .options(undefer(QuestionImage.data))
        )
    )


def test_a_question_is_stored_with_its_picture_and_a_marker_where_it_goes(db):
    result = load_bank(db, bank_of(question(1, urls=[URL])), images={URL: blob(PNG)})

    assert (result.created, result.images_stored, result.no_image) == (1, 1, [])
    stored = db.get(Question, "C1")
    assert stored.text == "What comes next in sequence 1?\n\n[[image 1]]"
    (picture,) = pictures_of(db, "C1")
    assert (picture.position, picture.content_type, picture.source_url) == (1, "image/png", URL)
    assert picture.data == PNG and picture.sha256 == hashlib.sha256(PNG).hexdigest()


def test_a_question_whose_picture_is_not_available_is_left_out_and_reported(db):
    result = load_bank(db, bank_of(question(1, urls=[URL]), question(2)), images={})

    assert result.no_image == [1]
    assert (result.created, result.by_section) == (1, {"logical": 1})
    assert db.get(Question, "C1") is None and db.get(Question, "C2") is not None


def test_loading_again_needs_no_pictures_and_keeps_the_stored_ones(db):
    load_bank(db, bank_of(question(1, urls=[URL])), images={URL: blob(PNG)})
    ids_before = list(db.scalars(select(QuestionImage.id)))

    again = load_bank(db, bank_of(question(1, urls=[URL])))  # nothing fetched this time

    assert (again.created, again.updated, again.unchanged, again.no_image) == (0, 0, 1, [])
    assert list(db.scalars(select(QuestionImage.id))) == ids_before


def test_new_wording_with_the_same_picture_is_an_update_that_keeps_the_picture(db):
    load_bank(db, bank_of(question(1, urls=[URL])), images={URL: blob(PNG)})

    again = load_bank(db, bank_of(question(1, text="A reworded question?", urls=[URL])))

    assert (again.updated, again.no_image) == (1, [])
    assert db.get(Question, "C1").text.startswith("A reworded question?")
    assert [p.data for p in pictures_of(db, "C1")] == [PNG]


def test_a_new_picture_replaces_the_old_one(db):
    load_bank(db, bank_of(question(1, urls=[URL])), images={URL: blob(PNG)})
    new_url = "https://hr.cytonn.com/storage/aptitude/q92-v2.PNG"

    again = load_bank(db, bank_of(question(1, urls=[new_url])), images={new_url: blob(OTHER)})

    assert again.updated == 1 and again.images_stored == 1
    pictures = pictures_of(db, "C1")
    assert [(p.source_url, p.data) for p in pictures] == [(new_url, OTHER)]
    assert db.scalar(select(func.count()).select_from(QuestionImage)) == 1


def test_several_pictures_keep_their_order_and_their_markers(db):
    second = "https://hr.cytonn.com/storage/aptitude/q93.PNG"
    load_bank(
        db, bank_of(question(1, urls=[URL, second])), images={URL: blob(PNG), second: blob(OTHER)}
    )
    assert [p.source_url for p in pictures_of(db, "C1")] == [URL, second]
    text = db.get(Question, "C1").text
    assert text.index("[[image 1]]") < text.index("[[image 2]]")


def test_listing_a_questions_pictures_does_not_load_their_bytes(db):
    load_bank(db, bank_of(question(1, urls=[URL])), images={URL: blob(PNG)})
    db.expire_all()
    stored = db.scalar(select(Question).where(Question.id == "C1"))
    (picture,) = stored.images
    assert "data" not in picture.__dict__  # deferred: the bytes are fetched only when asked for
    assert picture.position == 1


def test_a_passage_key_is_stored_so_a_paper_can_limit_one_passage(db):
    passage = (
        "A long reading passage that goes on for well over one hundred characters, so that "
        "it counts as one. "
    )
    load_bank(
        db,
        bank_of(question(1, text=passage + "First?"), question(2, text=passage + "Second?")),
    )
    keys = {q.id: q.passage_key for q in db.scalars(select(Question))}
    assert keys["C1"] == keys["C2"] and keys["C1"] is not None


def test_a_dry_run_style_mapping_that_claims_every_picture_is_honoured_even_when_it_looks_empty(db):
    """A mapping with no entries of its own but which can answer for any address (what the dry run
    passes) is not the same as no mapping at all."""
    from collections.abc import Iterator, Mapping

    class Everything(Mapping[str, ImageBlob]):
        def __getitem__(self, url: str) -> ImageBlob:
            return blob(PNG)

        def __contains__(self, url: object) -> bool:
            return True

        def __iter__(self) -> Iterator[str]:
            return iter(())

        def __len__(self) -> int:
            return 0

    result = load_bank(db, bank_of(question(1, urls=[URL])), images=Everything())
    assert (result.created, result.no_image) == (1, [])
