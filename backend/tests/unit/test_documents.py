"""Reading the words out of uploaded documents. Every format is built here, byte by byte, so no
binary fixture is kept in the repository."""

import io
import zipfile

import pytest

from app.errors import ApiError
from app.services import documents
from app.services.documents import extract

PEOPLE = [
    ["Name", "Email"],
    ["Ada Lovelace", "ada@example.org"],
    ["Grace Hopper", "grace@navy.test"],
]
CSV_PEOPLE = "Name,Email\nAda Lovelace,ada@example.org\nGrace Hopper,grace@navy.test\n"


def refused(data: bytes, want="text") -> ApiError:
    with pytest.raises(ApiError) as caught:
        extract(data, want)
    return caught.value


# ------------------------------------------------------------------------------------ builders


def zipped(files: dict[str, str | bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in files.items():
            zf.writestr(name, body)
    return out.getvalue()


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def paragraph(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def word_table(rows) -> str:
    cells = lambda row: "".join(f"<w:tc>{paragraph(c)}</w:tc>" for c in row)  # noqa: E731
    return "<w:tbl>" + "".join(f"<w:tr>{cells(r)}</w:tr>" for r in rows) + "</w:tbl>"


def docx(body: str, head: str = "") -> bytes:
    xml = f"{head}<w:document {W}><w:body>{body}</w:body></w:document>"
    return zipped({"[Content_Types].xml": "<Types/>", "word/document.xml": xml})


SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def xlsx(rows, other_sheet=None) -> bytes:
    shared: list[str] = []

    def cell(r, c, value):
        ref = f"{chr(65 + c)}{r + 1}"
        if isinstance(value, str):
            shared.append(value)
            return f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>'
        return f'<c r="{ref}"><v>{value}</v></c>'

    def cells_of(r, row):
        return "".join(cell(r, c, v) for c, v in enumerate(row) if v is not None)

    def sheet(data):
        body = "".join(f'<row r="{r + 1}">{cells_of(r, row)}</row>' for r, row in enumerate(data))
        return f'<worksheet xmlns="{SHEET_NS}"><sheetData>{body}</sheetData></worksheet>'

    first = sheet(rows)
    second = sheet(other_sheet or [["not", "this", "one"]])
    strings = "".join(f"<si><t>{s}</t></si>" for s in shared)
    return zipped(
        {
            "[Content_Types].xml": "<Types/>",
            # the first sheet is not called sheet1.xml, and a second one follows it
            "xl/workbook.xml": (
                f'<workbook xmlns="{SHEET_NS}" xmlns:r="{REL_NS}"><sheets>'
                '<sheet name="Questions" sheetId="1" r:id="rId9"/>'
                '<sheet name="Other" sheetId="2" r:id="rId8"/></sheets></workbook>'
            ),
            "xl/_rels/workbook.xml.rels": (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId9" Target="worksheets/sheet7.xml"/>'
                '<Relationship Id="rId8" Target="worksheets/sheet2.xml"/></Relationships>'
            ),
            "xl/sharedStrings.xml": f'<sst xmlns="{SHEET_NS}">{strings}</sst>',
            "xl/worksheets/sheet7.xml": first,
            "xl/worksheets/sheet2.xml": second,
        }
    )


def pptx(*slides: tuple[int, list[str]]) -> bytes:
    files: dict[str, str | bytes] = {"[Content_Types].xml": "<Types/>"}
    for number, lines in slides:
        paras = "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in lines)
        files[f"ppt/slides/slide{number}.xml"] = (
            '<p:sld xmlns:p="urn:p" xmlns:a="urn:a"><p:cSld><p:spTree><p:sp><p:txBody>'
            f"{paras}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
        )
    return zipped(files)


ODF_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
)


def odf(mimetype: str, body: str) -> bytes:
    return zipped(
        {
            "mimetype": f"application/vnd.oasis.opendocument.{mimetype}",
            "content.xml": (
                f"<office:document-content {ODF_NS}><office:body>{body}</office:body>"
                "</office:document-content>"
            ),
        }
    )


def pdf(text: str | None) -> bytes:
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET" if text else ""
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out


# ------------------------------------------------------------------------------- plain content


def test_plain_text_comes_back_as_it_is():
    result = extract(CSV_PEOPLE.encode())
    assert (result.kind, result.text) == ("text", CSV_PEOPLE)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "cp1252"], ids=lambda e: e)
def test_the_common_text_encodings_all_read_the_same(encoding):
    text = "Name,Email\nZoë Müller,zoe@example.org\n"
    assert extract(text.encode(encoding)).text.lstrip("﻿") == text


def test_html_gives_its_words_without_tags_scripts_or_styles():
    page = (
        "<!doctype html><html><head><title>x</title><style>p{color:red}</style></head><body>"
        "<script>alert(1)</script><p>Dear all</p>"
        "<table><tr><td>Ada</td><td>ada@example.org</td></tr></table></body></html>"
    )
    result = extract(page.encode())
    assert result.kind == "html"
    assert "alert" not in result.text and "color" not in result.text and "<" not in result.text
    assert "Dear all" in result.text and "Ada\tada@example.org" in result.text


def test_rtf_gives_its_words_with_accents_and_paragraphs():
    rtf = (
        "{|rtf1|ansi{|fonttbl{|f0 Arial;}}{|*|generator Word;}"
        "|f0 Dear |b Ada|b0|par Caf|'e9 |u8364?|par}"
    )
    rtf = rtf.replace("|", chr(92))  # a backslash, written once instead of ten times
    result = extract(rtf.encode("latin-1"))
    assert result.kind == "rtf"
    assert result.text == "Dear Ada\nCafé €"
    assert "Arial" not in result.text and "generator" not in result.text


# ------------------------------------------------------------------------------------ Word


def test_a_word_file_gives_its_paragraphs_and_its_tables_as_tab_separated_rows():
    data = docx(paragraph("Invitations") + word_table(PEOPLE[1:]) + paragraph("Thanks"))
    result = extract(data)
    assert result.kind == "docx"
    assert result.text.splitlines() == [
        "Invitations",
        "Ada Lovelace\tada@example.org",
        "Grace Hopper\tgrace@navy.test",
        "Thanks",
    ]


def test_a_word_table_can_be_asked_for_as_csv_rows():
    data = docx(paragraph("intro") + word_table(PEOPLE))
    result = extract(data, "table")
    assert (result.kind, result.text) == ("docx", CSV_PEOPLE)


def test_a_word_file_without_a_table_is_not_a_table():
    assert refused(docx(paragraph("only words")), "table").code == "no_table_found"


# ----------------------------------------------------------------------------------- Excel


def test_a_spreadsheet_gives_its_first_sheet_as_csv_whatever_the_sheet_is_called():
    result = extract(xlsx(PEOPLE))
    assert (result.kind, result.text) == ("xlsx", CSV_PEOPLE)
    assert "not,this,one" not in result.text  # the second sheet is left alone


def test_a_spreadsheet_keeps_empty_cells_in_place_and_numbers_as_numbers():
    data = xlsx([["question_id", "section", "n"], ["q1", None, 42]])
    assert extract(data, "table").text == "question_id,section,n\nq1,,42\n"


# ---------------------------------------------------------------------------- slides, OpenDocument


def test_slides_are_read_in_numeric_order():
    data = pptx((10, ["Last slide"]), (2, ["Second", "More"]), (1, ["First"]))
    result = extract(data)
    assert (result.kind, result.text) == ("pptx", "First\nSecond\nMore\nLast slide")


def test_an_odf_text_document_gives_headings_paragraphs_and_table_rows():
    body = (
        "<office:text><text:h>Heading</text:h><text:p>One<text:tab/>two</text:p>"
        "<table:table><table:table-row><table:table-cell><text:p>Ada</text:p></table:table-cell>"
        "<table:table-cell><text:p>ada@example.org</text:p></table:table-cell></table:table-row>"
        "</table:table></office:text>"
    )
    result = extract(odf("text", body))
    assert (result.kind, result.text.splitlines()) == (
        "odt",
        ["Heading", "One\ttwo", "Ada\tada@example.org"],
    )


def test_an_odf_spreadsheet_gives_csv_and_ignores_the_run_of_empty_cells():
    def row(*values):
        cells = "".join(
            f"<table:table-cell><text:p>{v}</text:p></table:table-cell>" for v in values
        )
        return f"<table:table-row>{cells}" + (
            '<table:table-cell table:number-columns-repeated="1000"/></table:table-row>'
        )

    body = "<office:spreadsheet><table:table>" + row("Name", "Email") + row("Ada", "a@example.org")
    body += "</table:table></office:spreadsheet>"
    result = extract(odf("spreadsheet", body), "table")
    assert (result.kind, result.text) == ("ods", "Name,Email\nAda,a@example.org\n")


def test_an_odf_presentation_is_read_as_lines():
    body = "<office:presentation><text:p>Slide words</text:p></office:presentation>"
    assert extract(odf("presentation", body)).text == "Slide words"


# ------------------------------------------------------------------------------------ PDF


def test_a_pdf_gives_its_text():
    result = extract(pdf("Ada Lovelace, ada@example.org"))
    assert (result.kind, result.text.strip()) == ("pdf", "Ada Lovelace, ada@example.org")


def test_a_pdf_is_never_treated_as_a_table_even_if_it_has_commas():
    assert refused(pdf("Name, Email"), "table").code == "no_table_found"


def test_a_scanned_pdf_with_no_text_says_so():
    error = refused(pdf(None))
    assert (error.status_code, error.code) == (422, "scanned_pdf")


def test_a_password_protected_pdf_says_so():
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(pdf("secret words"))))
    try:
        writer.encrypt("a-password", algorithm="RC4-128")
    except Exception:  # noqa: BLE001  (a build of pypdf without the cipher it needs)
        pytest.skip("this pypdf cannot write an encrypted file")
    locked = io.BytesIO()
    writer.write(locked)
    assert refused(locked.getvalue()).code == "password_protected"


def test_a_damaged_pdf_is_unreadable_not_a_crash():
    assert refused(b"%PDF-1.7\n1 0 obj << /Broken").code in ("unreadable_file", "scanned_pdf")


# ------------------------------------------------------------------------- what is turned away


def test_the_old_binary_office_formats_are_refused_with_a_way_forward():
    error = refused(bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 600)
    assert (error.status_code, error.code) == (415, "legacy_office_format")
    assert "docx" in error.extra["formats"]


def test_a_file_that_is_not_written_content_is_refused():
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + bytes(range(256)) * 4
    assert refused(png).code == "unsupported_type"
    assert refused(bytes([0, 1, 2, 3]) * 100).code == "unsupported_type"


def test_a_zip_that_is_not_a_document_is_refused():
    assert refused(zipped({"notes.txt": "hello"})).code == "unsupported_type"
    assert refused(b"PK\x03\x04 not really a zip").code == "unreadable_file"


@pytest.mark.parametrize("blank", [b"", b"   \n\t ", b"\r\n"])
def test_an_empty_file_is_refused(blank):
    assert refused(blank).code == "empty_file"


def test_a_document_with_no_words_in_it_is_refused():
    assert refused(docx(paragraph(""))).code == "no_text_found"


def test_a_file_over_the_size_limit_is_refused():
    error = refused(b"a" * (documents.MAX_BYTES + 1))
    assert (error.status_code, error.code) == (413, "file_too_large")


def test_text_far_beyond_a_sensible_list_is_refused():
    big = ("x" * 99 + "\n") * (documents.MAX_TEXT_CHARS // 100 + 10)
    assert refused(big.encode()).code == "too_much_text"


def test_a_zip_bomb_is_refused_before_it_is_unpacked():
    huge = docx(" " * (documents.MAX_MEMBER_BYTES + 1))  # compresses to a few kilobytes
    assert len(huge) < 100_000
    assert refused(huge).code == "file_too_large"


def test_xml_that_declares_entities_is_refused():
    attack = (
        '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
    )
    assert refused(docx(paragraph("&b;"), head=attack)).code == "unreadable_file"


def test_the_kind_comes_from_the_bytes_not_from_any_name():
    # the same bytes are a spreadsheet whatever the upload was called; there is no name to trust
    assert extract(xlsx(PEOPLE)).kind == "xlsx"
    assert extract(docx(paragraph("words"))).kind == "docx"


# ------------------------------------------------------------------------------- tables, text


def test_plain_csv_and_tsv_count_as_tables_and_prose_does_not():
    assert extract(CSV_PEOPLE.encode(), "table").text == CSV_PEOPLE
    assert extract(b"a\tb\n1\t2\n", "table").kind == "text"
    assert (
        refused(b"This is a letter about nothing in particular.\nIt has no columns.", "table").code
        == "no_table_found"
    )


def test_a_document_nested_far_too_deeply_is_unreadable_not_a_crash():
    depth = 20_000
    body = "<text:p>" + "<text:span>" * depth + "words" + "</text:span>" * depth + "</text:p>"
    error = refused(odf("text", "<office:text>" + body + "</office:text>"))
    assert (error.status_code, error.code) == (422, "unreadable_file")
